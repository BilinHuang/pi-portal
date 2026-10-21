"""Database seeding script for Pi Stealth Dashboard.

Creates or updates:
- Default users: `admin` (password: `admin123`) and `guest_user` (password: `user123`)
- Pre-configured services with operational status tags ('active', 'disabled', 'offline', 'wip')
- Pre-configured activation codes (infinite uses, limited count uses, single-service unlock)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.database import Base, SessionLocal, engine, ensure_schema_migrations
from backend.app.models import ActivationCode, Service, User
from backend.app.security import hash_password


def seed():
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations()
    db = SessionLocal()

    try:
        # 1. Seed Users
        users_data = [
            ("admin", "admin123", "admin"),
            ("guest_user", "user123", "user"),
        ]
        for username, pwd, role in users_data:
            existing_user = db.query(User).filter(User.username == username).first()
            if not existing_user:
                db.add(
                    User(
                        username=username,
                        password_hash=hash_password(pwd),
                        role=role,
                    )
                )

        # 2. Seed Services across internal tiers with realistic operational statuses
        services_data = [
            # 6+ Public Baseline
            {
                "slug": "pi-status-note",
                "name": "节点公告与便签",
                "description": "树莓派公开运行日志、局域网常用备忘录与公告板。",
                "icon": "📋",
                "tier": "6+",
                "target_url": "/apps/pi-status-note",
                "open_in_new_tab": False,
                "status": "active",
                "sort_order": 1,
            },
            {
                "slug": "speedtest-node",
                "name": "内网测速与延迟诊断",
                "description": "测试当前设备到树莓派 5 节点与 Cloudflare 边缘的响应速度。",
                "icon": "🚀",
                "tier": "6+",
                "target_url": "/apps/speedtest-node",
                "open_in_new_tab": False,
                "status": "active",
                "sort_order": 2,
            },
            {
                "slug": "mac-ai-assistant",
                "name": "Mac 本地大模型推理端",
                "description": "挂载于 Mac 节点的 Ollama 本地推理服务（当 Mac 休眠或离线时暂不可用）。",
                "icon": "🧠",
                "tier": "6+",
                "target_url": "/apps/mac-ai-assistant",
                "open_in_new_tab": False,
                "status": "offline",
                "sort_order": 3,
            },
            {
                "slug": "smart-home-hub",
                "name": "传感器与家居联动面板",
                "description": "树莓派 GPIO 温湿度传感器与自动化规则编排（规划中尚未编写）。",
                "icon": "🏡",
                "tier": "6+",
                "target_url": "/apps/smart-home-hub",
                "open_in_new_tab": False,
                "status": "wip",
                "sort_order": 4,
            },
            # 9+ Tier
            {
                "slug": "family-recipes",
                "name": "共享菜谱与采购清单",
                "description": "日常采购清单与家庭菜谱归档服务。",
                "icon": "🍲",
                "tier": "9+",
                "target_url": "/apps/family-recipes",
                "open_in_new_tab": False,
                "status": "active",
                "sort_order": 1,
            },
            {
                "slug": "music-stream",
                "name": "Navidrome 音乐电台",
                "description": "树莓派自建无损音乐流媒体服务器，支持多端在线播放。",
                "icon": "🎵",
                "tier": "9+",
                "target_url": "/apps/music-stream",
                "open_in_new_tab": True,
                "status": "disabled",
                "sort_order": 2,
            },
            # 12+ Tier
            {
                "slug": "immich-photos",
                "name": "Immich 私有云相册",
                "description": "个人手机照片自动备份与时间线检索相册。",
                "icon": "🖼️",
                "tier": "12+",
                "target_url": "/apps/immich-photos",
                "open_in_new_tab": True,
                "status": "active",
                "sort_order": 1,
            },
            {
                "slug": "mac-video-transcode",
                "name": "Mac 远程渲染与转码集群",
                "description": "调用 Mac Apple Silicon 硬件编码器处理视频任务（需 Mac 在线）。",
                "icon": "🎞️",
                "tier": "12+",
                "target_url": "/apps/mac-video-transcode",
                "open_in_new_tab": True,
                "status": "offline",
                "sort_order": 2,
            },
            {
                "slug": "gitea-git",
                "name": "Gitea 私有代码仓库",
                "description": "运行在树莓派上的轻量级 Git 代码托管与 CI 节点。",
                "icon": "🦊",
                "tier": "12+",
                "target_url": "/apps/gitea-git",
                "open_in_new_tab": True,
                "status": "wip",
                "sort_order": 3,
            },
            # 15+ Tier
            {
                "slug": "vaultwarden",
                "name": "Vaultwarden 密码金库",
                "description": "高敏个人密码管理器与双重验证密钥托管中心。",
                "icon": "🔐",
                "tier": "15+",
                "target_url": "/apps/vaultwarden",
                "open_in_new_tab": True,
                "status": "active",
                "sort_order": 1,
            },
            {
                "slug": "wireguard-panel",
                "name": "内网穿透与隧道控制台",
                "description": "回家隧道、Cloudflare Tunnel 路由规则与节点防火墙配置。",
                "icon": "🛡️",
                "tier": "15+",
                "target_url": "/apps/wireguard-panel",
                "open_in_new_tab": True,
                "status": "disabled",
                "sort_order": 2,
            },
            # 18+ Stealth Tier
            {
                "slug": "midnight-cinema",
                "name": "深夜私人影院",
                "description": "加密挂载的私人 4K 媒体库，仅对持有授权的会话可见。",
                "icon": "🎬",
                "tier": "18+",
                "target_url": "/apps/midnight-cinema",
                "open_in_new_tab": True,
                "status": "active",
                "sort_order": 1,
            },
            {
                "slug": "secret-archive",
                "name": "绝密离线归档仓",
                "description": "受限访问的加密文档与私人收藏库，未授权访问直接返回 404。",
                "icon": "🗄️",
                "tier": "18+",
                "target_url": "/apps/secret-archive",
                "open_in_new_tab": True,
                "status": "offline",
                "sort_order": 2,
            },
        ]

        for s_data in services_data:
            existing_svc = (
                db.query(Service).filter(Service.slug == s_data["slug"]).first()
            )
            if not existing_svc:
                db.add(
                    Service(
                        **s_data,
                        is_enabled=(s_data["status"] == "active"),
                    )
                )
            else:
                # Update default sample icons/descriptions/statuses if untouched
                existing_svc.icon = s_data["icon"]
                existing_svc.name = s_data["name"]
                existing_svc.description = s_data["description"]
                if getattr(existing_svc, "status", None) in (None, "active"):
                    existing_svc.status = s_data["status"]
                    existing_svc.is_enabled = s_data["status"] == "active"

        # 3. Seed Activation Codes
        codes_data = [
            {
                "code": "PASS-18-UNLIMITED",
                "description": "无限次全功能通行码（解锁全部隐藏分区）",
                "grant_tier": "*",
                "grant_service_slug": None,
                "max_uses": -1,
            },
            {
                "code": "ONLY-18-INFINITE",
                "description": "无限次私密专区激活码（单独解锁最高私密分区）",
                "grant_tier": "18+",
                "grant_service_slug": None,
                "max_uses": -1,
            },
            {
                "code": "PASS-15-LIMIT3",
                "description": "限用 3 次：解锁日常、云端与核心网络分区",
                "grant_tier": "<=15+",
                "grant_service_slug": None,
                "max_uses": 3,
            },
            {
                "code": "PASS-12-ONETIME",
                "description": "单次激活码：解锁日常共享与云端存储分区（用完即止）",
                "grant_tier": "<=12+",
                "grant_service_slug": None,
                "max_uses": 1,
            },
            {
                "code": "PASS-APP-SECRET",
                "description": "限用 5 次：仅单独解锁『深夜私人影院』单个应用",
                "grant_tier": None,
                "grant_service_slug": "midnight-cinema",
                "max_uses": 5,
            },
        ]

        for c_data in codes_data:
            existing_code = (
                db.query(ActivationCode)
                .filter(ActivationCode.code == c_data["code"])
                .first()
            )
            if not existing_code:
                db.add(ActivationCode(**c_data))

        db.commit()
        print("✅ 数据库结构升级与测试数据同步完成！")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
