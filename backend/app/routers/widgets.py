"""Dashboard Widgets Router: Multi-Timezone World Clock & Cross-Platform System Telemetry."""
from __future__ import annotations

from datetime import datetime, timezone
import os
import platform
import time
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter
import psutil

from ..config import DEFAULT_TIMEZONES

router = APIRouter(prefix="/api/widgets", tags=["widgets"])

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


@router.get("/timezones")
def get_world_clocks():
    """Return current time across configured default cities (Shanghai, Tokyo, Sydney)."""
    now_utc = datetime.now(timezone.utc)
    shanghai_dt = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    shanghai_offset_hours = shanghai_dt.utcoffset().total_seconds() / 3600.0

    clocks = []
    for item in DEFAULT_TIMEZONES:
        tz = ZoneInfo(item["tz"])
        local_dt = now_utc.astimezone(tz)
        offset_sec = local_dt.utcoffset().total_seconds()
        offset_hours = offset_sec / 3600.0
        diff_vs_shanghai = offset_hours - shanghai_offset_hours

        sign = "+" if offset_hours >= 0 else ""
        offset_label = (
            f"UTC{sign}{int(offset_hours)}"
            if offset_hours.is_integer()
            else f"UTC{sign}{offset_hours:.1f}"
        )

        if diff_vs_shanghai == 0:
            diff_label = "基准时区"
        elif diff_vs_shanghai > 0:
            diff_label = f"比上海快 {int(diff_vs_shanghai) if diff_vs_shanghai.is_integer() else diff_vs_shanghai} 小时"
        else:
            diff_label = f"比上海慢 {int(abs(diff_vs_shanghai)) if diff_vs_shanghai.is_integer() else abs(diff_vs_shanghai)} 小时"

        clocks.append(
            {
                "id": item["id"],
                "city": item["city"],
                "country": item["country"],
                "timezone": item["tz"],
                "time_24h": local_dt.strftime("%H:%M:%S"),
                "date": local_dt.strftime("%Y-%m-%d"),
                "weekday": WEEKDAY_CN[local_dt.weekday()],
                "utc_offset": offset_label,
                "diff_label": diff_label,
                "is_daytime": 6 <= local_dt.hour < 19,
            }
        )

    return {
        "server_utc": now_utc.isoformat(),
        "clocks": clocks,
    }


def _read_pi_temperature() -> Optional[float]:
    """Read CPU temperature on Raspberry Pi 5 (/sys/class/thermal/thermal_zone0/temp)."""
    thermal_path = "/sys/class/thermal/thermal_zone0/temp"
    if os.path.exists(thermal_path):
        try:
            with open(thermal_path, "r", encoding="utf-8") as f:
                return round(int(f.read().strip()) / 1000.0, 1)
        except Exception:
            return None
    return None


@router.get("/system")
def get_system_status():
    """Cross-platform hardware status abstraction (works on both macOS Dev and Raspberry Pi 5)."""
    sys_name = platform.system()
    machine = platform.machine()
    is_raspberry_pi = False

    model_name = f"{sys_name} ({machine})"
    if os.path.exists("/proc/device-tree/model"):
        try:
            with open("/proc/device-tree/model", "r", encoding="utf-8") as f:
                model_name = f.read().strip("\x00").strip()
                is_raspberry_pi = "Raspberry Pi" in model_name
        except Exception:
            pass

    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    cpu_pct = psutil.cpu_percent(interval=None)
    uptime_seconds = int(time.time() - psutil.boot_time())

    temp_c = _read_pi_temperature()

    return {
        "platform": model_name,
        "is_raspberry_pi": is_raspberry_pi,
        "cpu_percent": round(cpu_pct, 1),
        "cpu_cores": psutil.cpu_count(logical=True) or 4,
        "memory": {
            "total_gb": round(vm.total / (1024**3), 2),
            "used_gb": round((vm.total - vm.available) / (1024**3), 2),
            "percent": round(vm.percent, 1),
        },
        "storage": {
            "total_gb": round(disk.total / (1024**3), 1),
            "used_gb": round(disk.used / (1024**3), 1),
            "percent": round(disk.percent, 1),
        },
        "temperature_c": temp_c,
        "uptime_hours": round(uptime_seconds / 3600.0, 1),
    }
