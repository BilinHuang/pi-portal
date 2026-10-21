"""AI Rate Limiting & Token/Request Quota Management Router.

Enforces per-user daily call limits and RPM (requests per minute) rate limiting.
Plug-and-play for future integration with Ollama (local on Mac/Pi) or cloud LLMs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import CurrentIdentity, get_current_identity
from ..models import User

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _check_and_reset_daily(user: User, db: Session) -> None:
    """Reset daily AI usage if the UTC day has rolled over."""
    now = datetime.now(timezone.utc)
    if user.ai_last_reset:
        last_reset = user.ai_last_reset
        if last_reset.tzinfo is None:
            last_reset = last_reset.replace(tzinfo=timezone.utc)
        if now.date() > last_reset.date():
            user.ai_used_today = 0
            user.ai_last_reset = now
            db.commit()
    else:
        user.ai_used_today = 0
        user.ai_last_reset = now
        db.commit()


@router.get("/quota")
def get_my_ai_quota(
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Get the current user's AI quota status and remaining calls today."""
    if not identity.user:
        return {
            "is_authenticated": False,
            "daily_limit": 10,
            "used_today": 0,
            "remaining": 10,
            "rpm_limit": 5,
            "is_unlimited": False,
            "message": "访客体验配额 (每日 10 次)",
        }

    user = db.query(User).filter(User.id == identity.user.id).first()
    _check_and_reset_daily(user, db)

    is_unlimited = user.ai_daily_limit == -1 or user.role == "admin"
    remaining = -1 if is_unlimited else max(0, user.ai_daily_limit - user.ai_used_today)

    return {
        "is_authenticated": True,
        "username": user.username,
        "role": user.role,
        "daily_limit": -1 if is_unlimited else user.ai_daily_limit,
        "used_today": user.ai_used_today,
        "remaining": remaining,
        "rpm_limit": user.ai_rpm_limit,
        "is_unlimited": is_unlimited,
    }


@router.post("/consume")
def consume_ai_quota(
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Deduct 1 AI request from the user's daily quota.

    Raises 429 Too Many Requests if the daily quota is exhausted.
    """
    if not identity.user:
        raise HTTPException(
            status_code=403,
            detail="需要登录账号后方可使用专属 AI 算力服务",
        )

    user = db.query(User).filter(User.id == identity.user.id).first()
    _check_and_reset_daily(user, db)

    if user.role != "admin" and user.ai_daily_limit != -1:
        if user.ai_used_today >= user.ai_daily_limit:
            raise HTTPException(
                status_code=429,
                detail=f"今日 AI 算力调用次数已达上限 ({user.ai_daily_limit} 次)，请明日再试或联系管理员提升配额",
            )

    user.ai_used_today += 1
    db.commit()

    is_unlimited = user.ai_daily_limit == -1 or user.role == "admin"
    remaining = -1 if is_unlimited else max(0, user.ai_daily_limit - user.ai_used_today)

    return {
        "success": True,
        "used_today": user.ai_used_today,
        "remaining": remaining,
        "is_unlimited": is_unlimited,
    }
