"""Database seeding script for Pi Stealth Portal.

Creates or updates:
- Default users: `admin` (`admin123`) and `guest_user` (`user123`)
- Pre-configured services with clean, concise names and descriptions
- Pre-configured activation codes
- Default sample announcements & notes for 'pi-status-note'
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.database import Base, SessionLocal, engine, ensure_schema_migrations
from backend.app.models import ActivationCode, Note, Service, User
from backend.app.security import hash_password


def seed():
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations()
    db = SessionLocal()

    try:
        # 1. Seed Users
        users_data = [
            ("admin", "admin123", "admin", "管理员"),
            ("guest_user", "user123", "user", "测试"),
        ]
        for username, pwd, role, tag in users_data:
            existing_user = db.query(User).filter(User.username == username).first()
            if not existing_user:
                db.add(
                    User(
                        username=username,
                        password_hash=hash_password(pwd),
                        password_plain=pwd,
                        role=role,
                        user_tag=tag,
                    )
                )
            else:
                if not getattr(existing_user, "password_plain", None):
                    existing_user.password_plain = pwd
                if getattr(existing_user, "user_tag", "普通") in (None, "", "普通"):
                    existing_user.user_tag = tag

        # 2. Seed Services across internal tiers
        services_data = [
            {
                "slug": "pi-status-note",
                "name": "公告与便签",
                "description": "运行公告、备忘录与常用命令速记。",
                "icon": "📋",
                "tier": "6+",
                "target_url": "/apps/pi-status-note",
                "open_in_new_tab": False,
                "status": "active",
                "sort_order": 1,
            },
            {
                "slug": "speedtest-node",
                "name": "连接测速",
                "description": "服务器时钟偏差、往返延迟与上下行速率。",
                "icon": "🚀",
                "tier": "6+",
                "target_url": "/apps/speedtest-node",
                "open_in_new_tab": False,
                "status": "active",
                "sort_order": 2,
            },
            {
                "slug": "mac-ai-assistant",
                "name": "Mac 本地大模型",
                "description": "挂载于 Mac 节点的 Ollama 本地推理服务。",
                "icon": "🧠",
                "tier": "6+",
                "target_url": "/apps/mac-ai-assistant",
                "open_in_new_tab": False,
                "status": "offline",
                "sort_order": 3,
            },
            {
                "slug": "smart-home-hub",
                "name": "智能家居",
                "description": "传感器监控与自动化规则编排。",
                "icon": "🏡",
                "tier": "6+",
                "target_url": "/apps/smart-home-hub",
                "open_in_new_tab": False,
                "status": "wip",
                "sort_order": 4,
            },
            {
                "slug": "family-recipes",
                "name": "家庭菜谱",
                "description": "日常采购清单与菜谱归档。",
                "icon": "🍲",
                "tier": "9+",
                "target_url": "/apps/family-recipes",
                "open_in_new_tab": False,
                "status": "active",
                "sort_order": 1,
            },
            {
                "slug": "music-stream",
                "name": "音乐串流",
                "description": "Navidrome 无损音乐服务器。",
                "icon": "🎵",
                "tier": "9+",
                "target_url": "/apps/music-stream",
                "open_in_new_tab": True,
                "status": "disabled",
                "sort_order": 2,
            },
            {
                "slug": "immich-photos",
                "name": "私有相册",
                "description": "手机照片自动备份与时间线检索。",
                "icon": "🖼️",
                "tier": "12+",
                "target_url": "/apps/immich-photos",
                "open_in_new_tab": True,
                "status": "active",
                "sort_order": 1,
            },
            {
                "slug": "mac-video-transcode",
                "name": "Mac 媒体转码",
                "description": "调用 Mac 硬件编码器处理视频转码任务。",
                "icon": "🎞️",
                "tier": "12+",
                "target_url": "/apps/mac-video-transcode",
                "open_in_new_tab": True,
                "status": "offline",
                "sort_order": 2,
            },
            {
                "slug": "gitea-git",
                "name": "代码仓库",
                "description": "轻量 Git 代码托管与 CI 节点。",
                "icon": "🦊",
                "tier": "12+",
                "target_url": "/apps/gitea-git",
                "open_in_new_tab": True,
                "status": "wip",
                "sort_order": 3,
            },
            {
                "slug": "vaultwarden",
                "name": "密码金库",
                "description": "个人密码管理与双重验证。",
                "icon": "🔐",
                "tier": "15+",
                "target_url": "/apps/vaultwarden",
                "open_in_new_tab": True,
                "status": "active",
                "sort_order": 1,
            },
            {
                "slug": "wireguard-panel",
                "name": "网络隧道",
                "description": "Cloudflare 隧道与防火墙配置。",
                "icon": "🛡️",
                "tier": "15+",
                "target_url": "/apps/wireguard-panel",
                "open_in_new_tab": True,
                "status": "disabled",
                "sort_order": 2,
            },
            {
                "slug": "midnight-cinema",
                "name": "私人影院",
                "description": "私人 4K 流媒体库。",
                "icon": "🎬",
                "tier": "18+",
                "target_url": "/apps/midnight-cinema",
                "open_in_new_tab": True,
                "status": "active",
                "sort_order": 1,
            },
            {
                "slug": "secret-archive",
                "name": "私密归档",
                "description": "受限访问的加密文档与离线归档仓。",
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
                existing_svc.icon = s_data["icon"]
                existing_svc.name = s_data["name"]
                existing_svc.description = s_data["description"]
                existing_svc.status = s_data["status"]
                existing_svc.is_enabled = s_data["status"] == "active"

        # 3. Seed Activation Codes
        codes_data = [
            {
                "code": "PASS-18-UNLIMITED",
                "description": "全功能通行码（解锁全部分区）",
                "grant_tier": "*",
                "grant_service_slug": None,
                "max_uses": -1,
            },
            {
                "code": "ONLY-18-INFINITE",
                "description": "私密专区激活码",
                "grant_tier": "18+",
                "grant_service_slug": None,
                "max_uses": -1,
            },
            {
                "code": "PASS-15-LIMIT3",
                "description": "限用 3 次：日常、云端与核心网络",
                "grant_tier": "<=15+",
                "grant_service_slug": None,
                "max_uses": 3,
            },
            {
                "code": "PASS-12-ONETIME",
                "description": "单次激活码：日常与云端开发",
                "grant_tier": "<=12+",
                "grant_service_slug": None,
                "max_uses": 1,
            },
            {
                "code": "PASS-APP-SECRET",
                "description": "限用 5 次：仅解锁『私人影院』",
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

        # 4. Seed sample Notes
        if db.query(Note).count() == 0:
            sample_notes = [
                Note(
                    title="树莓派节点运行说明",
                    content="节点运行于 SQLite WAL 模式与 Systemd 守护进程。\n公网访问近期将切换至 Cloudflare Tunnel。",
                    category="bulletin",
                    priority="info",
                    is_pinned=True,
                    author="admin",
                ),
                Note(
                    title="常用运维命令",
                    content="sudo systemctl status pi-dashboard\ncd ~/Documents/WebApp/portal && git pull",
                    category="code",
                    priority="normal",
                    is_pinned=True,
                    author="admin",
                ),
                Note(
                    title="近期待办",
                    content="1. 配置 Cloudflare Tunnel 域名绑定\n2. 调试内网测速模块稳定性",
                    category="todo",
                    priority="normal",
                    is_pinned=False,
                    author="admin",
                ),
            ]
            db.add_all(sample_notes)

        db.commit()
        print("✅ 数据同步与文本清洗完成！")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
