"""LLM loop: transcript_queue → chat completion → speech_queue or tool dispatch.

v0.5 uses non-streaming chat completions. The trade-off is ~500 ms more
latency per turn vs. token-streaming, in exchange for clean tool-call
handling. To upgrade, switch ``_call_llm`` to ``stream=True`` and split the
``message`` accumulator into a sentence-buffer that flushes to TTS as
sentences complete.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx
import structlog

from .audio_in import STTFinal
from .audio_out import SpeechRequest
from .humanize import inject_filler, response_delay_ms
from .metrics import M_LLM_ERRORS, M_LLM_LATENCY
from .tools import TERMINAL_TOOLS, TOOL_SCHEMAS, ToolContext, ToolResult, dispatch

log = structlog.get_logger().bind(component="conversation")


# ---------------------------------------------------------------------------
# Per-call settings
# ---------------------------------------------------------------------------

@dataclass
class ConversationSettings:
    model: str
    temperature: float
    max_tokens: int
    request_timeout_sec: int
    response_delay_ms_min: int
    response_delay_ms_max: int
    filler_frequency: float
    voice_id: str | None
    enable_tools: bool = True


@dataclass
class _ConversationState:
    messages: list[dict] = field(default_factory=list)
    turns_since_filler: int = 99   # high so first turn is eligible
    terminal_pending: ToolResult | None = None


# ---------------------------------------------------------------------------
# ConversationLoop
# ---------------------------------------------------------------------------

class ConversationLoop:
    """The main brain. Owned by CallSession.

    Public API:
      - ``set_system_prompt(prompt)``        - call once at start
      - ``enqueue_opener(text)``             - speak first thing
      - ``run(transcript_queue, ...)``       - long-running coroutine
      - ``terminal_result``                  - set after a terminal tool fires
    """

    def __init__(
        self,
        *,
        settings: ConversationSettings,
        llm_url: str,
        speech_queue: asyncio.Queue[SpeechRequest | None],
        tool_ctx: ToolContext,
        cancel_event: asyncio.Event,
        call_ended: asyncio.Event,
    ) -> None:
        self.settings = settings
        self.llm_url = llm_url.rstrip("/")
        self.speech_queue = speech_queue
        self.tool_ctx = tool_ctx
        self.cancel_event = cancel_event
        self.call_ended = call_ended

        self.state = _ConversationState()
        self.terminal_result: ToolResult | None = None
        self._client: httpx.AsyncClient | None = None
        self._stop = asyncio.Event()

    async def __aenter__(self) -> "ConversationLoop":
        self._client = httpx.AsyncClient(
            base_url=self.llm_url,
            timeout=httpx.Timeout(self.settings.request_timeout_sec, connect=5.0),
            http2=True,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Public mutators
    # ------------------------------------------------------------------

    def set_system_prompt(self, prompt: str) -> None:
        if self.state.messages and self.state.messages[0].get("role") == "system":
            self.state.messages[0] = {"role": "system", "content": prompt}
        else:
            self.state.messages.insert(0, {"role": "system", "content": prompt})

    def enqueue_opener(self, text: str) -> None:
        if not text:
            return
        self.state.messages.append({"role": "assistant", "content": text})
        self._enqueue_speech(text)

    async def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self, transcript_queue: asyncio.Queue[STTFinal]) -> None:
        while not self._stop.is_set():
            try:
                final: STTFinal = await asyncio.wait_for(
                    transcript_queue.get(), timeout=0.5
                )
            except asyncio.TimeoutError:
                continue

            if not final.text:
                continue

            log.info("user_said", text=final.text, duration_ms=final.duration_ms)
            self.tool_ctx.transcript_writer and \
                self.tool_ctx.transcript_writer.write("user_speech", {
                    "text": final.text, "duration_ms": final.duration_ms,
                })
            self.state.messages.append({"role": "user", "content": final.text})

            # Human-like response delay.
            delay = response_delay_ms(
                self.settings.response_delay_ms_min,
                self.settings.response_delay_ms_max,
            )
            await asyncio.sleep(delay / 1000.0)

            try:
                content, tool_calls = await self._call_llm()
            except _LLMFailure as exc:
                log.warning("llm_failure", error=str(exc))
                M_LLM_ERRORS.labels(kind=exc.kind).inc()
                self._enqueue_speech(_FALLBACK_APOLOGY, is_terminal=True)
                self.terminal_result = ToolResult(
                    name="end_call", success=False, is_terminal=True,
                    speak=_FALLBACK_APOLOGY, dispo_code="ERROR_AI",
                )
                self.call_ended.set()
                return

            await self._handle_llm_response(content, tool_calls)

            if self.terminal_result is not None:
                # Speech for terminal tools is already enqueued; wait for
                # it to finish playing then signal end-of-call.
                await self._await_speech_drain()
                self.call_ended.set()
                return

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    async def _call_llm(self) -> tuple[str, list[dict]]:
        body: dict[str, Any] = {
            "model": self.settings.model,
            "messages": self.state.messages,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "stream": False,
        }
        if self.settings.enable_tools:
            body["tools"] = TOOL_SCHEMAS
            body["tool_choice"] = "auto"

        started = time.monotonic()
        try:
            r = await self._client.post("/v1/chat/completions", json=body)
        except httpx.TimeoutException as exc:
            raise _LLMFailure("timeout", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise _LLMFailure("http_error", str(exc)) from exc
        finally:
            M_LLM_LATENCY.labels(stage="complete").observe(
                time.monotonic() - started
            )

        if r.status_code != 200:
            raise _LLMFailure("status_" + str(r.status_code),
                              r.text[:200])

        try:
            data = r.json()
            choice = data["choices"][0]
            msg = choice["message"]
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            raise _LLMFailure("bad_shape", str(exc)) from exc

        content = (msg.get("content") or "").strip()
        tool_calls = msg.get("tool_calls") or []
        return content, tool_calls

    # ------------------------------------------------------------------
    # LLM response handling
    # ------------------------------------------------------------------

    async def _handle_llm_response(
        self,
        content: str,
        tool_calls: list[dict],
    ) -> None:
        # Optional pre-tool speech ("sure, transferring you now…").
        if content:
            spoken = self._maybe_inject_filler(content)
            self.state.messages.append({"role": "assistant", "content": content})
            self._enqueue_speech(spoken)

        if not tool_calls:
            return

        # Append the assistant's tool_calls turn so the LLM has a coherent
        # history when we feed back tool results.
        self.state.messages.append({
            "role": "assistant",
            "content": content or None,
            "tool_calls": tool_calls,
        })

        for tc in tool_calls:
            fn = tc.get("function", {}) or {}
            name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            tool_call_id = tc.get("id", str(uuid4()))

            result = await dispatch(name, raw_args, self.tool_ctx)
            self.state.messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result.feedback_to_llm or json.dumps(result.extra),
            })

            if result.is_terminal:
                self.terminal_result = result
                if result.speak:
                    self._enqueue_speech(result.speak, is_terminal=True)
                # Don't dispatch any further tool calls past a terminal one.
                return

            # Informational tool — feed result back to LLM for the next turn.
            if name == "search_kb":
                # Re-call the LLM with the tool result in context. One round
                # of tool-then-respond is the v0.5 contract; chained tools
                # land in a future iteration.
                try:
                    follow_content, follow_tools = await self._call_llm()
                except _LLMFailure as exc:                  # pragma: no cover
                    log.warning("llm_followup_failed",
                                error=str(exc), tool=name)
                    return
                if follow_content:
                    spoken = self._maybe_inject_filler(follow_content)
                    self.state.messages.append({
                        "role": "assistant", "content": follow_content,
                    })
                    self._enqueue_speech(spoken)
                # Ignore further tool calls in the follow-up to bound depth.

    # ------------------------------------------------------------------
    # Speech queueing
    # ------------------------------------------------------------------

    def _enqueue_speech(self, text: str, *, is_terminal: bool = False) -> None:
        if not text:
            return
        self.tool_ctx.transcript_writer and \
            self.tool_ctx.transcript_writer.write("agent_speech", {
                "text": text, "terminal": is_terminal,
            })
        try:
            self.speech_queue.put_nowait(SpeechRequest(
                text=text,
                voice_id=self.settings.voice_id,
                is_terminal=is_terminal,
                request_id=str(uuid4()),
            ))
        except asyncio.QueueFull:                            # pragma: no cover
            log.warning("speech_queue_full", chars=len(text))

    def _maybe_inject_filler(self, text: str) -> str:
        new_text, did = inject_filler(
            text,
            frequency=self.settings.filler_frequency,
            turns_since_last=self.state.turns_since_filler,
        )
        if did:
            self.state.turns_since_filler = 0
        else:
            self.state.turns_since_filler += 1
        return new_text

    async def _await_speech_drain(self) -> None:
        """Spin briefly so the audio_out pipeline can finish playing."""
        # An empty queue is a heuristic — TTS may still be generating bytes.
        # The audio_out lifecycle owns the precise drain; we just wait until
        # the queue is empty before declaring end-of-call.
        for _ in range(60):  # up to ~6 s
            if self.speech_queue.empty():
                return
            await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class _LLMFailure(Exception):
    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind


_FALLBACK_APOLOGY = (
    "Sorry, I'm having trouble on my end. Let me transfer you to a human — "
    "please hold."
)
