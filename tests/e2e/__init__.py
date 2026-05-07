"""End-to-end test harness for the call pipeline.

These tests stand up minimal in-process fakes for ViciDial + the SIP
unix socket and exercise the worker against a scripted call. They DO NOT
test real telephony — that requires a real Asterisk / RTP setup and a
phone number, out of scope for unit-style runs.

What they cover:
- Worker connects to a fake SIP socket
- Worker reads the initial CONTROL frame
- Worker sends the call_context to the (mocked) LLM and TTS
- Worker writes back AUDIO_OUT frames + a HANGUP at the end
- Session-mgr action endpoints are called with the right parameters
"""
