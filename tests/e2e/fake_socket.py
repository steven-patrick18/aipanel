"""In-process fake of the SIP unix-socket that the worker connects to.

The real SIP service writes a per-call socket and sends:
  1. one CONTROL frame containing the CallContext JSON
  2. then AUDIO_IN frames at 50 Hz (320 B each)
  3. and reads AUDIO_OUT / HANGUP / etc. frames back

This fake speaks the same wire protocol and lets a test script:
  - inject a sequence of audio frames + DTMF + hangup
  - capture what the worker sends back (audio_out, hangup, control)
  - assert on the captured stream
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import struct
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Mirror of aipanel_sip.audio_bridge constants.
FRAME_AUDIO_IN  = 0x01
FRAME_AUDIO_OUT = 0x02
FRAME_CONTROL   = 0x10
FRAME_HANGUP    = 0x11
FRAME_DTMF      = 0x12
PCM_FRAME_BYTES = 320     # 20 ms of 8 kHz s16le mono


def encode_frame(frame_type: int, payload: bytes = b"") -> bytes:
    return struct.pack(">IB", 1 + len(payload), frame_type) + payload


@dataclass
class CapturedStream:
    audio_out: list[bytes] = field(default_factory=list)
    control:   list[dict] = field(default_factory=list)
    hangup_received: bool = False
    dtmf_sent_to_worker: list[str] = field(default_factory=list)


class FakeSipSocket:
    """Server side of the SIP socket. Manages one conversation."""

    def __init__(self, *, call_id: str, deployment_id: str) -> None:
        self.call_id = call_id
        self.deployment_id = deployment_id
        self.path = Path(tempfile.mkdtemp(prefix="aipanel-test-")) / f"{call_id}.sock"
        self.captured = CapturedStream()
        self._server_sock: socket.socket | None = None
        self._client_sock: socket.socket | None = None
        self._reader_task: asyncio.Task | None = None
        self._closed = False

    async def start(self) -> None:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(self.path))
        s.listen(1)
        s.setblocking(False)
        self._server_sock = s

    async def accept_client(self, timeout_sec: float = 5.0) -> None:
        loop = asyncio.get_running_loop()
        client, _ = await asyncio.wait_for(
            loop.sock_accept(self._server_sock), timeout=timeout_sec,
        )
        client.setblocking(False)
        self._client_sock = client
        # Send initial CONTROL frame with the call context.
        ctx = {
            "type": "call_context",
            "call_id": self.call_id,
            "deployment_id": self.deployment_id,
            "vici_lead_id": "L42",
            "vici_uniqueid": "1700000000.5",
            "vici_campaign": "FAKE",
            "vici_phone": "+18005551234",
            "p_asserted_identity": "<sip:18005551234@fake.example>",
        }
        await self._write_frame(FRAME_CONTROL, json.dumps(ctx).encode())
        self._reader_task = asyncio.create_task(self._read_loop())

    async def send_silence(self, ms: int) -> None:
        frames = max(1, ms // 20)
        for _ in range(frames):
            await self._write_frame(FRAME_AUDIO_IN, b"\x00" * PCM_FRAME_BYTES)
            await asyncio.sleep(0.02)

    async def send_dtmf(self, digit: str) -> None:
        await self._write_frame(FRAME_DTMF, digit[:1].encode("ascii"))

    async def send_hangup(self) -> None:
        await self._write_frame(FRAME_HANGUP, b"")

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._reader_task:
            self._reader_task.cancel()
        if self._client_sock:
            try: self._client_sock.close()
            except OSError: pass
        if self._server_sock:
            try: self._server_sock.close()
            except OSError: pass
        if self.path.exists():
            try: self.path.unlink()
            except OSError: pass
        try: self.path.parent.rmdir()
        except OSError: pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _write_frame(self, ftype: int, payload: bytes) -> None:
        if self._client_sock is None:
            raise RuntimeError("client not connected")
        loop = asyncio.get_running_loop()
        await loop.sock_sendall(self._client_sock, encode_frame(ftype, payload))

    async def _read_loop(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                header = await self._sock_recv_exact(loop, 5)
                if header is None:
                    return
                length, ftype = struct.unpack(">IB", header)
                body = b""
                if length > 1:
                    body = await self._sock_recv_exact(loop, length - 1) or b""
                if ftype == FRAME_AUDIO_OUT:
                    self.captured.audio_out.append(body)
                elif ftype == FRAME_HANGUP:
                    self.captured.hangup_received = True
                    return
                elif ftype == FRAME_CONTROL:
                    try:
                        self.captured.control.append(json.loads(body.decode("utf-8")))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        pass
                elif ftype == FRAME_DTMF:
                    self.captured.dtmf_sent_to_worker.append(
                        body.decode("ascii", "replace")
                    )
        except asyncio.CancelledError:
            return

    async def _sock_recv_exact(self, loop, n: int) -> bytes | None:
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = await loop.sock_recv(self._client_sock, n - len(buf))
            except (OSError, ConnectionError):
                return None
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)
