"""Per-call orchestrator: owns the SIP socket, all six tasks, and cleanup.

Lifecycle::

    async with CallSession(job, services) as session:
        await session.run()

``run()`` returns when the call has fully ended (caller hangup, AI-terminal
tool, error fallback, or shutdown). Cleanup runs in __aexit__ and is
idempotent so a partially-set-up session still tears down cleanly.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import psycopg
import structlog

from .audio_in import AudioInPipeline, STTFinal, STTPartial
from .audio_out import AudioOutPipeline, SpeechRequest
from .barge_in import should_barge_in
from .config import WorkerConfig
from .conversation import ConversationLoop, ConversationSettings
from .humanize import DEFAULT_DISCLOSURE, pick_opener
from .kb_search import KBSearch
from .metrics import M_ACTIVE, M_BARGE_INS, M_CALLS
from .prompt_builder import PromptContext, build_system_prompt
from .recorder import Recorder, upload_recording
from .sip_protocol import (
    FRAME_AUDIO_IN,
    FRAME_AUDIO_OUT,
    FRAME_CONTROL,
    FRAME_DTMF,
    FRAME_HANGUP,
    PCM_FRAME_BYTES,
    encode_frame,
    read_frame,
)
from .tools import TOOL_SCHEMAS, ToolContext, ToolResult
from .transcript_writer import TranscriptWriter
from .vici_client import Lead, ViciClient

log = structlog.get_logger().bind(component="call_session")


# ---------------------------------------------------------------------------
# Shared services injected by main.py
# ---------------------------------------------------------------------------

@dataclass
class WorkerServices:
    cfg: WorkerConfig
    minio_client: Any = None     # minio.Minio | None


# ---------------------------------------------------------------------------
# Job payload — accepts both Redis-list and Redis-stream shapes
# ---------------------------------------------------------------------------

@dataclass
class CallJob:
    call_id: str
    deployment_id: str
    sip_socket_path: str
    vici_uniqueid: str | None = None
    vici_lead_id: str | None = None
    phone_number: str | None = None
    campaign: str | None = None

    @classmethod
    def from_payload(cls, raw: dict | bytes | str) -> "CallJob":
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", "replace")
        if isinstance(raw, str):
            raw = json.loads(raw)
        return cls(
            call_id=str(raw.get("call_id") or raw.get("id") or ""),
            deployment_id=str(raw.get("deployment_id") or ""),
            sip_socket_path=str(raw.get("sip_socket_path")
                                or raw.get("socket_path") or ""),
            vici_uniqueid=raw.get("vici_uniqueid") or None,
            vici_lead_id=raw.get("vici_lead_id") or None,
            phone_number=raw.get("phone_number") or raw.get("vici_phone") or None,
            campaign=raw.get("campaign") or raw.get("vici_campaign") or None,
        )


# ---------------------------------------------------------------------------
# Agent config loaded from Postgres
# ---------------------------------------------------------------------------

@dataclass
class AgentConfig:
    agent_id: str
    name: str
    persona: dict = field(default_factory=dict)
    voice_id: str | None = None
    language: str = "en"
    script: dict = field(default_factory=dict)
    scenario_tree: dict = field(default_factory=dict)
    kb_collection_id: str | None = None
    campaign_id: str | None = None


@dataclass
class CampaignConfig:
    """Loaded alongside the agent if either the agent or the deployment links
    to an aipanel campaign. Drives methodology hints + few-shot injection."""
    campaign_id: str
    name: str = ""
    methodology: str = ""
    objective: str = ""
    persona_template: dict = field(default_factory=dict)
    script_template: dict = field(default_factory=dict)
    few_shot_pool: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# CallSession
# ---------------------------------------------------------------------------

class CallSession:
    def __init__(
        self,
        job: CallJob,
        services: WorkerServices,
    ) -> None:
        self.job = job
        self.services = services
        self.cfg = services.cfg

        # External handles set up in __aenter__.
        self._sip_reader: asyncio.StreamReader | None = None
        self._sip_writer: asyncio.StreamWriter | None = None
        self._agent: AgentConfig | None = None
        self._campaign: CampaignConfig | None = None
        self._lead: Lead | None = None
        self._vici: ViciClient | None = None
        self._kb: KBSearch | None = None
        self._transcripts: TranscriptWriter | None = None
        self._recorder: Recorder | None = None

        # Queues + events shared between tasks.
        self._frames_out: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        self._transcript_finals: asyncio.Queue[STTFinal] = asyncio.Queue()
        self._transcript_partials: asyncio.Queue[STTPartial] = asyncio.Queue()
        self._speech_queue: asyncio.Queue[SpeechRequest | None] = \
            asyncio.Queue(maxsize=16)
        self._call_ended = asyncio.Event()
        self._tts_cancel = asyncio.Event()
        self._is_speaking = asyncio.Event()      # set while audio_out is active

        # Set after a terminal tool / error.
        self._terminal_outcome: ToolResult | None = None
        self._started_at = datetime.now(timezone.utc)

        # Pipelines.
        self._audio_in: AudioInPipeline | None = None
        self._audio_out: AudioOutPipeline | None = None
        self._conversation: ConversationLoop | None = None

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "CallSession":
        log.info("call_setup_start",
                 call_id=self.job.call_id,
                 deployment_id=self.job.deployment_id,
                 socket=self.job.sip_socket_path)

        await self._connect_sip()
        await self._await_call_context()
        await self._load_agent()

        self._vici = await ViciClient(
            base_url=self.cfg.vici_url,
            enabled=self.cfg.vici_enabled,
        ).__aenter__()
        self._lead = await self._vici.get_lead(self.job.vici_lead_id)

        self._kb = KBSearch(self.cfg.db_dsn, self._agent.kb_collection_id)
        self._transcripts = TranscriptWriter(self.cfg.db_dsn, self.job.call_id)
        await self._transcripts.start(
            deployment_id=self.job.deployment_id,
            vici_uniqueid=self.job.vici_uniqueid,
            vici_lead_id=self.job.vici_lead_id,
            phone_number=self.job.phone_number,
        )

        if self.cfg.recording_enabled:
            self._recorder = Recorder(self.job.call_id, self.cfg.recording_dir)
            self._recorder.open()

        # Pipelines.
        self._audio_in = AudioInPipeline(
            stt_ws_url=f"{self._http_to_ws(self.cfg.stt_url)}/v1/stt/stream",
            language=self._agent.language,
            finals_queue=self._transcript_finals,
            partials_queue=self._transcript_partials,
        )
        self._audio_out = await AudioOutPipeline(
            tts_url=self.cfg.tts_url,
            voice_id_default=self._agent.voice_id or "",
            speech_queue=self._speech_queue,
            frames_out_queue=self._frames_out,
            cancel_event=self._tts_cancel,
            on_speech_started=self._on_speech_started,
            on_speech_finished=self._on_speech_finished,
        ).__aenter__()

        tool_ctx = ToolContext(
            call_id=self.job.call_id,
            deployment_id=self.job.deployment_id,
            vici_lead_id=self.job.vici_lead_id,
            vici_uniqueid=self.job.vici_uniqueid,
            vici_client=self._vici,
            kb_search=self._kb,
            transcript_writer=self._transcripts,
        )
        self._conversation = await ConversationLoop(
            settings=ConversationSettings(
                model=self.cfg.llm_model,
                temperature=self.cfg.llm_temperature,
                max_tokens=self.cfg.llm_max_response_tokens,
                request_timeout_sec=self.cfg.llm_request_timeout_sec,
                response_delay_ms_min=self.cfg.response_delay_ms_min,
                response_delay_ms_max=self.cfg.response_delay_ms_max,
                filler_frequency=self.cfg.filler_frequency,
                voice_id=self._agent.voice_id,
            ),
            llm_url=self.cfg.llm_url,
            speech_queue=self._speech_queue,
            tool_ctx=tool_ctx,
            cancel_event=self._tts_cancel,
            call_ended=self._call_ended,
        ).__aenter__()

        # System prompt + opener.
        self._conversation.set_system_prompt(self._build_system_prompt())
        opener = self._pick_opener()
        if opener:
            self._conversation.enqueue_opener(opener)

        log.info("call_ready", call_id=self.job.call_id)
        M_ACTIVE.inc()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._cleanup()

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def run(self) -> ToolResult | None:
        """Spin all six tasks; return the terminal ToolResult (or None)."""
        tasks = [
            asyncio.create_task(self._sip_read_loop(), name="sip-read"),
            asyncio.create_task(self._sip_write_loop(), name="sip-write"),
            asyncio.create_task(self._audio_in.run(), name="stt"),
            asyncio.create_task(self._audio_out.run(), name="audio-out"),
            asyncio.create_task(
                self._conversation.run(self._transcript_finals),
                name="conversation",
            ),
            asyncio.create_task(self._barge_in_loop(), name="barge-in"),
        ]
        try:
            await self._call_ended.wait()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        return (self._conversation.terminal_result
                if self._conversation else None)

    # ------------------------------------------------------------------
    # SIP socket I/O
    # ------------------------------------------------------------------

    async def _connect_sip(self) -> None:
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_unix_connection(self.job.sip_socket_path),
                timeout=5.0,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise RuntimeError(
                f"could not connect to SIP socket {self.job.sip_socket_path}: {exc}"
            ) from exc
        self._sip_reader = r
        self._sip_writer = w

    async def _await_call_context(self) -> None:
        """SIP service sends a CONTROL frame with CallContext as the first frame.

        We accept whatever we get and only validate ``call_id`` matches.
        """
        try:
            frame = await asyncio.wait_for(read_frame(self._sip_reader), timeout=5.0)
        except asyncio.TimeoutError:
            log.warning("sip_no_initial_control",
                        call_id=self.job.call_id)
            return
        if frame is None:
            raise RuntimeError("SIP socket closed before initial control frame")
        ftype, payload = frame
        if ftype != FRAME_CONTROL:
            log.warning("sip_unexpected_first_frame",
                        ftype=ftype, len=len(payload))
            return
        try:
            ctx = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("sip_initial_control_invalid")
            return
        if ctx.get("call_id") and ctx["call_id"] != self.job.call_id:
            log.warning("sip_call_id_mismatch",
                        job_id=self.job.call_id,
                        sip_id=ctx.get("call_id"))

    async def _sip_read_loop(self) -> None:
        assert self._sip_reader is not None
        while not self._call_ended.is_set():
            frame = await read_frame(self._sip_reader)
            if frame is None:
                log.info("sip_socket_eof", call_id=self.job.call_id)
                self._call_ended.set()
                return
            ftype, payload = frame
            if ftype == FRAME_AUDIO_IN:
                if self._audio_in is not None:
                    self._audio_in.feed(payload)
                if self._recorder is not None:
                    self._recorder.write_inbound(payload)
            elif ftype == FRAME_HANGUP:
                log.info("sip_hangup_received", call_id=self.job.call_id)
                self._call_ended.set()
                return
            elif ftype == FRAME_DTMF:
                digit = payload.decode("ascii", "replace")
                log.info("dtmf", call_id=self.job.call_id, digit=digit)
                self._transcripts and self._transcripts.write(
                    "dtmf", {"digit": digit}
                )
            elif ftype == FRAME_CONTROL:
                # Future: SIP-side control events (e.g. mute, hold).
                pass

    async def _sip_write_loop(self) -> None:
        assert self._sip_writer is not None
        while not self._call_ended.is_set():
            try:
                frame = await asyncio.wait_for(self._frames_out.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            try:
                self._sip_writer.write(encode_frame(FRAME_AUDIO_OUT, frame))
                await self._sip_writer.drain()
            except (ConnectionError, OSError) as exc:
                log.warning("sip_write_failed",
                            call_id=self.job.call_id, error=str(exc))
                self._call_ended.set()
                return
            if self._recorder is not None:
                self._recorder.write_outbound(frame)

    # ------------------------------------------------------------------
    # Barge-in monitor
    # ------------------------------------------------------------------

    async def _barge_in_loop(self) -> None:
        last_partial_at: float | None = None
        while not self._call_ended.is_set():
            try:
                p: STTPartial = await asyncio.wait_for(
                    self._transcript_partials.get(), timeout=0.5
                )
            except asyncio.TimeoutError:
                last_partial_at = None
                continue

            duration_ms = (p.received_at - last_partial_at) * 1000.0 if last_partial_at else 0.0
            last_partial_at = last_partial_at or p.received_at

            decision = should_barge_in(
                partial_text=p.text,
                partial_stability=p.stability,
                partial_duration_ms=duration_ms,
                is_speaking=self._is_speaking.is_set(),
                min_words=self.cfg.barge_in_min_words,
                min_duration_ms=self.cfg.barge_in_min_duration_ms,
                stability_threshold=self.cfg.barge_in_stability_threshold,
            )
            if decision.cancel_tts:
                log.info("barge_in_triggered",
                         call_id=self.job.call_id,
                         partial_preview=p.text[:60])
                M_BARGE_INS.inc()
                self._tts_cancel.set()
                # Drain the playback queue so we go silent immediately.
                while not self._frames_out.empty():
                    try:
                        self._frames_out.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                self._transcripts and self._transcripts.write("barge_in", {
                    "partial_text": p.text,
                })

    def _on_speech_started(self, req: SpeechRequest) -> None:
        self._is_speaking.set()

    def _on_speech_finished(self, req: SpeechRequest, was_cancelled: bool) -> None:
        self._is_speaking.clear()

    # ------------------------------------------------------------------
    # Agent + prompt
    # ------------------------------------------------------------------

    async def _load_agent(self) -> None:
        try:
            agent, campaign = await asyncio.to_thread(self._sync_load_agent)
        except psycopg.Error as exc:
            log.warning("agent_load_failed",
                        deployment_id=self.job.deployment_id, error=str(exc))
            agent, campaign = AgentConfig(agent_id="", name="aipanel agent"), None
        self._agent = agent
        self._campaign = campaign
        if campaign is not None:
            log.info("campaign_loaded",
                     deployment_id=self.job.deployment_id,
                     campaign_id=campaign.campaign_id,
                     methodology=campaign.methodology,
                     few_shot_examples=len(campaign.few_shot_pool))

    def _sync_load_agent(self) -> tuple[AgentConfig, CampaignConfig | None]:
        sql = (
            "SELECT a.id::text, a.name, a.persona, a.voice_id::text, a.language, "
            "       a.script, a.scenario_tree, a.kb_collection_id::text, "
            "       a.campaign_id::text, "
            "       d.aipanel_campaign_id::text "
            "  FROM deployments d "
            "  JOIN agents a ON d.agent_id = a.id "
            " WHERE d.id = %s"
        )
        with psycopg.connect(self.cfg.db_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (self.job.deployment_id,))
                row = cur.fetchone()
                if not row:
                    return (AgentConfig(agent_id="", name="aipanel agent"), None)
                agent = AgentConfig(
                    agent_id=row[0],
                    name=row[1],
                    persona=row[2] or {},
                    voice_id=row[3] or None,
                    language=row[4] or "en",
                    script=row[5] or {},
                    scenario_tree=row[6] or {},
                    kb_collection_id=row[7] or None,
                    campaign_id=row[8] or None,
                )
                # Deployment-level link wins over agent-level link if both
                # are set — operator might want to override per deployment.
                campaign_id = row[9] or row[8]
                if not campaign_id:
                    return (agent, None)
                cur.execute(
                    "SELECT id::text, name, methodology, objective, "
                    "       persona_template, script_template, few_shot_pool "
                    "  FROM campaigns WHERE id = %s",
                    (campaign_id,),
                )
                crow = cur.fetchone()
                if not crow:
                    return (agent, None)
                campaign = CampaignConfig(
                    campaign_id=crow[0],
                    name=crow[1] or "",
                    methodology=crow[2] or "",
                    objective=crow[3] or "",
                    persona_template=crow[4] or {},
                    script_template=crow[5] or {},
                    few_shot_pool=list(crow[6] or []),
                )
        return (agent, campaign)

    def _build_system_prompt(self) -> str:
        assert self._agent is not None and self._lead is not None

        # If a campaign is linked, merge templates UNDER the agent's own
        # values (agent overrides). This lets a campaign provide defaults
        # for personas/scripts that any new agent in the campaign inherits.
        merged_persona = dict(self._agent.persona or {})
        merged_script  = dict(self._agent.script or {})
        methodology = ""
        objective = ""
        few_shot: list[dict] = []
        if self._campaign is not None:
            for k, v in (self._campaign.persona_template or {}).items():
                merged_persona.setdefault(k, v)
            for k, v in (self._campaign.script_template or {}).items():
                merged_script.setdefault(k, v)
            methodology = self._campaign.methodology
            objective   = self._campaign.objective
            few_shot    = list(self._campaign.few_shot_pool or [])

        ctx = PromptContext(
            persona=merged_persona,
            lead={
                "name": self._lead.name,
                "phone_number": self._lead.phone_number,
                "email": self._lead.email,
            },
            campaign={"purpose": self.job.campaign or "today's outreach"},
            script=merged_script,
            objections=merged_script.get("objections"),
            additional_guidelines=merged_persona.get("guidelines", ""),
            disclosure_response=merged_persona.get(
                "disclosure_response", DEFAULT_DISCLOSURE
            ),
            kb_enabled=bool(self._agent.kb_collection_id),
            tools=TOOL_SCHEMAS,
            methodology=methodology,
            campaign_objective=objective,
            few_shot_examples=few_shot,
        )
        return build_system_prompt(ctx)

    def _pick_opener(self) -> str:
        assert self._agent is not None
        openers = self._agent.script.get("openings") or self._agent.script.get("opening")
        if isinstance(openers, str):
            return openers
        if isinstance(openers, list) and openers:
            return pick_opener(openers)
        return ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _http_to_ws(http_url: str) -> str:
        if http_url.startswith("https://"):
            return "wss://" + http_url[len("https://"):]
        if http_url.startswith("http://"):
            return "ws://" + http_url[len("http://"):]
        return http_url

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def _cleanup(self) -> None:
        log.info("call_cleanup_start", call_id=self.job.call_id)
        terminal = self._conversation.terminal_result if self._conversation else None
        outcome = self._classify_outcome(terminal)
        dispo = (terminal.dispo_code if terminal else "ABANDON")

        # Stop pipelines.
        for closer, name in (
            (self._audio_in.stop if self._audio_in else None, "audio_in"),
            (self._audio_out.stop if self._audio_out else None, "audio_out"),
            (self._conversation.stop if self._conversation else None, "conversation"),
        ):
            if closer is None:
                continue
            try:
                await asyncio.wait_for(closer(), timeout=2.0)
            except (asyncio.TimeoutError, Exception) as exc:                # noqa: BLE001
                log.warning("pipeline_close_failed",
                            pipeline=name, error=str(exc))

        # Send HANGUP to SIP and close the socket.
        if self._sip_writer is not None:
            try:
                self._sip_writer.write(encode_frame(FRAME_HANGUP))
                await self._sip_writer.drain()
            except Exception:                                # pragma: no cover
                pass
            try:
                self._sip_writer.close()
                await self._sip_writer.wait_closed()
            except Exception:                                # pragma: no cover
                pass

        # Vici dispo (best-effort).
        if self._vici is not None:
            try:
                await self._vici.post_disposition(
                    call_id=self.job.call_id,
                    vici_uniqueid=self.job.vici_uniqueid,
                    dispo_code=dispo,
                    notes=(terminal.extra if terminal else {}).get("reason", "")
                          if terminal else "",
                )
            except Exception as exc:                         # pragma: no cover
                log.warning("vici_dispo_failed", error=str(exc))
            try:
                await self._vici.__aexit__(None, None, None)
            except Exception:                                # pragma: no cover
                pass

        # Recording → MinIO.
        recording_path_remote = ""
        if self._recorder is not None:
            local = self._recorder.close()
            if local is not None and self.services.minio_client is not None:
                key = f"{self.job.deployment_id}/{self.job.call_id}.wav"
                key_uploaded = await upload_recording(
                    minio_client=self.services.minio_client,
                    bucket=self.cfg.minio_bucket_recordings,
                    object_name=key,
                    local_path=local,
                )
                if key_uploaded:
                    recording_path_remote = (
                        f"s3://{self.cfg.minio_bucket_recordings}/{key_uploaded}"
                    )

        # Final transcript update.
        duration_sec = max(
            0,
            int((datetime.now(timezone.utc) - self._started_at).total_seconds()),
        )
        if self._transcripts is not None:
            try:
                await self._transcripts.stop(
                    outcome=outcome,
                    dispo_code=dispo,
                    recording_path=recording_path_remote,
                    duration_sec=duration_sec,
                )
            except Exception as exc:                         # pragma: no cover
                log.warning("transcript_stop_failed", error=str(exc))

        M_ACTIVE.dec()
        M_CALLS.labels(outcome=outcome).inc()
        log.info("call_cleanup_done",
                 call_id=self.job.call_id,
                 outcome=outcome, dispo=dispo,
                 duration_sec=duration_sec)

    @staticmethod
    def _classify_outcome(terminal: ToolResult | None) -> str:
        if terminal is None:
            return "abandoned"
        if not terminal.success:
            return "error"
        return terminal.name
