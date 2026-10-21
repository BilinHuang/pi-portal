"""Authentication, Registration (Security Questions + 1h Invite Code), and Activation Code endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..config import (
    ALL_TIERS,
    COOKIE_MAX_AGE,
    GUEST_COOKIE_NAME,
    REGISTRATION_IDENTITY_QUESTIONS,
    REGISTRATION_LIFE_QUESTIONS,
    SESSION_COOKIE_NAME,
)
from ..database import get_db
from ..dependencies import (
    CurrentIdentity,
    expand_tier_grant,
    get_current_identity,
)
from ..models import ActivationCode, PermissionGrant, RegistrationInvite, User
from ..schemas import (
    ActivateCodeRequest,
    ActivateCodeResponse,
    AuthStatusResponse,
    LoginRequest,
    RegisterRequest,
)
from ..security import (
    create_signed_token,
    generate_guest_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _ordered_tiers(tiers_set: set) -> List[str]:
    return [t for t in ALL_TIERS if t in tiers_set]


def _normalize_answer(raw: str) -> str:
    """Normalize an answer by stripping whitespace, punctuation, and lowercasing."""
    if not raw:
        return ""
    cleaned = re.sub(r"[\s\-_.,，。、/\\!！?？'\"“”‘’()（）\[\]【】]+", "", raw.strip())
    return cleaned.lower()


@router.get("/register-questions")
def get_register_questions():
    """Return the public question prompts for the two registration dropdowns (never exposes answers)."""
    return {
        "identity_questions": [
            {"key": k, "prompt": v["prompt"]}
            for k, v in REGISTRATION_IDENTITY_QUESTIONS.items()
        ],
        "life_questions": [
            {"key": k, "prompt": v["prompt"]}
            for k, v in REGISTRATION_LIFE_QUESTIONS.items()
        ],
    }


@router.post("/register", response_model=AuthStatusResponse)
def register_account(
    payload: RegisterRequest,
    response: Response,
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Register a new user via either 2 security questions OR a 1-hour temporary admin invite code."""
    username_clean = payload.username.strip()
    if not re.match(r"^[a-zA-Z0-9_\u4e00-\u9fa5\-]{2,32}$", username_clean):
        raise HTTPException(
            status_code=400,
            detail="用户名需为 2~32 位中英文、数字、下划线或连字符",
        )

    existing_user = db.query(User).filter(User.username == username_clean).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="该用户名已被注册，请换一个")

    now_utc = datetime.now(timezone.utc)
    invite_str = (payload.invite_code or "").strip().upper()

    user_tag = "普通"
    grant_tier = "6+"

    # Path B: 1-Hour Temporary Invite Code provided
    if invite_str:
        invite = (
            db.query(RegistrationInvite)
            .filter(RegistrationInvite.code == invite_str)
            .first()
        )
        if not invite or invite.is_used:
            raise HTTPException(
                status_code=400, detail="临时注册验证码无效或已被使用"
            )
        exp = invite.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now_utc > exp:
            raise HTTPException(
                status_code=400, detail="该临时注册验证码已超过 1 小时有效期"
            )

        invite.is_used = True
        invite.used_by = username_clean
        user_tag = invite.user_tag or "验证码"
        grant_tier = invite.grant_tier or "<=9+"

        # If they also filled out Q1 correctly, use the more specific circle tag
        q1_key = (payload.q1_key or "").strip()
        q1_ans = _normalize_answer(payload.q1_answer or "")
        if q1_key in REGISTRATION_IDENTITY_QUESTIONS and q1_ans:
            q1_cfg = REGISTRATION_IDENTITY_QUESTIONS[q1_key]
            valid_q1 = {_normalize_answer(a) for a in q1_cfg["answers"]}
            if q1_ans in valid_q1:
                user_tag = q1_cfg["user_tag"]
                grant_tier = q1_cfg["grant_tier"]

    # Path A: Must answer at least 2 security questions (Q1 Identity + Q2 Life)
    else:
        q1_key = (payload.q1_key or "").strip()
        q2_key = (payload.q2_key or "").strip()
        q1_ans = _normalize_answer(payload.q1_answer or "")
        q2_ans = _normalize_answer(payload.q2_answer or "")

        if (
            q1_key not in REGISTRATION_IDENTITY_QUESTIONS
            or q2_key not in REGISTRATION_LIFE_QUESTIONS
        ):
            raise HTTPException(
                status_code=400,
                detail="请从下拉框中选择完整的两道验证问题并填写答案",
            )
        if not q1_ans or not q2_ans:
            raise HTTPException(
                status_code=400,
                detail="请完整回答两道验证问题以确认身份",
            )

        q1_cfg = REGISTRATION_IDENTITY_QUESTIONS[q1_key]
        q2_cfg = REGISTRATION_LIFE_QUESTIONS[q2_key]

        valid_q1 = {_normalize_answer(a) for a in q1_cfg["answers"]}
        valid_q2 = {_normalize_answer(a) for a in q2_cfg["answers"]}

        if q1_ans not in valid_q1 or q2_ans not in valid_q2:
            raise HTTPException(
                status_code=400,
                detail="默契问题回答不正确，请核对答案（或联系管理员获取 1 小时临时验证码）",
            )

        user_tag = q1_cfg["user_tag"]
        grant_tier = q1_cfg["grant_tier"]

    # Create user record
    new_user = User(
        username=username_clean,
        password_hash=hash_password(payload.password),
        password_plain=payload.password,
        role="user",
        user_tag=user_tag,
        ai_daily_limit=50,
        ai_used_today=0,
        ai_rpm_limit=10,
    )
    db.add(new_user)
    db.flush()

    # Grant corresponding tier permission (初中->6+, 高中->9+, 大学->12+, 家人->15+)
    db.add(
        PermissionGrant(
            user_id=new_user.id,
            session_token=None,
            unlocked_tier=grant_tier,
            unlocked_service_slug=None,
            source_code=f"REG:{user_tag}",
        )
    )

    # Merge any existing guest unlocks into the new account
    if identity.guest_token:
        guest_grants = (
            db.query(PermissionGrant)
            .filter(PermissionGrant.session_token == identity.guest_token)
            .all()
        )
        for g in guest_grants:
            g.user_id = new_user.id
            g.session_token = None

    db.commit()
    db.refresh(new_user)

    # Issue login cookie automatically
    token = create_signed_token(
        {
            "user_id": new_user.id,
            "username": new_user.username,
            "role": new_user.role,
        }
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )

    unlocked_tiers = set(identity.unlocked_tiers)
    unlocked_tiers.update(expand_tier_grant(grant_tier))

    return AuthStatusResponse(
        is_authenticated=True,
        is_guest_activated=False,
        username=new_user.username,
        role=new_user.role,
        user_tag=new_user.user_tag,
        unlocked_tiers=_ordered_tiers(unlocked_tiers),
        unlocked_services=sorted(identity.unlocked_services),
        client_ip=identity.client_ip,
        ai_daily_limit=new_user.ai_daily_limit,
        ai_used_today=new_user.ai_used_today,
        ai_rpm_limit=new_user.ai_rpm_limit,
    )


@router.get("/me", response_model=AuthStatusResponse)
def get_me(identity: CurrentIdentity = Depends(get_current_identity)):
    """Return current authentication & unlocked permission status."""
    role = "guest"
    username = None
    user_tag = None
    ai_daily = 50
    ai_used = 0
    ai_rpm = 10
    if identity.user:
        role = identity.user.role
        username = identity.user.username
        user_tag = getattr(identity.user, "user_tag", "普通")
        ai_daily = getattr(identity.user, "ai_daily_limit", 50)
        ai_used = getattr(identity.user, "ai_used_today", 0)
        ai_rpm = getattr(identity.user, "ai_rpm_limit", 10)
    return AuthStatusResponse(
        is_authenticated=identity.is_authenticated,
        is_guest_activated=identity.is_guest_activated,
        username=username,
        role=role,
        user_tag=user_tag,
        unlocked_tiers=_ordered_tiers(identity.unlocked_tiers),
        unlocked_services=sorted(identity.unlocked_services),
        client_ip=identity.client_ip,
        ai_daily_limit=ai_daily,
        ai_used_today=ai_used,
        ai_rpm_limit=ai_rpm,
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

    # Sync password_plain if empty so admin table can display it
    if not getattr(user, "password_plain", None):
        user.password_plain = payload.password
        db.commit()

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
        user_tag=getattr(user, "user_tag", "普通"),
        unlocked_tiers=_ordered_tiers(unlocked_tiers),
        unlocked_services=sorted(unlocked_services),
        client_ip=identity.client_ip,
        ai_daily_limit=getattr(user, "ai_daily_limit", 50),
        ai_used_today=getattr(user, "ai_used_today", 0),
        ai_rpm_limit=getattr(user, "ai_rpm_limit", 10),
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
