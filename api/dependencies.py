"""
EdgeFinder — FastAPI Auth Dependencies

Reusable dependencies for authentication and authorization:
    get_current_user    — requires valid JWT (401 if missing/invalid)
    get_optional_user   — returns User or None (for pages that vary by auth state)
    require_role        — factory that returns a dependency checking user.role

Usage:
    @router.get("/admin-only")
    async def admin_panel(user: User = Depends(require_role("admin"))):
        ...

    @router.get("/dashboard")
    async def dashboard(user: User | None = Depends(get_optional_user)):
        if user is None:
            return RedirectResponse("/login")
        ...
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.models import User
from core.security import decode_access_token

logger = logging.getLogger(__name__)

_COOKIE_NAME = "ef_token"


def _extract_token(request: Request) -> str | None:
    """Extract JWT from cookie first, then Authorization header."""
    # 1. Cookie (browser dashboard + SSE — can't set headers on EventSource)
    token = request.cookies.get(_COOKIE_NAME)
    if token:
        return token

    # 2. Authorization header (API clients)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]

    return None


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Require authenticated user. Raises 401 if no valid token.
    """
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload = decode_access_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    result = await db.execute(
        select(User).where(User.id == int(user_id), User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """
    Return authenticated user or None. Does not raise 401.
    Used for pages that show different content based on auth state.
    """
    token = _extract_token(request)
    if not token:
        return None

    try:
        payload = decode_access_token(token)
    except JWTError:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    result = await db.execute(
        select(User).where(User.id == int(user_id), User.is_active.is_(True))
    )
    return result.scalar_one_or_none()


def require_role(*roles: str) -> Callable:
    """
    Factory that returns a dependency requiring the user to have one of the
    specified roles. Raises 403 if the user's role is not in the allowed set.

    Usage:
        @router.get("/admin")
        async def admin(user: User = Depends(require_role("admin"))):
            ...
    """
    async def _check_role(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {', '.join(roles)}",
            )
        return user

    return _check_role
