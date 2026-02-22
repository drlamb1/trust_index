"""
EdgeFinder — Security Module

Password hashing (bcrypt) and JWT token management (python-jose).

Usage:
    from core.security import hash_password, verify_password, create_access_token, decode_access_token

    hashed = hash_password("mysecretpassword")
    assert verify_password("mysecretpassword", hashed)

    token = create_access_token({"sub": "user@example.com"})
    payload = decode_access_token(token)  # raises JWTError on failure
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from config.settings import settings

# ---------------------------------------------------------------------------
# Password hashing (bcrypt directly — passlib is abandoned/incompatible)
# ---------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------


def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a signed JWT access token.

    The `data` dict is copied and an `exp` claim is added.
    Default expiry comes from settings.access_token_expire_minutes.
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta
        or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode["exp"] = expire
    return jwt.encode(
        to_encode,
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict:
    """
    Decode and verify a JWT access token.

    Returns the payload dict on success.
    Raises jose.JWTError on invalid/expired tokens.
    """
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
    )
