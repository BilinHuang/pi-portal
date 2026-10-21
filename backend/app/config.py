"""Global configuration for Pi Stealth Dashboard."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "dashboard.db"
FRONTEND_DIR = BASE_DIR / "frontend"

SECRET_KEY = os.getenv(
    "DASHBOARD_SECRET_KEY",
    "pi5-stealth-dashboard-secret-key-2026-change-in-production",
)

SESSION_COOKIE_NAME = "pi_dash_session"
GUEST_COOKIE_NAME = "pi_dash_guest"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

# Internal permission tiers (kept internal; never explicitly shown as age ratings on UI)
ALL_TIERS = ["6+", "9+", "12+", "15+", "18+"]

# Tiers visible to everyone by default (public visitor baseline)
DEFAULT_PUBLIC_TIERS = ["6+"]

# Neutral category titles (no explicit age tags displayed)
TIER_META = {
    "6+": {
        "label": "公共基础服务",
        "subtitle": "日常工具与公开节点状态",
    },
    "9+": {
        "label": "家庭娱乐与共享",
        "subtitle": "局域网共享媒体与生活工具",
    },
    "12+": {
        "label": "云端存储与开发",
        "subtitle": "个人相册、代码托管与跨端同步",
    },
    "15+": {
        "label": "核心网络与安全",
        "subtitle": "密钥管理、内网穿透与高敏工具",
    },
    "18+": {
        "label": "私密归档专区",
        "subtitle": "受限访问与私人加密馆藏",
    },
}

# Service operational status metadata (replaces the old age badge on card top-right)
SERVICE_STATUS_META = {
    "active": {
        "label": "运行中",
        "badge_class": "status-tag-active",
        "is_available": True,
    },
    "disabled": {
        "label": "已关闭",
        "badge_class": "status-tag-disabled",
        "is_available": False,
    },
    "offline": {
        "label": "暂不可用",
        "badge_class": "status-tag-offline",
        "is_available": False,
    },
    "wip": {
        "label": "待开发",
        "badge_class": "status-tag-wip",
        "is_available": False,
    },
}

DEFAULT_TIMEZONES = [
    {"id": "shanghai", "city": "上海", "country": "CN", "tz": "Asia/Shanghai"},
    {"id": "tokyo", "city": "东京", "country": "JP", "tz": "Asia/Tokyo"},
    {"id": "sydney", "city": "悉尼", "country": "AU", "tz": "Australia/Sydney"},
]
