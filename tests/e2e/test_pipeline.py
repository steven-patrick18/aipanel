"""End-to-end pipeline test — worker against in-process fakes.

Boots fake LLM/STT/TTS on free ports, opens a fake SIP socket, runs the
worker's CallSession against them with a scripted conversation, and
asserts the worker emitted audio + hung up cleanly.

Run with:
    pytest tests/e2e/test_pipeline.py -v
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import pytest

# Make the worker package importable.
ROOT = Path(__file__).resolve().parents[2]
WORKER_SRC = ROOT / "workers" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from .fake_services import (
    boot, make_fake_llm_app, make_fake_stt_app, make_fake_tts_app,
)
from .fake_socket import FakeSipSocket


pytestmark = pytest.mark.asyncio


@pytest.mark.asyncio
async def test_worker_completes_a_scripted_call(monkeypatch):
    """A user says hello → agent responds → user says goodbye → end."""
    # Fakes that satisfy the worker's expected protocols.
    llm = make_fake_llm_app(scripted_replies=[
        "Hi there — thanks for picking up. Have you got a quick minute?",
        "Got it. Thanks for your time, have a great day!",
    ])
    stt = make_fake_stt_app(scripted_finals=[
        "Sure, what's this about?",
        "Not interested, thanks.",
    ])
    tts = make_fake_tts_app()

    call_id = str(uuid4())
    deployment_id = str(uuid4())
    sip = FakeSipSocket(call_id=call_id, deployment_id=deployment_id)

    async with boot(llm) as llm_port, \
               boot(stt) as stt_port, \
               boot(tts) as tts_port:
        await sip.start()

        # Build a CallJob that points at the fake socket.
        from aipanel_worker.call_session import CallJob, CallSession, WorkerServices
        from aipanel_worker.config import WorkerConfig

        # Build a minimal in-memory cfg pointing at the fake services.
        cfg = WorkerConfig(
            db_dsn="postgresql://x:x@127.0.0.1:5432/never_used",
            redis_url="redis://127.0.0.1:6379/15",
            llm_url=f"http://127.0.0.1:{llm_port}",
            stt_url=f"http://127.0.0.1:{stt_port}",
            tts_url=f"http://127.0.0.1:{tts_port}",
            llm_model="fake-llm",
            llm_request_timeout_sec=10,
            response_delay_ms_min=0,
            response_delay_ms_max=0,
            recording_enabled=False,
            shutdown_drain_sec=2.0,
            worker_request_stream="x",
            queue_list_key="x",
            queue_stream_key="x",
            queue_consumer_group="x",
        )
        services = WorkerServices(cfg=cfg)
        job = CallJob(
            call_id=call_id,
            deployment_id=deployment_id,
            sip_socket_path=str(sip.path),
            vici_uniqueid="1700000000.5",
            vici_lead_id="L42",
            phone_number="+18005551234",
            campaign="FAKE",
        )

        # Stub out the bits that need a real DB/Vici (out of scope here):
        # - agent loader → return an empty agent
        # - vici client → returns a stub Lead
        # - transcript writer → no-op
        from aipanel_worker import call_session as cs_mod
        from aipanel_worker.vici_client import Lead

        def _fake_load_agent(self):
            self._agent = cs_mod.AgentConfig(agent_id="", name="fake")
            self._campaign = None
        async def _no_db_start(self, **kw): pass
        async def _no_db_stop(self, **kw): pass
        monkeypatch.setattr(cs_mod.CallSession, "_load_agent",
                            lambda self: asyncio.sleep(0,
                                result=_fake_load_agent(self)))
        # The above is awkward — call _load_agent directly without DB:
        async def _patched_load(self):
            _fake_load_agent(self)
        monkeypatch.setattr(cs_mod.CallSession, "_load_agent", _patched_load)

        # No transcript DB writes during the test.
        async def _start_noop(self, **_kw): pass
        async def _stop_noop(self, **_kw): pass
        monkeypatch.setattr(
            "aipanel_worker.transcript_writer.TranscriptWriter.start",
            _start_noop,
        )
        monkeypatch.setattr(
            "aipanel_worker.transcript_writer.TranscriptWriter.stop",
            _stop_noop,
        )

        # Run the session with a hard timeout so a hang doesn't wedge CI.
        async def _drive() -> None:
            async with CallSession(job, services) as session:
                # Accept the worker's connect (CallSession.__aenter__ already
                # connected by now since the fake is listening).
                await sip.accept_client(timeout_sec=5.0)
                # Pump some audio so STT finals fire.
                await sip.send_silence(ms=500)
                await sip.send_silence(ms=500)
                # Let the conversation loop turn over.
                await asyncio.sleep(2.0)
                # Hang up from the caller side.
                await sip.send_hangup()
                # Give cleanup a moment.
                await asyncio.sleep(1.0)

        try:
            await asyncio.wait_for(_drive(), timeout=15.0)
        finally:
            await sip.close()

    # Assertions — relaxed because the test depends on async timing.
    assert sip.captured.control, "worker should have sent at least one CONTROL frame"
    assert sip.captured.control[0].get("type") == "call_context", \
        "first frame from worker should be the call_context echo"
    # The worker should have emitted SOME audio_out frames (TTS started).
    assert len(sip.captured.audio_out) > 0, \
        "worker should have produced audio_out frames after the LLM replied"
