"""Services discovery and Stealth 404 launch/redirect endpoints."""
from __future__ import annotations

from typing import Dict, List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..config import ALL_TIERS, SERVICE_STATUS_META, TIER_META
from ..database import get_db
from ..dependencies import (
    CurrentIdentity,
    can_launch_service,
    can_view_service,
    get_current_identity,
)
from ..models import Service
from ..schemas import DashboardServicesResponse, ServiceCardSchema, TierGroupSchema

router = APIRouter(tags=["services"])


@router.get("/api/services", response_model=DashboardServicesResponse)
def list_visible_services(
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Return ONLY the categories and services that the current user/guest has unlocked.

    - Unpermitted categories are completely omitted (stealth).
    - Age tier strings (6+, 9+, etc.) are never exposed in UI labels; instead, each card
      carries its operational status tag ('运行中', '已关闭', '暂不可用', '待开发').
    """
    all_services = (
        db.query(Service)
        .order_by(Service.sort_order.asc(), Service.id.asc())
        .all()
    )

    by_tier: Dict[str, List[ServiceCardSchema]] = {t: [] for t in ALL_TIERS}
    total_visible = 0

    for svc in all_services:
        if can_view_service(identity, svc):
            raw_status = getattr(svc, "status", "active") or "active"
            if raw_status not in SERVICE_STATUS_META:
                raw_status = "active"
            s_meta = SERVICE_STATUS_META[raw_status]

            card = ServiceCardSchema(
                id=svc.id,
                slug=svc.slug,
                name=svc.name,
                description=svc.description,
                icon=svc.icon,
                status=raw_status,
                status_label=s_meta["label"],
                status_badge_class=s_meta["badge_class"],
                is_available=bool(s_meta["is_available"]),
                launch_url=f"/go/{svc.slug}",
                target_url=svc.target_url,
                open_in_new_tab=svc.open_in_new_tab,
            )
            if svc.tier in by_tier:
                by_tier[svc.tier].append(card)
                total_visible += 1

    groups: List[TierGroupSchema] = []
    for idx, tier in enumerate(ALL_TIERS, start=1):
        cards = by_tier[tier]
        if not cards:
            continue
        meta = TIER_META.get(
            tier,
            {"label": "扩展服务", "subtitle": ""},
        )
        groups.append(
            TierGroupSchema(
                group_id=f"section-{idx}",
                label=meta["label"],
                subtitle=meta["subtitle"],
                services=cards,
            )
        )

    return DashboardServicesResponse(
        groups=groups,
        total_visible_services=total_visible,
    )


@router.get("/go/{slug}")
@router.get("/api/services/launch/{slug}")
def launch_service(
    slug: str,
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Stealth launch gate: redirects only if authorized AND service status is 'active'."""
    service = db.query(Service).filter(Service.slug == slug).first()
    if not service or not can_launch_service(identity, service):
        raise HTTPException(status_code=404, detail="Not Found")

    return RedirectResponse(url=service.target_url, status_code=307)


@router.get("/apps/{slug}", response_class=HTMLResponse)
def builtin_mini_app(
    slug: str,
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Built-in mini-application host page protected by the Stealth 404 guard."""
    service = db.query(Service).filter(Service.slug == slug).first()
    if not service or not can_launch_service(identity, service):
        raise HTTPException(status_code=404, detail="Not Found")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{service.name} — Pi Node App</title>
  <link rel="stylesheet" href="/static/css/style.css" />
</head>
<body class="subapp-body">
  <div class="subapp-container">
    <div class="subapp-header">
      <a href="/" class="btn btn-ghost">← 返回 Dashboard</a>
      <span class="status-tag status-tag-active">运行中</span>
    </div>
    <div class="subapp-card">
      <div class="subapp-icon">{service.icon}</div>
      <h1>{service.name}</h1>
      <p class="subapp-desc">{service.description}</p>
      <div class="subapp-status-box">
        <div><strong>服务标识 (Slug):</strong> <code>{service.slug}</code></div>
        <div><strong>运行状态:</strong> <code>运行中 (Active)</code></div>
        <div><strong>当前访问者:</strong> <code>{identity.user.username if identity.user else '已授权访客 (Guest Session)'}</code></div>
        <div><strong>来源 IP:</strong> <code>{identity.client_ip}</code></div>
      </div>
      <div class="subapp-interactive" id="mini-app-workspace" data-slug="{service.slug}">
        <p class="muted">此模块运行于树莓派受保护路由 <code>/apps/{service.slug}</code>。若未获授权或该功能被管理员关闭/离线，直接访问此 URL 将返回 404。</p>
      </div>
    </div>
  </div>
</body>
</html>"""
