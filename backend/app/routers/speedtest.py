"""Server Time Synchronization, Latency (Ping/Jitter), and In-Memory Bandwidth Speedtest Router.

Designed for Raspberry Pi 5 + TF Card:
- All download and upload buffers operate strictly in RAM (zero disk/TF card read/write).
- Protected by the same service permission & operational status check as 'speedtest-node'.
"""
from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import CurrentIdentity, can_launch_service, get_current_identity
from ..models import Service

router = APIRouter(prefix="/api/speedtest", tags=["speedtest"])

# Pre-allocated 256 KB in-memory chunk to stream downloads with near-zero RAM & zero disk I/O
_CHUNK_SIZE = 256 * 1024
_MEM_CHUNK = b"P" * _CHUNK_SIZE


def _require_speedtest_available(
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
) -> CurrentIdentity:
    """Ensure the caller has permission and the speedtest-node service is currently active."""
    service = db.query(Service).filter(Service.slug == "speedtest-node").first()
    if service and not can_launch_service(identity, service):
        raise HTTPException(status_code=404, detail="Not Found")
    return identity


@router.get("/ping")
def ping_and_server_time(
    response: Response,
    identity: CurrentIdentity = Depends(_require_speedtest_available),
):
    """Return high-precision server timestamp (ms) for NTP-style RTT & clock offset calculation."""
    now_ms = time.time() * 1000.0
    now_utc = datetime.now(timezone.utc)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return {
        "server_ts_ms": round(now_ms, 3),
        "server_utc_iso": now_utc.isoformat(),
        "client_ip": identity.client_ip,
    }


@router.get("/download")
def speedtest_download(
    size_mb: int = Query(default=4, ge=1, le=32),
    identity: CurrentIdentity = Depends(_require_speedtest_available),
):
    """Stream an in-memory binary payload of `size_mb` MB (zero TF card I/O)."""
    total_bytes = size_mb * 1024 * 1024
    chunks_count = total_bytes // _CHUNK_SIZE

    def _stream() -> Iterator[bytes]:
        for _ in range(chunks_count):
            yield _MEM_CHUNK

    headers = {
        "Content-Length": str(total_bytes),
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(
        _stream(),
        media_type="application/octet-stream",
        headers=headers,
    )


@router.post("/upload")
async def speedtest_upload(
    request: Request,
    identity: CurrentIdentity = Depends(_require_speedtest_available),
):
    """Consume uploaded bytes in memory and return transfer metrics (zero TF card write)."""
    t0 = time.perf_counter()
    total_received = 0
    max_bytes = 32 * 1024 * 1024  # Cap at 32 MB for safety

    async for chunk in request.stream():
        total_received += len(chunk)
        if total_received > max_bytes:
            raise HTTPException(status_code=413, detail="Payload too large")

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "received_bytes": total_received,
        "server_receive_ms": round(elapsed_ms, 2),
        "server_ts_ms": round(time.time() * 1000.0, 3),
    }
