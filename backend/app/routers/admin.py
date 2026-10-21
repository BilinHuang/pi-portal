"""Stealth Admin Router for managing Feature Switches, Activation Codes, Services, Users & AI Quotas.

All endpoints require admin role; non-admin requests receive 404 Not Found.
"""
from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import ALL_TIERS, SERVICE_STATUS_META, TIER_META
from ..database import get_db
from ..dependencies import CurrentIdentity, expand_tier_grant, require_admin_or_404
from ..models import ActivationCode, PermissionGrant, Service, User
from ..schemas import (
    ActivationCodeItemSchema,
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AdminUpdateAiQuotaRequest,
    AdminUserItemSchema,
    CreateActivationCodeRequest,
    CreateServiceRequest,
    UpdateServiceStatusRequest,
)
from ..security import hash_password

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_or_404)],
)


# ==================== User & AI Quota Management ====================


@router.get("/users", response_model=List[AdminUserItemSchema])
def list_users(db: Session = Depends(get_db)):
    """List all user accounts with their unlocked permissions and AI quota configurations."""
    users = db.query(User).order_by(User.id.asc()).all()
    results = []

    for u in users:
        unlocked_tiers = set()
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
                role=u.role,
                created_at=u.created_at,
                unlocked_tiers=sorted(unlocked_tiers),
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
    """Create a new user account with initial password and AI quota."""
    username_clean = payload.username.strip()
    existing = db.query(User).filter(User.username == username_clean).first()
    if existing:
        raise HTTPException(status_code=400, detail="该用户名已存在")

    new_user = User(
        username=username_clean,
        password_hash=hash_password(payload.password),
        role=payload.role,
        ai_daily_limit=payload.ai_daily_limit,
        ai_used_today=0,
        ai_rpm_limit=payload.ai_rpm_limit,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return AdminUserItemSchema(
        id=new_user.id,
        username=new_user.username,
        role=new_user.role,
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
    """Admin resets any user's password directly."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Not Found")

    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"success": True, "message": f"用户 [{user.username}] 的密码已重置成功"}


@router.patch("/users/{user_id}/ai-quota")
def update_user_ai_quota(
    user_id: int,
    payload: AdminUpdateAiQuotaRequest,
    db: Session = Depends(get_db),
):
    """Update AI daily request quota and RPM rate limit for a user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Not Found")

    user.ai_daily_limit = payload.ai_daily_limit
    user.ai_rpm_limit = payload.ai_rpm_limit
    db.commit()
    return {
        "success": True,
        "user_id": user.id,
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
