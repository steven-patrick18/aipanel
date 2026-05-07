"""Prometheus metrics for the Session Manager."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

M_SESSIONS = Gauge(
    "aipanel_vici_sessions_active",
    "Currently logged-in ViciDial sessions",
    ["status"],
)

M_LOGIN = Counter(
    "aipanel_vici_login_attempts_total",
    "Playwright-driven login attempts",
    ["result"],   # ok | fail
)

M_HEARTBEAT = Counter(
    "aipanel_vici_heartbeats_total",
    "Heartbeat round trips",
    ["result"],   # ok | fail
)

M_ACTION_LATENCY = Histogram(
    "aipanel_vici_action_latency_seconds",
    "Latency of internal action endpoints",
    ["action"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

M_API_REQUESTS = Counter(
    "aipanel_vici_api_requests_total",
    "Internal API requests handled",
    ["route", "status"],
)
