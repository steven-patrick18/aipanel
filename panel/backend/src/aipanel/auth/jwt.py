"""JWT issuance + verification.

HS256 signed with ``JWT_SECRET`` from secrets.env. Two token types:

* ``access`` — short (default 15 min), proves you're logged in
* ``refresh`` — long (default 7 d), exchanged for a new access token

Payload shape::

    {
      "sub": "<user_id>",
      "tenant_id": "<tenant_id>",
      "role": "admin" | "operator" | "viewer",
      "type": "access" | "refresh",
      "iat": int,
      "exp": int
    }
"""

from __future__ import annotations

import secrets as _secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

import jwt as pyjwt

from ..config import get_config

_ALG = "HS256"


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class TokenPayload:
    user_id: UUID
    tenant_id: UUID
    role: str
    token_type: Literal["access", "refresh"]
    issued_at: datetime
    expires_at: datetime
    jti: str = ""        # token id — used by the logout denylist


def _new_jti() -> str:
    """16-byte URL-safe random id; sufficient for denylist uniqueness."""
    return _secrets.token_urlsafe(16)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode(payload: dict) -> str:
    secret = get_config().panel.jwt_secret
    return pyjwt.encode(payload, secret, algorithm=_ALG)


def _decode(token: str) -> dict:
    secret = get_config().panel.jwt_secret
    try:
        return pyjwt.decode(token, secret, algorithms=[_ALG])
    except pyjwt.ExpiredSignatureError as exc:
        raise InvalidToken("expired") from exc
    except pyjwt.InvalidTokenError as exc:
        raise InvalidToken(str(exc)) from exc


def issue_access(
    *,
    user_id: UUID, tenant_id: UUID, role: str,
    lifetime_minutes: int | None = None,
) -> tuple[str, datetime]:
    cfg = get_config().panel
    minutes = lifetime_minutes or cfg.access_token_minutes
    iat = _now()
    exp = iat + timedelta(minutes=minutes)
    token = _encode({
        "sub":       str(user_id),
        "tenant_id": str(tenant_id),
        "role":      role,
        "type":      "access",
        "iat":       int(iat.timestamp()),
        "exp":       int(exp.timestamp()),
        "jti":       _new_jti(),
    })
    return token, exp


def issue_refresh(
    *,
    user_id: UUID, tenant_id: UUID, role: str,
    lifetime_days: int | None = None,
) -> tuple[str, datetime]:
    cfg = get_config().panel
    days = lifetime_days or cfg.refresh_token_days
    iat = _now()
    exp = iat + timedelta(days=days)
    token = _encode({
        "sub":       str(user_id),
        "tenant_id": str(tenant_id),
        "role":      role,
        "type":      "refresh",
        "iat":       int(iat.timestamp()),
        "exp":       int(exp.timestamp()),
        "jti":       _new_jti(),
    })
    return token, exp


def verify(token: str, *, expected_type: Literal["access", "refresh"]) -> TokenPayload:
    data = _decode(token)
    if data.get("type") != expected_type:
        raise InvalidToken(f"expected {expected_type} token, got {data.get('type')!r}")
    try:
        return TokenPayload(
            user_id=UUID(data["sub"]),
            tenant_id=UUID(data["tenant_id"]),
            role=str(data["role"]),
            token_type=expected_type,
            issued_at=datetime.fromtimestamp(int(data["iat"]), tz=timezone.utc),
            expires_at=datetime.fromtimestamp(int(data["exp"]), tz=timezone.utc),
            jti=str(data.get("jti", "")),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidToken(f"malformed payload: {exc}") from exc


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(plaintext: str) -> str:
    return _pwd_context.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return _pwd_context.verify(plaintext, hashed)
    except Exception:
        return False
