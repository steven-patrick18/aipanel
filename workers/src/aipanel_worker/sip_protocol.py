"""Frame protocol for the SIP-service unix socket.

Mirrors aipanel_sip.audio_bridge — repeated here because the worker lives in
its own venv. If/when there's a shared package, both copies collapse to one.

Wire format::

    [4 bytes BE length][1 byte type][payload of (length - 1) bytes]

`length` covers ``type + payload``; total bytes on wire = ``4 + length``.
"""

from __future__ import annotations

import asyncio
import struct

# Frame types (must match aipanel_sip.audio_bridge).
FRAME_AUDIO_IN  = 0x01    # caller → worker (PCM 8 kHz s16le, 320 B / 20 ms)
FRAME_AUDIO_OUT = 0x02    # worker → caller (same format)
FRAME_CONTROL   = 0x10    # JSON event, bidirectional
FRAME_HANGUP    = 0x11    # either side requests teardown
FRAME_DTMF      = 0x12    # single ASCII digit from caller

PCM_FRAME_BYTES = 320     # 20 ms of 8 kHz, mono, s16le
SAMPLE_RATE_SIP = 8000
SAMPLE_RATE_STT = 16000   # what we resample TO before forwarding to STT


def encode_frame(frame_type: int, payload: bytes = b"") -> bytes:
    """Pack one frame for the wire."""
    if not 0 <= frame_type <= 0xFF:
        raise ValueError(f"frame_type out of range: {frame_type}")
    length = 1 + len(payload)
    return struct.pack(">IB", length, frame_type) + payload


async def read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes] | None:
    """Read one frame from an asyncio StreamReader. Returns (type, payload) or None on EOF."""
    try:
        header = await reader.readexactly(5)
    except asyncio.IncompleteReadError:
        return None
    length, ftype = struct.unpack(">IB", header)
    payload = b""
    if length > 1:
        try:
            payload = await reader.readexactly(length - 1)
        except asyncio.IncompleteReadError:
            return None
    return ftype, payload
