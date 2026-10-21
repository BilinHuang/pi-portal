"""Authentication & Stealth Authorization Dependencies."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Set
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import (
    ALL_TIERS,
    DEFAULT_PUBLIC_TIERS,
    GUEST_COOKIE_NAME,
    SESSION_COOKIE_NAME,
)
from .database import get_db
from .models import PermissionGrant, Service, User
from .security import verify_signed_token


@dataclass
class CurrentIdentity:
    user: Optional[User] = None
    guest_token: Optional[str] = None
    unlocked_tiers: Set[str] = field(default_factory=lambda: set(DEFAULT_PUBLIC_TIERS))
    unlocked_services: Set[str] = field(default_factory=set)
    client_ip: str = "127.0.0.1"

    @property
    def is_authenticated(self) -> bool:
        return self.user is not None

    @property
    def is_admin(self) -> bool:
        return self.user is not None and self.user.role == "admin"

    @property
    def is_guest_activated(self) -> bool:
        return (
            not self.is_authenticated
            and (
                len(self.unlocked_tiers - set(DEFAULT_PUBLIC_TIERS)) > 0
                or len(self.unlocked_services) > 0
            )
        )


def extract_client_ip(request: Request) -> str:
    """Extract client IP with Cloudflare CF-Connecting-IP and X-Forwarded-For support."""
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def expand_tier_grant(grant_tier_str: Optional[str]) -> Set[str]:
    """Parse a grant_tier expression into a set of canonical tier strings."""
    if not grant_tier_str:
        return set()
    raw = grant_tier_str.strip()
    if raw in ("*", "ALL", "all"):
        return set(ALL_TIERS)
    if raw.startswith("<="):
        target = raw[2:].strip()
        if target in ALL_TIERS:
            idx = ALL_TIERS.index(target)
            return set(ALL_TIERS[: idx + 1])
    result = set()
    for part in raw.split(","):
        p = part.strip()
        if p in ALL_TIERS:
            result.add(p)
    return result


def get_current_identity(
    request: Request, db: Session = Depends(get_db)
) -> CurrentIdentity:
    """Resolve current user or guest session and compute all unlocked tiers and services."""
    identity = CurrentIdentity(
        unlocked_tiers=set(DEFAULT_PUBLIC_TIERS),
        unlocked_services=set(),
        client_ip=extract_client_ip(request),
    )

    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if session_cookie:
        payload = verify_signed_token(session_cookie)
        if payload and "user_id" in payload:
            user = db.query(User).filter(User.id == payload["user_id"]).first()
            if user:
                identity.user = user
                if user.role == "admin":
                    identity.unlocked_tiers = set(ALL_TIERS)
                else:
                    grants = (
                        db.query(PermissionGrant)
                        .filter(PermissionGrant.user_id == user.id)
                        .all()
                    )
                    for g in grants:
                        if g.unlocked_tier:
                            identity.unlocked_tiers.update(
                                expand_tier_grant(g.unlocked_tier)
                            )
                        if g.unlocked_service_slug:
                            identity.unlocked_services.add(g.unlocked_service_slug)

    guest_cookie = request.cookies.get(GUEST_COOKIE_NAME)
    if guest_cookie:
        payload = verify_signed_token(guest_cookie)
        if payload and "guest_token" in payload:
            guest_token = payload["guest_token"]
            identity.guest_token = guest_token
            grants = (
                db.query(PermissionGrant)
                .filter(PermissionGrant.session_token == guest_token)
                .all()
            )
            for g in grants:
                if g.unlocked_tier:
                    identity.unlocked_tiers.update(expand_tier_grant(g.unlocked_tier))
                if g.unlocked_service_slug:
                    identity.unlocked_services.add(g.unlocked_service_slug)

    return identity


def can_view_service(identity: CurrentIdentity, service: Service) -> bool:
    """Determine if the current identity is permitted to see the service card on the dashboard.

    Note: Even if a service's operational status is 'disabled', 'offline', or 'wip',
    permitted users still see the card (with its grey status tag).
    Unpermitted users do NOT see the card at all.
    """
    if identity.is_admin:
        return True
    if service.tier in identity.unlocked_tiers:
        return True
    if service.slug in identity.unlocked_services:
        return True
    return False


def can_launch_service(identity: CurrentIdentity, service: Service) -> bool:
    """Determine if a service can actually be launched/accessed."""
    if not can_view_service(identity, service):
        return False
    status = getattr(service, "status", "active") or "active"
    return status == "active"


def require_admin_or_404(
    identity: CurrentIdentity = Depends(get_current_identity),
) -> CurrentIdentity:
    """Stealth Admin Guard: raises 404 Not Found if caller is not an admin."""
    if not identity.is_admin:
        raise HTTPException(status_code=404, detail="Not Found")
    return identity
