"""Authentication and Activation Code endpoints (User Login + Guest Passcode)."""
from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..config import (
    ALL_TIERS,
    COOKIE_MAX_AGE,
    GUEST_COOKIE_NAME,
    SESSION_COOKIE_NAME,
)
from ..database import get_db
from ..dependencies import (
    CurrentIdentity,
    expand_tier_grant,
    get_current_identity,
)
from ..models import ActivationCode, PermissionGrant, User
from ..schemas import (
    ActivateCodeRequest,
    ActivateCodeResponse,
    AuthStatusResponse,
    LoginRequest,
)
from ..security import (
    create_signed_token,
    generate_guest_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _ordered_tiers(tiers_set: set) -> List[str]:
    return [t for t in ALL_TIERS if t in tiers_set]


@router.get("/me", response_model=AuthStatusResponse)
def get_me(identity: CurrentIdentity = Depends(get_current_identity)):
    """Return current authentication & unlocked permission status."""
    role = "guest"
    username = None
    if identity.user:
        role = identity.user.role
        username = identity.user.username
    return AuthStatusResponse(
        is_authenticated=identity.is_authenticated,
        is_guest_activated=identity.is_guest_activated,
        username=username,
        role=role,
        unlocked_tiers=_ordered_tiers(identity.unlocked_tiers),
        unlocked_services=sorted(identity.unlocked_services),
        client_ip=identity.client_ip,
    )


@router.post("/login", response_model=AuthStatusResponse)
def login(
    payload: LoginRequest,
    response: Response,
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Authenticate with username and password, merging any guest unlocks into the user account."""
    user = db.query(User).filter(User.username == payload.username.strip()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if identity.guest_token:
        guest_grants = (
            db.query(PermissionGrant)
            .filter(PermissionGrant.session_token == identity.guest_token)
            .all()
        )
        for g in guest_grants:
            g.user_id = user.id
            g.session_token = None
        if guest_grants:
            db.commit()

    token = create_signed_token(
        {"user_id": user.id, "username": user.username, "role": user.role}
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )

    unlocked_tiers = set(identity.unlocked_tiers)
    unlocked_services = set(identity.unlocked_services)
    if user.role == "admin":
        unlocked_tiers = set(ALL_TIERS)
    else:
        user_grants = (
            db.query(PermissionGrant).filter(PermissionGrant.user_id == user.id).all()
        )
        for g in user_grants:
            if g.unlocked_tier:
                unlocked_tiers.update(expand_tier_grant(g.unlocked_tier))
            if g.unlocked_service_slug:
                unlocked_services.add(g.unlocked_service_slug)

    return AuthStatusResponse(
        is_authenticated=True,
        is_guest_activated=False,
        username=user.username,
        role=user.role,
        unlocked_tiers=_ordered_tiers(unlocked_tiers),
        unlocked_services=sorted(unlocked_services),
        client_ip=identity.client_ip,
    )


@router.post("/activate", response_model=ActivateCodeResponse)
def activate_code(
    payload: ActivateCodeRequest,
    response: Response,
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Redeem an activation code for either a logged-in account or a guest session."""
    code_str = payload.code.strip()
    ac = (
        db.query(ActivationCode)
        .filter(ActivationCode.code == code_str, ActivationCode.is_active == True)
        .first()
    )
    if not ac:
        raise HTTPException(status_code=400, detail="激活码无效或已停用")

    user_id = identity.user.id if identity.user else None
    guest_token = identity.guest_token

    if not user_id and not guest_token:
        guest_token = generate_guest_token()
        signed_guest = create_signed_token({"guest_token": guest_token})
        response.set_cookie(
            key=GUEST_COOKIE_NAME,
            value=signed_guest,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
        )

    existing_query = db.query(PermissionGrant).filter(
        PermissionGrant.source_code == ac.code
    )
    if user_id:
        existing = existing_query.filter(PermissionGrant.user_id == user_id).first()
    else:
        existing = existing_query.filter(
            PermissionGrant.session_token == guest_token
        ).first()

    if not existing:
        if ac.max_uses != -1 and ac.used_count >= ac.max_uses:
            raise HTTPException(status_code=400, detail="该激活码已达到使用次数上限")

        ac.used_count += 1

        new_grant = PermissionGrant(
            user_id=user_id,
            session_token=None if user_id else guest_token,
            unlocked_tier=ac.grant_tier,
            unlocked_service_slug=ac.grant_service_slug,
            source_code=ac.code,
        )
        db.add(new_grant)
        db.commit()

    if ac.grant_tier:
        identity.unlocked_tiers.update(expand_tier_grant(ac.grant_tier))
    if ac.grant_service_slug:
        identity.unlocked_services.add(ac.grant_service_slug)

    remaining = -1 if ac.max_uses == -1 else max(0, ac.max_uses - ac.used_count)

    msg = "激活成功！已为你解锁对应隐藏功能区"
    if existing:
        msg = "当前会话已具备该激活码对应的服务权限"

    return ActivateCodeResponse(
        success=True,
        message=msg,
        unlocked_tiers=_ordered_tiers(identity.unlocked_tiers),
        unlocked_services=sorted(identity.unlocked_services),
        remaining_uses=remaining,
    )


@router.post("/logout")
def logout(response: Response):
    """Clear both user session and guest activation cookies."""
    response.delete_cookie(SESSION_COOKIE_NAME)
    response.delete_cookie(GUEST_COOKIE_NAME)
    return {"success": True, "message": "已退出登录并清除本地激活状态"}
