"""PJSIP endpoint bootstrap: transports, codecs, null sound device.

We deliberately do NOT touch ALSA — the SIP service runs headless on a
server with no audio hardware. ``audDevManager().setNullDev()`` after
``libStart()`` makes pjmedia treat the sound device as a black hole, which
keeps PJSIP happy without opening /dev/snd.
"""

from __future__ import annotations

import structlog

try:
    import pjsua2 as pj
except ImportError:                                          # pragma: no cover
    pj = None  # type: ignore[assignment]

from .config import SipConfig

log = structlog.get_logger().bind(component="endpoint")

USER_AGENT = "aipanel-sip/0.3"


class SipEndpoint:
    """Owner of the single ``pj.Endpoint`` instance for the process."""

    def __init__(self, cfg: SipConfig) -> None:
        if pj is None:
            raise RuntimeError(
                "pjsua2 is not importable. Did installer/lib/pjsip.sh build "
                "the bindings into the SIP venv?"
            )
        self.cfg = cfg
        self.ep = pj.Endpoint()
        self._started = False

    def start(self) -> None:
        """Create + initialise + start the PJSIP library."""
        ep_cfg = pj.EpConfig()

        # User agent + log redirection.
        ep_cfg.uaConfig.userAgent = USER_AGENT
        ep_cfg.uaConfig.maxCalls = 256

        # Media settings — server-side, no echo cancel, no VAD.
        ep_cfg.medConfig.clockRate    = 8000
        ep_cfg.medConfig.sndClockRate = 0      # null sound device set below
        ep_cfg.medConfig.channelCount = 1
        ep_cfg.medConfig.audioFramePtime = 20
        ep_cfg.medConfig.noVad = True
        ep_cfg.medConfig.ecOptions = 0
        ep_cfg.medConfig.ecTailLen = 0

        # PJSIP's own logging — keep at level 3 (info) and let it land in
        # stderr so journald/systemd captures it alongside our structlog.
        ep_cfg.logConfig.level        = 3
        ep_cfg.logConfig.consoleLevel = 3

        self.ep.libCreate()
        self.ep.libInit(ep_cfg)

        # UDP transport (ViciDial's Asterisk speaks UDP by default).
        tcfg = pj.TransportConfig()
        tcfg.port          = self.cfg.sip_listen_port
        tcfg.boundAddress  = self.cfg.sip_listen_host
        if self.cfg.sip_public_ip:
            tcfg.publicAddress = self.cfg.sip_public_ip
        self.ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tcfg)

        self.ep.libStart()
        self._started = True

        # Headless: tell pjmedia not to grab a real soundcard.
        try:
            self.ep.audDevManager().setNullDev()
        except pj.Error as exc:                              # pragma: no cover
            log.warning("null_sound_device_failed", error=str(exc))

        self._configure_codecs()
        log.info("endpoint_started",
                 listen=f"{self.cfg.sip_listen_host}:{self.cfg.sip_listen_port}",
                 public_ip=self.cfg.sip_public_ip)

    def _configure_codecs(self) -> None:
        """Allow only PCMU and PCMA at 8 kHz; everything else priority 0."""
        wanted_priority = {
            "PCMU/8000": 250,
            "PCMA/8000": 240,
        }
        for codec_info in self.ep.codecEnum2():
            cid = codec_info.codecId
            self.ep.codecSetPriority(cid, wanted_priority.get(cid, 0))
        active = [c.codecId for c in self.ep.codecEnum2() if c.priority > 0]
        log.info("codecs_configured", active=active)

    def register_thread(self, name: str) -> None:
        """Mark a Python thread as PJSIP-aware (required before any pj API call)."""
        if not self._started:
            return
        try:
            if not self.ep.libIsThreadRegistered():
                self.ep.libRegisterThread(name)
        except pj.Error as exc:                              # pragma: no cover
            log.warning("thread_register_failed", thread=name, error=str(exc))

    def shutdown(self) -> None:
        """Tear down PJSIP. Idempotent."""
        if not self._started:
            return
        self._started = False
        try:
            self.ep.libDestroy()
        except pj.Error as exc:                              # pragma: no cover
            log.warning("lib_destroy_failed", error=str(exc))
