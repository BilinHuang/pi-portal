"""Global configuration for Pi Stealth Portal."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "dashboard.db"
FRONTEND_DIR = BASE_DIR / "frontend"

# Gemini API Keys directory (supports Gemini1.key, gemini2.key, *.key)
KEYS_DIR = Path(os.getenv("PORTAL_KEYS_DIR", str(BASE_DIR / "keys")))

# Local 3-Tier Novel Reader root directory (Epoch -> Story/Meta -> Chapters)
NOVELS_DIR = Path(os.getenv("PORTAL_NOVELS_DIR", str(BASE_DIR / "novels")))

# Story Studio generated outputs directory
STUDIO_OUTPUT_DIR = DATA_DIR / "studio_outputs"
STUDIO_INPUT_DIR = DATA_DIR / "studio_inputs"

SECRET_KEY = os.getenv(
    "DASHBOARD_SECRET_KEY",
    "pi5-stealth-dashboard-secret-key-2026-change-in-production",
)

SESSION_COOKIE_NAME = "pi_dash_session"
GUEST_COOKIE_NAME = "pi_dash_guest"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

# Internal permission tiers
ALL_TIERS = ["6+", "9+", "12+", "15+", "18+"]

# Public baseline tiers
DEFAULT_PUBLIC_TIERS = ["6+"]

# Category labels and subtitles
TIER_META = {
    "6+": {
        "label": "公共基础",
        "subtitle": "基础工具与节点状态",
    },
    "9+": {
        "label": "家庭共享",
        "subtitle": "共享媒体与生活工具",
    },
    "12+": {
        "label": "云端开发",
        "subtitle": "个人相册与代码仓库",
    },
    "15+": {
        "label": "核心网络",
        "subtitle": "密码金库与网络隧道",
    },
    "18+": {
        "label": "私密专区",
        "subtitle": "受限访问与私人归档",
    },
}

# Service operational status metadata
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

# Registration Security Questions
REGISTRATION_IDENTITY_QUESTIONS = {
    "junior_high": {
        "prompt": "我初中是在哪所学校？",
        "answers": ["七宝二中", "七宝第二中学", "上海市七宝第二中学"],
        "user_tag": "初中",
        "grant_tier": "6+",
    },
    "senior_high": {
        "prompt": "我高中是在哪所学校？",
        "answers": [
            "交附嘉分",
            "交嘉",
            "绞架",
            "交大附中嘉定分校",
            "上海交通大学附属中学嘉定分校",
        ],
        "user_tag": "高中",
        "grant_tier": "<=9+",
    },
    "university": {
        "prompt": "我大学是在哪所学校？",
        "answers": [
            "合工大",
            "肥工",
            "hfut",
            "合肥工业大学",
            "新南威尔士大学",
            "unsw",
            "新南",
            "新南威尔士",
        ],
        "user_tag": "大学",
        "grant_tier": "<=12+",
    },
    "nickname": {
        "prompt": "家里人或发小叫我什么小名？",
        "answers": ["菜菜"],
        "user_tag": "家人",
        "grant_tier": "<=15+",
    },
}

REGISTRATION_LIFE_QUESTIONS = {
    "game": {
        "prompt": "说出一款我常玩的游戏",
        "answers": [
            "都市天际线",
            "都市天际线1",
            "都市天际线2",
            "天际线",
            "citiesskylines",
            "csl",
            "原神",
            "genshin",
            "genshinimpact",
            "明日方舟",
            "方舟",
            "粥",
            "arknights",
            "狂热运输2",
            "狂热运输",
            "transportfever2",
            "transportfever",
        ],
    },
    "sport": {
        "prompt": "我常做什么球类运动？",
        "answers": ["羽毛球", "打羽毛球", "badminton"],
    },
}
