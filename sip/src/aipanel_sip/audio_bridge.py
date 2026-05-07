"""Audio bridge: PJSIP RTP <-> framed unix socket to a worker process.

Wire protocol on the unix socket
--------------------------------

Each frame is::

    [4 bytes BE length][1 byte type][payload of (length - 1) bytes]

So ``length`` covers ``type + payload`` and the total bytes on the wire is
``4 + length``. A 320-byte audio frame therefore writes 325 bytes.

Frame types:

==========  ====  ==========================================================
Constant     hex  Meaning
==========  ====  ==========================================================
AUDIO_IN    0x01  PCM frame from caller → worker (320B, 8 kHz mono s16le)
AUDIO_OUT   0x02  PCM frame from worker → caller (same format)
CONTROL     0x10  JSON event (UTF-8). Bidirectional.
HANGUP      0x11  Either side requests teardown. No payload.
DTMF        0x12  Single ASCII digit from caller (0-9, *, #, A-D).
==========  ====  ==========================================================

Backpressure
------------

Inbound (PJSIP → worker) and outbound (worker → caller) both go through a
bounded ``deque``. Overflow drops the oldest frame and increments
``aipanel_sip_audio_frames_dropped_total`` rather than blocking the
PJSIP/RTP thread, which would tear down the call.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
from collections import deque
from typing import TYPE_CHECKING, Any, Callable
from uuid import UUID

import structlog

# pjsua2 is built into the SIP venv by installer/lib/pjsip.sh. Tests run
# without it; we degrade gracefully so the framing protocol stays unit-testable.
try:
    import pjsua2 as pj
except ImportError:                                          # pragma: no cover
    pj = None  # type: ignore[assignment]

if TYPE_CHECKING:                                            # pragma: no cover
    from .worker_dispatcher import WorkerDispatcher

log = structlog.get_logger().bind(component="audio_bridge")

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------
FRAME_AUDIO_IN  = 0x01
FRAME_AUDIO_OUT = 0x02
FRAME_CONTROL   = 0x10
FRAME_HANGUP    = 0x11
FRAME_DTMF      = 0x12

PCM_FRAME_BYTES = 320            # 20 ms of 8 kHz, 16-bit, mono
SILENCE_FRAME = b"\x00" * PCM_FRAME_BYTES

QUEUE_MAX_FRAMES = 50            # ~1 s of audio per direction


# ---------------------------------------------------------------------------
# Pure framing helpers (importable without pjsua2 — used by tests)
# ---------------------------------------------------------------------------

def encode_frame(frame_type: int, payload: bytes = b"") -> bytes:
    """Encode a single frame. ``length`` covers type + payload."""
    if not 0 <= frame_type <= 0xFF:
        raise ValueError(f"frame_type out of range: {frame_type}")
    length = 1 + len(payload)
    return struct.pack(">IB", length, frame_type) + payload


def recv_exact(sock: socket.socket, n: int) -> bytes | None:
    """Read exactly ``n`` bytes from a SOCK_STREAM socket. None on EOF/close."""
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except (OSError, ConnectionError):
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def read_frame(sock: socket.socket) -> tuple[int, bytes] | None:
    """Read one framed message from the socket. Returns (type, payload) or None."""
    header = recv_exact(sock, 5)
    if header is None:
        return None
    length, ftype = struct.unpack(">IB", header)
    payload = b""
    if length > 1:
        body = recv_exact(sock, length - 1)
        if body is None:
            return None
        payload = body
    return ftype, payload


# ---------------------------------------------------------------------------
# PJSIP AudioMediaPort subclass
# ---------------------------------------------------------------------------

if pj is not None:

    class _CallAudioPort(pj.AudioMediaPort):                 # type: ignore[misc]
        """Subclass overriding the SWIG director hooks for frame I/O.

        Both methods are invoked from PJSIP's media thread at ~50 Hz per call.
        They MUST return promptly: any blocking work here stalls RTP and drops
        audio. We only do bounded-queue ops.
        """

        def __init__(self, bridge: "AudioBridge") -> None:
            super().__init__()
            self._bridge = bridge

        def onFrameRequested(self, frame: Any) -> None:      # noqa: N802 (PJSIP API)
            try:
                data = self._bridge.dequeue_outbound()
                frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO
                frame.buf = data
                frame.size = len(data)
            except Exception:                                # pragma: no cover
                log.exception("on_frame_requested_failed",
                              call_id=str(self._bridge.call_id))

        def onFrameReceived(self, frame: Any) -> None:       # noqa: N802 (PJSIP API)
            try:
                if frame.type != pj.PJMEDIA_FRAME_TYPE_AUDIO:
                    return
                data = bytes(frame.buf)[: frame.size]
                self._bridge.enqueue_inbound(data)
            except Exception:                                # pragma: no cover
                log.exception("on_frame_received_failed",
                              call_id=str(self._bridge.call_id))


# ---------------------------------------------------------------------------
# AudioBridge — one per active call
# ---------------------------------------------------------------------------

class AudioBridge:
    """Glue between a single PJSIP call and a worker over a unix socket.

    Lifecycle::

        bridge = AudioBridge(call_id, socket_path, on_dropped, on_hangup)
        bridge.setup_socket()          # create & listen on the unix socket
        # ...publish worker request via WorkerDispatcher...
        bridge.accept_worker(timeout)  # blocks until worker connects (or raises)
        bridge.attach_media(audio_media)  # wires PJSIP RTP into the bridge
        # ...call runs...
        bridge.close()                 # idempotent
    """

    def __init__(
        self,
        call_id: UUID,
        socket_path: str,
        *,
        on_dropped_frame: Callable[[], None] | None = None,
        on_worker_hangup: Callable[[], None] | None = None,
        on_dtmf_from_worker: Callable[[str], None] | None = None,
    ) -> None:
        self.call_id = call_id
        self.socket_path = socket_path
        self._on_dropped = on_dropped_frame or (lambda: None)
        self._on_worker_hangup = on_worker_hangup or (lambda: None)
        self._on_dtmf_from_worker = on_dtmf_from_worker or (lambda d: None)

        self._inbound: deque[bytes] = deque(maxlen=QUEUE_MAX_FRAMES)
        self._outbound: deque[bytes] = deque(maxlen=QUEUE_MAX_FRAMES)
        # Lock guards _inbound / _outbound: deque is thread-safe for append /
        # popleft, but maxlen overflow detection requires checking len() first.
        self._lock = threading.Lock()

        self._listener: socket.socket | None = None
        self._client: socket.socket | None = None
        self._port: Any = None                # _CallAudioPort instance
        self._reader: threading.Thread | None = None
        self._writer: threading.Thread | None = None
        self._shutdown = threading.Event()
        self._closed = False

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup_socket(self) -> None:
        """Create the unix socket and start listening for the worker."""
        sock_dir = os.path.dirname(self.socket_path)
        os.makedirs(sock_dir, exist_ok=True)
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(self.socket_path)
        os.chmod(self.socket_path, 0o660)
        s.listen(1)
        self._listener = s

    def accept_worker(self, timeout_sec: float) -> None:
        """Block up to ``timeout_sec`` waiting for the worker to connect.

        Raises ``TimeoutError`` if no worker arrives, ``OSError`` on socket
        failure. On success, spins up the reader/writer threads.
        """
        if self._listener is None:
            raise RuntimeError("setup_socket() not called")
        self._listener.settimeout(timeout_sec)
        try:
            client, _ = self._listener.accept()
        except socket.timeout as exc:
            raise TimeoutError(
                f"worker did not connect to {self.socket_path} within "
                f"{timeout_sec:.1f}s"
            ) from exc
        client.settimeout(None)         # blocking I/O on the worker thread
        self._client = client

        self._reader = threading.Thread(
            target=self._read_loop,
            name=f"sip-call-{self.call_id}-rd",
            daemon=True,
        )
        self._writer = threading.Thread(
            target=self._write_loop,
            name=f"sip-call-{self.call_id}-wr",
            daemon=True,
        )
        self._reader.start()
        self._writer.start()

    def send_control(self, payload: dict[str, Any]) -> None:
        """Send a JSON control event to the worker (e.g. CallContext at start)."""
        self._send(FRAME_CONTROL, json.dumps(payload).encode("utf-8"))

    def send_dtmf(self, digit: str) -> None:
        if not digit:
            return
        self._send(FRAME_DTMF, digit[:1].encode("ascii", errors="replace"))

    def send_hangup(self) -> None:
        self._send(FRAME_HANGUP, b"")

    # ------------------------------------------------------------------
    # PJSIP wiring
    # ------------------------------------------------------------------

    def attach_media(self, audio_media: Any) -> None:
        """Bidirectionally connect this bridge to PJSIP's audio media."""
        if pj is None:                                       # pragma: no cover
            raise RuntimeError("pjsua2 not importable; cannot attach media")

        fmt = pj.MediaFormatAudio()
        fmt.type           = pj.PJMEDIA_TYPE_AUDIO
        fmt.clockRate      = 8000
        fmt.channelCount   = 1
        fmt.bitsPerSample  = 16
        fmt.frameTimeUsec  = 20_000

        port = _CallAudioPort(self)
        port.createPort(f"call-{self.call_id}", fmt)
        # Caller audio (RTP in) → our port.
        audio_media.startTransmit(port)
        # Our port → caller audio (RTP out).
        port.startTransmit(audio_media)
        self._port = port
        log.info("media_attached", call_id=str(self.call_id))

    # ------------------------------------------------------------------
    # PJSIP-thread fast path (called at 50 Hz)
    # ------------------------------------------------------------------

    def enqueue_inbound(self, frame: bytes) -> None:
        """Enqueue a PCM frame from RTP. Drops on overflow."""
        with self._lock:
            if len(self._inbound) >= QUEUE_MAX_FRAMES:
                self._inbound.popleft()
                self._on_dropped()
            self._inbound.append(frame)

    def dequeue_outbound(self) -> bytes:
        """Pop a PCM frame to play to the caller. Returns silence on underflow."""
        with self._lock:
            try:
                return self._outbound.popleft()
            except IndexError:
                return SILENCE_FRAME

    # ------------------------------------------------------------------
    # Worker socket I/O threads
    # ------------------------------------------------------------------

    def _read_loop(self) -> None:
        assert self._client is not None
        while not self._shutdown.is_set():
            frame = read_frame(self._client)
            if frame is None:
                # Worker disconnected without a HANGUP frame — treat as hangup.
                log.warning("worker_socket_eof", call_id=str(self.call_id))
                self._on_worker_hangup()
                return
            ftype, payload = frame
            if ftype == FRAME_AUDIO_OUT:
                if len(payload) == 0:
                    continue
                with self._lock:
                    if len(self._outbound) >= QUEUE_MAX_FRAMES:
                        self._outbound.popleft()
                        self._on_dropped()
                    self._outbound.append(payload)
            elif ftype == FRAME_HANGUP:
                log.info("worker_hangup", call_id=str(self.call_id))
                self._on_worker_hangup()
                return
            elif ftype == FRAME_DTMF:
                if payload:
                    self._on_dtmf_from_worker(payload.decode("ascii", "replace"))
            elif ftype == FRAME_CONTROL:
                # Control events from worker land in the log for now; the
                # full event bus lands in a later prompt.
                try:
                    evt = json.loads(payload.decode("utf-8"))
                    log.info("worker_control_event",
                             call_id=str(self.call_id), event=evt)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    log.warning("worker_control_decode_failed",
                                call_id=str(self.call_id))
            else:
                log.warning("worker_unknown_frame_type",
                            call_id=str(self.call_id), frame_type=ftype)

    def _write_loop(self) -> None:
        # Lightly-spinning drain. Sleep is short enough that ~50 fps audio
        # latency stays well under the 20 ms frame interval, but long enough
        # that we don't burn a core when the queue is empty.
        while not self._shutdown.is_set():
            with self._lock:
                try:
                    frame = self._inbound.popleft()
                except IndexError:
                    frame = None
            if frame is None:
                if self._shutdown.wait(timeout=0.005):
                    return
                continue
            if not self._send(FRAME_AUDIO_IN, frame):
                return

    def _send(self, ftype: int, payload: bytes) -> bool:
        if self._client is None:
            return False
        try:
            self._client.sendall(encode_frame(ftype, payload))
            return True
        except OSError as exc:
            log.warning("worker_send_failed",
                        call_id=str(self.call_id), error=str(exc))
            self._shutdown.set()
            return False

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Stop threads, close socket, unlink path. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._shutdown.set()

        # Tear down PJSIP port first so callbacks stop firing.
        if self._port is not None:
            try:
                self._port.delete()         # pjsua2 standard cleanup
            except Exception:                                # pragma: no cover
                log.exception("port_delete_failed", call_id=str(self.call_id))
            self._port = None

        for sock in (self._client, self._listener):
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass
        self._client = None
        self._listener = None

        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:                                  # pragma: no cover
                log.warning("socket_unlink_failed",
                            call_id=str(self.call_id), path=self.socket_path)
