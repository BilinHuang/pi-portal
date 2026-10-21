"""FastAPI Main Application Entrypoint for Pi Stealth Portal."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIR
from .database import Base, engine, ensure_schema_migrations
from .routers import admin, ai, auth, notes, services, speedtest, widgets

# Create tables and apply schema migrations automatically on startup
Base.metadata.create_all(bind=engine)
ensure_schema_migrations()

app = FastAPI(
    title="Pi Stealth Portal",
    version="1.4.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(auth.router)
app.include_router(services.router)
app.include_router(speedtest.router)
app.include_router(notes.router)
app.include_router(widgets.router)
app.include_router(ai.router)
app.include_router(admin.router)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


NOT_FOUND_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>404 Not Found</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #0b0f17;
      color: #e2e8f0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .box {
      text-align: center;
      padding: 2.5rem;
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 16px;
      background: rgba(17, 24, 39, 0.7);
      max-width: 420px;
    }
    .code {
      font-size: 4rem;
      font-weight: 800;
      letter-spacing: -0.04em;
      color: #38bdf8;
      margin: 0;
    }
    .msg {
      margin: 0.75rem 0 1.5rem;
      color: #94a3b8;
      font-size: 0.95rem;
    }
    a {
      display: inline-block;
      padding: 0.55rem 1.2rem;
      border-radius: 8px;
      background: rgba(56, 189, 248, 0.15);
      color: #38bdf8;
      text-decoration: none;
      font-size: 0.9rem;
      border: 1px solid rgba(56, 189, 248, 0.3);
    }
    a:hover {
      background: rgba(56, 189, 248, 0.25);
    }
  </style>
</head>
<body>
  <div class="box">
    <h1 class="code">404</h1>
    <p class="msg">The requested URL was not found on this server.</p>
    <a href="/">返回首页</a>
  </div>
</body>
</html>"""


@app.exception_handler(404)
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Ensure all 404 errors (real or stealth-masked) look completely identical."""
    if exc.status_code == 404:
        accept = request.headers.get("accept", "")
        if "application/json" in accept or request.url.path.startswith("/api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return HTMLResponse(content=NOT_FOUND_HTML, status_code=404)

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.get("/", include_in_schema=False)
def serve_dashboard_index():
    """Serve the main Dashboard SPA page."""
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("Dashboard frontend not found.", status_code=404)
    return FileResponse(str(index_file))


@app.get("/{full_path:path}", include_in_schema=False)
def catch_all_404(request: Request, full_path: str):
    """Any unmatched route falls through to the exact same 404 handler."""
    accept = request.headers.get("accept", "")
    if "application/json" in accept or full_path.startswith("api/"):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    return HTMLResponse(content=NOT_FOUND_HTML, status_code=404)
