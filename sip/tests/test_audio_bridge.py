"""Tests for the framing protocol + AudioBridge socket I/O.

These tests deliberately avoid pjsua2: only the framing helpers and the
worker-side reader/writer threads are exercised. The PJSIP wiring
(``attach_media``, ``onFrameRequested``) is covered manually on a host
with PJSIP installed.
"""

from __future__ import annotations

import os
import socket
import struct
import tempfile
import threading
import time
from uuid import uuid4

import pytest

from aipanel_sip.audio_bridge import (
    FRAME_AUDIO_IN,
    FRAME_AUDIO_OUT,
    FRAME_CONTROL,
    FRAME_DTMF,
    FRAME_HANGUP,
    PCM_FRAME_BYTES,
    AudioBridge,
    encode_frame,
    read_frame,
    recv_exact,
)


# ---------------------------------------------------------------------------
# Pure framing
# ---------------------------------------------------------------------------

def test_encode_frame_layout_for_audio():
    payload = b"\x01" * PCM_FRAME_BYTES
    encoded = encode_frame(FRAME_AUDIO_IN, payload)
    # 4 length + 1 type + 320 payload = 325
    assert len(encoded) == 325
    length, ftype = struct.unpack(">IB", encoded[:5])
    assert length == 1 + PCM_FRAME_BYTES   # length covers type + payload
    assert ftype == FRAME_AUDIO_IN
    assert encoded[5:] == payload


def test_encode_frame_empty_payload():
    encoded = encode_frame(FRAME_HANGUP)
    # 4 length + 1 type + 0 payload = 5
    assert encoded == b"\x00\x00\x00\x01" + bytes([FRAME_HANGUP])


def test_encode_frame_rejects_invalid_type():
    with pytest.raises(ValueError):
        encode_frame(0x100, b"")


# ---------------------------------------------------------------------------
# Round trip over a real socketpair
# ---------------------------------------------------------------------------

def test_read_frame_roundtrip_via_socketpair():
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        a.sendall(encode_frame(FRAME_AUDIO_OUT, b"hello"))
        a.sendall(encode_frame(FRAME_HANGUP))
        ftype, payload = read_frame(b)  # type: ignore[misc]
        assert ftype == FRAME_AUDIO_OUT
        assert payload == b"hello"
        ftype2, payload2 = read_frame(b)  # type: ignore[misc]
        assert ftype2 == FRAME_HANGUP
        assert payload2 == b""
    finally:
        a.close()
        b.close()


def test_recv_exact_returns_none_on_close():
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    a.close()
    assert recv_exact(b, 5) is None
    b.close()


# ---------------------------------------------------------------------------
# AudioBridge end-to-end (worker side simulated)
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_socket_dir(tmp_path):
    d = tmp_path / "calls"
    d.mkdir()
    return str(d)


def _connect_worker(socket_path: str, timeout: float = 2.0) -> socket.socket:
    """Polls until the listener exists, then connects."""
    deadline = time.monotonic() + timeout
    while not os.path.exists(socket_path):
        if time.monotonic() > deadline:
            raise TimeoutError(f"socket never appeared: {socket_path}")
        time.sleep(0.01)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(socket_path)
    return s


def test_bridge_inbound_frames_reach_worker(tmp_socket_dir):
    """PJSIP-side enqueue_inbound() → worker reads AUDIO_IN frames."""
    cid = uuid4()
    sock_path = f"{tmp_socket_dir}/{cid}.sock"
    bridge = AudioBridge(call_id=cid, socket_path=sock_path)
    bridge.setup_socket()

    worker_sock_holder: list[socket.socket] = []

    def _worker():
        worker_sock_holder.append(_connect_worker(sock_path))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    bridge.accept_worker(timeout_sec=2.0)
    t.join(timeout=2.0)
    assert worker_sock_holder, "worker never connected"
    worker_sock = worker_sock_holder[0]
    worker_sock.settimeout(2.0)

    # Push two inbound PCM frames as if from the RTP thread.
    frame_a = b"\x11" * PCM_FRAME_BYTES
    frame_b = b"\x22" * PCM_FRAME_BYTES
    bridge.enqueue_inbound(frame_a)
    bridge.enqueue_inbound(frame_b)

    got = []
    for _ in range(2):
        msg = read_frame(worker_sock)
        assert msg is not None
        got.append(msg)
    assert got[0] == (FRAME_AUDIO_IN, frame_a)
    assert got[1] == (FRAME_AUDIO_IN, frame_b)

    bridge.close()
    worker_sock.close()


def test_bridge_outbound_audio_from_worker_dequeues_in_order(tmp_socket_dir):
    """Worker writes AUDIO_OUT → bridge.dequeue_outbound() returns same bytes."""
    cid = uuid4()
    sock_path = f"{tmp_socket_dir}/{cid}.sock"
    bridge = AudioBridge(call_id=cid, socket_path=sock_path)
    bridge.setup_socket()

    worker_holder: list[socket.socket] = []

    def _worker():
        worker_holder.append(_connect_worker(sock_path))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    bridge.accept_worker(timeout_sec=2.0)
    t.join(timeout=2.0)
    worker_sock = worker_holder[0]

    frame = b"\xAB" * PCM_FRAME_BYTES
    worker_sock.sendall(encode_frame(FRAME_AUDIO_OUT, frame))

    # Spin briefly so the reader thread can drain the socket.
    deadline = time.monotonic() + 1.0
    out = bridge.dequeue_outbound()
    while out == b"\x00" * PCM_FRAME_BYTES and time.monotonic() < deadline:
        time.sleep(0.01)
        out = bridge.dequeue_outbound()
    assert out == frame

    bridge.close()
    worker_sock.close()


def test_bridge_dequeue_outbound_returns_silence_on_underflow(tmp_socket_dir):
    cid = uuid4()
    sock_path = f"{tmp_socket_dir}/{cid}.sock"
    bridge = AudioBridge(call_id=cid, socket_path=sock_path)
    bridge.setup_socket()
    try:
        # No worker, no frames — should still return silence, not raise.
        assert bridge.dequeue_outbound() == b"\x00" * PCM_FRAME_BYTES
    finally:
        bridge.close()


def test_bridge_worker_hangup_invokes_callback(tmp_socket_dir):
    cid = uuid4()
    sock_path = f"{tmp_socket_dir}/{cid}.sock"
    triggered = threading.Event()
    bridge = AudioBridge(
        call_id=cid,
        socket_path=sock_path,
        on_worker_hangup=triggered.set,
    )
    bridge.setup_socket()
    holder: list[socket.socket] = []

    def _worker():
        holder.append(_connect_worker(sock_path))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    bridge.accept_worker(timeout_sec=2.0)
    t.join(timeout=2.0)
    worker_sock = holder[0]

    worker_sock.sendall(encode_frame(FRAME_HANGUP))
    assert triggered.wait(timeout=2.0)
    bridge.close()
    worker_sock.close()


def test_bridge_inbound_overflow_drops_oldest_and_counts(tmp_socket_dir):
    cid = uuid4()
    sock_path = f"{tmp_socket_dir}/{cid}.sock"

    drops = {"n": 0}

    def _on_drop():
        drops["n"] += 1

    bridge = AudioBridge(
        call_id=cid,
        socket_path=sock_path,
        on_dropped_frame=_on_drop,
    )
    bridge.setup_socket()
    # No worker — write_loop will never start, so the inbound queue grows
    # until we hit QUEUE_MAX_FRAMES.
    from aipanel_sip.audio_bridge import QUEUE_MAX_FRAMES
    payload = b"\x01" * PCM_FRAME_BYTES
    for _ in range(QUEUE_MAX_FRAMES):
        bridge.enqueue_inbound(payload)
    assert drops["n"] == 0
    bridge.enqueue_inbound(payload)   # one over the limit
    assert drops["n"] == 1
    bridge.close()


def test_bridge_send_dtmf_and_control(tmp_socket_dir):
    cid = uuid4()
    sock_path = f"{tmp_socket_dir}/{cid}.sock"
    bridge = AudioBridge(call_id=cid, socket_path=sock_path)
    bridge.setup_socket()
    holder: list[socket.socket] = []

    def _worker():
        holder.append(_connect_worker(sock_path))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    bridge.accept_worker(timeout_sec=2.0)
    t.join(timeout=2.0)
    worker_sock = holder[0]
    worker_sock.settimeout(2.0)

    bridge.send_dtmf("5")
    bridge.send_control({"type": "hello"})

    msg1 = read_frame(worker_sock)
    msg2 = read_frame(worker_sock)
    assert msg1 == (FRAME_DTMF, b"5")
    assert msg2 is not None and msg2[0] == FRAME_CONTROL
    assert b'"type"' in msg2[1] and b'"hello"' in msg2[1]

    bridge.close()
    worker_sock.close()


def test_bridge_close_unlinks_socket(tmp_socket_dir):
    cid = uuid4()
    sock_path = f"{tmp_socket_dir}/{cid}.sock"
    bridge = AudioBridge(call_id=cid, socket_path=sock_path)
    bridge.setup_socket()
    assert os.path.exists(sock_path)
    bridge.close()
    assert not os.path.exists(sock_path)
    # Idempotent.
    bridge.close()
