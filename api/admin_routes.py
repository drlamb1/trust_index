"""
EdgeFinder — Admin API Routes

User management endpoints (admin only):
    POST   /api/admin/users                    → Create user
    GET    /api/admin/users/{id}               → Get user details
    PATCH  /api/admin/users/{id}               → Update user fields
    DELETE /api/admin/users/{id}               → Delete user
    POST   /api/admin/users/{id}/reset-password → Reset password
    POST   /api/admin/users/{id}/deactivate    → Deactivate user
    POST   /api/admin/users/{id}/activate      → Reactivate user
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import require_role
from core.database import get_db
from core.models import User
from core.security import hash_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

VALID_ROLES = {"admin", "member", "viewer"}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateUserRequest(BaseModel):
    email: EmailStr
    username: str
    password: str
    role: str = "viewer"
    daily_token_budget: int = 50000


class UpdateUserRequest(BaseModel):
    email: EmailStr | None = None
    username: str | None = None
    role: str | None = None
    is_active: bool | None = None
    daily_token_budget: int | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "username": u.username,
        "role": u.role,
        "is_active": u.is_active,
        "daily_token_budget": u.daily_token_budget,
        "tokens_used_today": u.tokens_used_today,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


async def _get_user_or_404(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ---------------------------------------------------------------------------
# Create user
# ---------------------------------------------------------------------------


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new user account."""
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(sorted(VALID_ROLES))}")

    existing = await db.execute(
        select(User).where((User.email == body.email) | (User.username == body.username))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email or username already exists")

    user = User(
        email=body.email,
        username=body.username,
        hashed_password=hash_password(body.password),
        role=body.role,
        daily_token_budget=body.daily_token_budget if body.role == "viewer" else 0,
    )
    db.add(user)
    await db.flush()

    logger.info("Admin %s created user %s (%s, role=%s)", admin.username, user.username, user.email, user.role)
    return {"message": "User created", "user": _user_dict(user)}


# ---------------------------------------------------------------------------
# Get single user
# ---------------------------------------------------------------------------


@router.get("/users/{user_id}")
async def get_user(
    user_id: int,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single user's details."""
    user = await _get_user_or_404(db, user_id)
    return {"user": _user_dict(user)}


# ---------------------------------------------------------------------------
# Update user
# ---------------------------------------------------------------------------


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update user fields (partial update)."""
    user = await _get_user_or_404(db, user_id)

    if body.role is not None:
        if body.role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(sorted(VALID_ROLES))}")
        user.role = body.role

    if body.email is not None:
        conflict = await db.execute(select(User).where(User.email == body.email, User.id != user_id))
        if conflict.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already in use")
        user.email = body.email

    if body.username is not None:
        conflict = await db.execute(select(User).where(User.username == body.username, User.id != user_id))
        if conflict.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Username already in use")
        user.username = body.username

    if body.is_active is not None:
        if user.id == admin.id and not body.is_active:
            raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
        user.is_active = body.is_active

    if body.daily_token_budget is not None:
        user.daily_token_budget = body.daily_token_budget

    await db.flush()
    logger.info("Admin %s updated user %s (id=%d)", admin.username, user.username, user.id)
    return {"message": "User updated", "user": _user_dict(user)}


# ---------------------------------------------------------------------------
# Delete user
# ---------------------------------------------------------------------------


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Hard delete a user."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    user = await _get_user_or_404(db, user_id)
    username = user.username
    await db.delete(user)
    await db.flush()

    logger.info("Admin %s deleted user %s (id=%d)", admin.username, username, user_id)
    return {"message": f"User '{username}' deleted"}


# ---------------------------------------------------------------------------
# Reset password
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: int,
    body: ResetPasswordRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Admin resets another user's password."""
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user = await _get_user_or_404(db, user_id)
    user.hashed_password = hash_password(body.new_password)
    await db.flush()

    logger.info("Admin %s reset password for user %s (id=%d)", admin.username, user.username, user_id)
    return {"message": f"Password reset for '{user.username}'"}


# ---------------------------------------------------------------------------
# Deactivate / Activate
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: int,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deactivate a user (soft disable)."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    user = await _get_user_or_404(db, user_id)
    user.is_active = False
    await db.flush()

    logger.info("Admin %s deactivated user %s (id=%d)", admin.username, user.username, user_id)
    return {"message": f"User '{user.username}' deactivated"}


@router.post("/users/{user_id}/activate")
async def activate_user(
    user_id: int,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reactivate a deactivated user."""
    user = await _get_user_or_404(db, user_id)
    user.is_active = True
    await db.flush()

    logger.info("Admin %s activated user %s (id=%d)", admin.username, user.username, user_id)
    return {"message": f"User '{user.username}' activated"}
