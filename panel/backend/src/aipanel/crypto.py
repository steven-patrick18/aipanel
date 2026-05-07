"""Symmetric encryption for at-rest secrets stored in Postgres.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from `cryptography`. The single
ENCRYPTION_KEY is loaded from /etc/aipanel/secrets.env via the env var of
the same name. The key is fetched lazily so importing this module before
the env is loaded is safe (e.g. in tooling).

Key rotation is out of scope for v0.2; once rows are written, regenerating
ENCRYPTION_KEY makes them unreadable.
"""

from __future__ import annotations

import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

ENV_VAR = "ENCRYPTION_KEY"


class CryptoError(RuntimeError):
    """Raised on missing key, malformed key, or decryption failure."""


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.environ.get(ENV_VAR)
    if not key:
        raise CryptoError(
            f"{ENV_VAR} is not set. Ensure /etc/aipanel/secrets.env is loaded "
            "before any encrypt/decrypt call."
        )
    try:
        # Fernet accepts bytes or str of the urlsafe-base64 key.
        return Fernet(key.encode("ascii") if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise CryptoError(f"Invalid {ENV_VAR}: {exc}") from exc


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return a urlsafe-base64 token suitable for `text`."""
    if plaintext is None:
        raise CryptoError("encrypt(None) is not allowed")
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token previously produced by `encrypt`."""
    if not ciphertext:
        raise CryptoError("decrypt() got empty input")
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise CryptoError("Decryption failed (key mismatch or tampering)") from exc


def reset_key_cache() -> None:
    """Clear the cached Fernet instance — used by tests after env mutation."""
    _fernet.cache_clear()
