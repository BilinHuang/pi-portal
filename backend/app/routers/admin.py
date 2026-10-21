"""Stealth Admin Router for managing Users, Passwords, 1h Registration Invites, AI Quotas, Codes & Services.

All endpoints require admin role; non-admin requests receive 404 Not Found.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import ALL_TIERS, SERVICE_STATUS_META, TIER_META
from ..database import get_db
from ..dependencies import CurrentIdentity, expand_tier_grant, require_admin_or_404
from ..models import ActivationCode, PermissionGrant, RegistrationInvite, Service, User
from ..schemas import (
    ActivationCodeItemSchema,
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AdminUpdateAiQuotaRequest,
    AdminUserItemSchema,
    CreateActivationCodeRequest,
    CreateServiceRequest,
    RegistrationInviteItemSchema,
    UpdateServiceStatusRequest,
)
from ..security import hash_password

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_or_404)],
)


# ==================== User, Password & AI Quota Management ====================


@router.get("/users", response_model=List[AdminUserItemSchema])
def list_users(db: Session = Depends(get_db)):
    """List all user accounts with their plain passwords, circle tags, unlocked permissions, and AI quotas."""
    users = db.query(User).order_by(User.id.asc()).all()
    results = []

    for u in users:
        unlocked_tiers = {"6+"}
        unlocked_services = set()
        if u.role == "admin":
            unlocked_tiers = set(ALL_TIERS)
        else:
            grants = (
                db.query(PermissionGrant).filter(PermissionGrant.user_id == u.id).all()
            )
            for g in grants:
                if g.unlocked_tier:
                    unlocked_tiers.update(expand_tier_grant(g.unlocked_tier))
                if g.unlocked_service_slug:
                    unlocked_services.add(g.unlocked_service_slug)

        results.append(
            AdminUserItemSchema(
                id=u.id,
                username=u.username,
                password_plain=getattr(u, "password_plain", "") or "",
                role=u.role,
                user_tag=getattr(u, "user_tag", "普通") or "普通",
                created_at=u.created_at,
                unlocked_tiers=[t for t in ALL_TIERS if t in unlocked_tiers],
                unlocked_services=sorted(unlocked_services),
                ai_daily_limit=getattr(u, "ai_daily_limit", 50),
                ai_used_today=getattr(u, "ai_used_today", 0),
                ai_rpm_limit=getattr(u, "ai_rpm_limit", 10),
            )
        )

    return results


@router.post("/users", response_model=AdminUserItemSchema)
def create_user(
    payload: AdminCreateUserRequest,
    db: Session = Depends(get_db),
):
    """Create a new user account with initial password, circle tag, and AI quota."""
    username_clean = payload.username.strip()
    existing = db.query(User).filter(User.username == username_clean).first()
    if existing:
        raise HTTPException(status_code=400, detail="该用户名已存在")

    tag_clean = payload.user_tag.strip() or ("管理员" if payload.role == "admin" else "普通")
    new_user = User(
        username=username_clean,
        password_hash=hash_password(payload.password),
        password_plain=payload.password,
        role=payload.role,
        user_tag=tag_clean,
        ai_daily_limit=payload.ai_daily_limit,
        ai_used_today=0,
        ai_rpm_limit=payload.ai_rpm_limit,
    )
    db.add(new_user)
    db.flush()

    # Map tag to default tier grant if applicable
    tag_to_tier = {
        "初中": "6+",
        "高中": "<=9+",
        "大学": "<=12+",
        "家人": "<=15+",
    }
    if tag_clean in tag_to_tier:
        db.add(
            PermissionGrant(
                user_id=new_user.id,
                unlocked_tier=tag_to_tier[tag_clean],
                source_code=f"ADMIN:{tag_clean}",
            )
        )

    db.commit()
    db.refresh(new_user)

    return AdminUserItemSchema(
        id=new_user.id,
        username=new_user.username,
        password_plain=new_user.password_plain,
        role=new_user.role,
        user_tag=new_user.user_tag,
        created_at=new_user.created_at,
        unlocked_tiers=ALL_TIERS if new_user.role == "admin" else ["6+"],
        unlocked_services=[],
        ai_daily_limit=new_user.ai_daily_limit,
        ai_used_today=new_user.ai_used_today,
        ai_rpm_limit=new_user.ai_rpm_limit,
    )


@router.put("/users/{user_id}/password")
def reset_user_password(
    user_id: int,
    payload: AdminResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """Admin resets any user's password directly and updates password_plain."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Not Found")

    user.password_hash = hash_password(payload.new_password)
    user.password_plain = payload.new_password
    db.commit()
    return {"success": True, "message": f"用户 [{user.username}] 的密码已更新"}


@router.patch("/users/{user_id}/ai-quota")
def update_user_ai_quota(
    user_id: int,
    payload: AdminUpdateAiQuotaRequest,
    db: Session = Depends(get_db),
):
    """Update AI daily request quota, RPM rate limit, and optional user_tag for a user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Not Found")

    user.ai_daily_limit = payload.ai_daily_limit
    user.ai_rpm_limit = payload.ai_rpm_limit
    if payload.user_tag is not None and payload.user_tag.strip():
        user.user_tag = payload.user_tag.strip()
    db.commit()
    return {
        "success": True,
        "user_id": user.id,
        "user_tag": user.user_tag,
        "ai_daily_limit": user.ai_daily_limit,
        "ai_rpm_limit": user.ai_rpm_limit,
    }


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    identity: CurrentIdentity = Depends(require_admin_or_404),
    db: Session = Depends(get_db),
):
    """Delete a user account (cannot delete currently logged in admin)."""
    if identity.user and identity.user.id == user_id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的管理员账号")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Not Found")

    db.delete(user)
    db.commit()
    return {"success": True}


# ==================== 1-Hour Temporary Registration Invites ====================


@router.get("/invites", response_model=List[RegistrationInviteItemSchema])
def list_registration_invites(db: Session = Depends(get_db)):
    """List recent 1-hour temporary registration verification codes."""
    now_utc = datetime.now(timezone.utc)
    invites = (
        db.query(RegistrationInvite)
        .order_by(RegistrationInvite.id.desc())
        .limit(20)
        .all()
    )
    result = []
    for inv in invites:
        exp = inv.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        result.append(
            RegistrationInviteItemSchema(
                id=inv.id,
                code=inv.code,
                user_tag=inv.user_tag,
                grant_tier=inv.grant_tier,
                is_used=bool(inv.is_used),
                used_by=inv.used_by,
                created_at=inv.created_at,
                expires_at=inv.expires_at,
                is_expired=(now_utc > exp),
            )
        )
    return result


@router.post("/invites", response_model=RegistrationInviteItemSchema)
def generate_one_hour_invite(
    user_tag: str = "验证码",
    grant_tier: str = "<=9+",
    db: Session = Depends(get_db),
):
    """Generate a 1-hour valid registration verification code with one click."""
    now_utc = datetime.now(timezone.utc)
    expires_at = now_utc + timedelta(hours=1)
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    random_part = "".join(secrets.choice(alphabet) for _ in range(6))
    code = f"REG-{random_part}"

    inv = RegistrationInvite(
        code=code,
        user_tag=user_tag.strip() or "验证码",
        grant_tier=grant_tier.strip() or "<=9+",
        is_used=False,
        created_at=now_utc,
        expires_at=expires_at,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)

    return RegistrationInviteItemSchema(
        id=inv.id,
        code=inv.code,
        user_tag=inv.user_tag,
        grant_tier=inv.grant_tier,
        is_used=False,
        used_by=None,
        created_at=inv.created_at,
        expires_at=inv.expires_at,
        is_expired=False,
    )


@router.delete("/invites/{invite_id}")
def delete_registration_invite(invite_id: int, db: Session = Depends(get_db)):
    """Delete a temporary registration invite code."""
    inv = (
        db.query(RegistrationInvite)
        .filter(RegistrationInvite.id == invite_id)
        .first()
    )
    if not inv:
        raise HTTPException(status_code=404, detail="Not Found")
    db.delete(inv)
    db.commit()
    return {"success": True}


# ==================== Activation Codes Management ====================


@router.get("/codes", response_model=List[ActivationCodeItemSchema])
def list_activation_codes(db: Session = Depends(get_db)):
    """List all activation codes and their usage statistics."""
    return db.query(ActivationCode).order_by(ActivationCode.id.desc()).all()


@router.post("/codes", response_model=ActivationCodeItemSchema)
def create_activation_code(
    payload: CreateActivationCodeRequest,
    db: Session = Depends(get_db),
):
    """Create a new finite or infinite activation code."""
    code_clean = payload.code.strip()
    existing = (
        db.query(ActivationCode).filter(ActivationCode.code == code_clean).first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="该激活码已存在")

    if not payload.grant_tier and not payload.grant_service_slug:
        raise HTTPException(
            status_code=400,
            detail="必须至少指定解锁分类 (grant_tier) 或解锁服务 (grant_service_slug) 之一",
        )

    ac = ActivationCode(
        code=code_clean,
        description=payload.description.strip(),
        grant_tier=payload.grant_tier.strip() if payload.grant_tier else None,
        grant_service_slug=(
            payload.grant_service_slug.strip() if payload.grant_service_slug else None
        ),
        max_uses=payload.max_uses,
        used_count=0,
        is_active=True,
    )
    db.add(ac)
    db.commit()
    db.refresh(ac)
    return ac


@router.delete("/codes/{code_id}")
def delete_activation_code(code_id: int, db: Session = Depends(get_db)):
    """Delete an activation code by ID."""
    ac = db.query(ActivationCode).filter(ActivationCode.id == code_id).first()
    if not ac:
        raise HTTPException(status_code=404, detail="Not Found")
    db.delete(ac)
    db.commit()
    return {"success": True}


# ==================== Services Management ====================


@router.get("/services")
def list_all_services_admin(db: Session = Depends(get_db)):
    """List all services across all groups for admin feature switch & management."""
    services = (
        db.query(Service)
        .order_by(Service.sort_order.asc(), Service.id.asc())
        .all()
    )
    result = []
    for s in services:
        raw_status = getattr(s, "status", "active") or "active"
        s_meta = SERVICE_STATUS_META.get(raw_status, SERVICE_STATUS_META["active"])
        t_meta = TIER_META.get(s.tier, {"label": s.tier})
        result.append(
            {
                "id": s.id,
                "slug": s.slug,
                "name": s.name,
                "description": s.description,
                "icon": s.icon,
                "tier": s.tier,
                "category_label": t_meta["label"],
                "status": raw_status,
                "status_label": s_meta["label"],
                "target_url": s.target_url,
                "open_in_new_tab": s.open_in_new_tab,
                "sort_order": s.sort_order,
            }
        )
    return result


@router.patch("/services/{service_id}/status")
def update_service_status_admin(
    service_id: int,
    payload: UpdateServiceStatusRequest,
    db: Session = Depends(get_db),
):
    """Toggle a service's operational state ('active', 'disabled', 'offline', 'wip')."""
    svc = db.query(Service).filter(Service.id == service_id).first()
    if not svc:
        raise HTTPException(status_code=404, detail="Not Found")

    svc.status = payload.status
    svc.is_enabled = payload.status == "active"
    db.commit()
    db.refresh(svc)
    s_meta = SERVICE_STATUS_META.get(svc.status, SERVICE_STATUS_META["active"])
    return {
        "success": True,
        "id": svc.id,
        "slug": svc.slug,
        "status": svc.status,
        "status_label": s_meta["label"],
    }


@router.post("/services")
def create_service_admin(
    payload: CreateServiceRequest,
    db: Session = Depends(get_db),
):
    """Create a new dashboard service card."""
    existing = db.query(Service).filter(Service.slug == payload.slug.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="服务标识 (slug) 已存在")

    svc = Service(
        slug=payload.slug.strip(),
        name=payload.name.strip(),
        description=payload.description.strip(),
        icon=payload.icon.strip() or "⚡",
        tier=payload.tier,
        target_url=payload.target_url.strip(),
        status=payload.status,
        open_in_new_tab=payload.open_in_new_tab,
        sort_order=payload.sort_order,
        is_enabled=(payload.status == "active"),
    )
    db.add(svc)
    db.commit()
    db.refresh(svc)
    return {"success": True, "id": svc.id, "slug": svc.slug}


@router.delete("/services/{service_id}")
def delete_service_admin(service_id: int, db: Session = Depends(get_db)):
    """Delete a service by ID."""
    svc = db.query(Service).filter(Service.id == service_id).first()
    if not svc:
        raise HTTPException(status_code=404, detail="Not Found")
    db.delete(svc)
    db.commit()
    return {"success": True}
