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


def _render_notes_app(service: Service, identity: CurrentIdentity) -> str:
    """Render the interactive Node Announcements & Scratchpad Notes web application."""
    visitor = identity.user.username if identity.user else "访客 (Guest)"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{service.name} — Pi 5 Portal</title>
  <link rel="stylesheet" href="/static/css/style.css" />
  <style>
    .notes-wrap {{
      max-width: 980px;
      width: 100%;
      margin: 2rem auto;
      padding: 0 1.25rem 3rem;
    }}
    .notes-hero {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      padding: 1.35rem 1.5rem;
      margin-bottom: 1.25rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 1rem;
    }}
    .notes-toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-bottom: 1.25rem;
    }}
    .filter-tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      background: rgba(15, 23, 42, 0.75);
      padding: 0.28rem;
      border-radius: 10px;
      border: 1px solid var(--border-subtle);
    }}
    .tab-btn {{
      border: none;
      background: transparent;
      color: var(--text-muted);
      font-size: 0.82rem;
      font-weight: 600;
      padding: 0.4rem 0.85rem;
      border-radius: 7px;
      cursor: pointer;
      transition: all 0.15s ease;
    }}
    .tab-btn:hover {{
      color: var(--text-main);
    }}
    .tab-btn.active {{
      background: rgba(56, 189, 248, 0.18);
      color: #38bdf8;
      border: 1px solid rgba(56, 189, 248, 0.32);
    }}
    .search-box {{
      background: rgba(15, 23, 42, 0.85);
      border: 1px solid var(--border-subtle);
      border-radius: 9px;
      padding: 0.45rem 0.85rem;
      color: var(--text-main);
      font-size: 0.84rem;
      min-width: 210px;
      outline: none;
    }}
    .search-box:focus {{
      border-color: var(--accent);
    }}
    .note-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(295px, 1fr));
      gap: 1rem;
    }}
    .note-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 14px;
      padding: 1.15rem 1.25rem;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: all 0.2s ease;
    }}
    .note-card.pinned {{
      border-color: rgba(56, 189, 248, 0.42);
      background: linear-gradient(180deg, rgba(14, 165, 233, 0.08), rgba(17, 24, 39, 0.78));
    }}
    .note-card:hover {{
      border-color: rgba(56, 189, 248, 0.32);
      transform: translateY(-2px);
    }}
    .note-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 0.6rem;
      margin-bottom: 0.55rem;
    }}
    .note-title {{
      font-size: 0.98rem;
      font-weight: 700;
      color: #f8fafc;
      line-height: 1.35;
    }}
    .note-badge {{
      font-size: 0.7rem;
      font-weight: 700;
      padding: 0.14rem 0.5rem;
      border-radius: 6px;
      white-space: nowrap;
      flex-shrink: 0;
    }}
    .badge-bulletin {{
      background: rgba(244, 63, 94, 0.16);
      color: #fb7185;
      border: 1px solid rgba(244, 63, 94, 0.35);
    }}
    .badge-memo {{
      background: rgba(56, 189, 248, 0.14);
      color: #38bdf8;
      border: 1px solid rgba(56, 189, 248, 0.3);
    }}
    .badge-todo {{
      background: rgba(16, 185, 129, 0.14);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }}
    .badge-code {{
      background: rgba(168, 85, 247, 0.16);
      color: #c084fc;
      border: 1px solid rgba(168, 85, 247, 0.32);
    }}
    .note-body {{
      font-size: 0.85rem;
      color: #cbd5e1;
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0.35rem 0 1rem;
      flex: 1;
      line-height: 1.55;
    }}
    .note-body.code-font {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      background: rgba(0, 0, 0, 0.35);
      padding: 0.65rem 0.75rem;
      border-radius: 8px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      font-size: 0.8rem;
    }}
    .note-footer {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.74rem;
      color: var(--text-muted);
      border-top: 1px solid rgba(255, 255, 255, 0.06);
      padding-top: 0.65rem;
      gap: 0.5rem;
      flex-wrap: wrap;
    }}
    .note-actions {{
      display: flex;
      gap: 0.35rem;
    }}
    .btn-action {{
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      border-radius: 6px;
      padding: 0.22rem 0.52rem;
      font-size: 0.73rem;
      cursor: pointer;
      transition: all 0.15s ease;
    }}
    .btn-action:hover {{
      color: #fff;
      border-color: rgba(56, 189, 248, 0.35);
      background: rgba(56, 189, 248, 0.12);
    }}
  </style>
</head>
<body>
  <div class="notes-wrap">
    <div class="subapp-header">
      <a href="/" class="btn btn-ghost">← 返回控制台</a>
      <span class="status-tag status-tag-active">运行中 · SQLite WAL 持久化</span>
    </div>

    <div class="notes-hero">
      <div style="display:flex;align-items:center;gap:0.9rem;">
        <div class="subapp-icon" style="margin:0;">{service.icon}</div>
        <div>
          <h1 style="font-size:1.3rem;">{service.name}</h1>
          <p class="subapp-desc" style="margin:0.15rem 0 0;">
            用于记录树莓派节点维护公告、局域网备忘速记、待办事项与常用终端命令（当前身份: {visitor}）。
          </p>
        </div>
      </div>
      <button class="btn btn-accent" onclick="openNoteModal()">+ 新建便签 / 公告</button>
    </div>

    <div class="notes-toolbar">
      <div class="filter-tabs">
        <button class="tab-btn active" onclick="setFilter('all', this)">全部</button>
        <button class="tab-btn" onclick="setFilter('bulletin', this)">📢 节点公告</button>
        <button class="tab-btn" onclick="setFilter('memo', this)">📝 备忘速记</button>
        <button class="tab-btn" onclick="setFilter('todo', this)">✅ 待办清单</button>
        <button class="tab-btn" onclick="setFilter('code', this)">💻 常用命令</button>
      </div>
      <input
        type="search"
        id="search-input"
        class="search-box"
        placeholder="🔍 搜索标题或内容..."
        oninput="loadNotes()"
      />
    </div>

    <div class="note-grid" id="note-grid">正在加载便签...</div>
  </div>

  <!-- Create / Edit Note Modal -->
  <div class="modal-backdrop hidden" id="modal-note">
    <div class="modal-card">
      <div class="modal-header">
        <h3 id="modal-note-heading">新建便签 / 公告</h3>
        <button class="modal-close" onclick="closeNoteModal()">✕</button>
      </div>
      <form id="form-note">
        <input type="hidden" id="note-id" value="" />
        <div class="form-group">
          <label for="note-cat">分类类型</label>
          <select id="note-cat" style="width:100%;background:rgba(15,23,42,0.9);border:1px solid rgba(255,255,255,0.14);border-radius:8px;padding:0.55rem 0.75rem;color:#f1f5f9;font-size:0.88rem;">
            <option value="bulletin">📢 节点公告 (Bulletin)</option>
            <option value="memo" selected>📝 备忘速记 (Memo)</option>
            <option value="todo">✅ 待办事项 (Todo)</option>
            <option value="code">💻 常用命令 / 配置 (Code)</option>
          </select>
        </div>
        <div class="form-group">
          <label for="note-title">标题</label>
          <input type="text" id="note-title" placeholder="例如: 树莓派公网维护通知 / 常用重启命令" required />
        </div>
        <div class="form-group">
          <label for="note-content">正文内容</label>
          <textarea
            id="note-content"
            rows="5"
            style="width:100%;background:rgba(15,23,42,0.9);border:1px solid rgba(255,255,255,0.14);border-radius:8px;padding:0.65rem 0.75rem;color:#f1f5f9;font-size:0.88rem;line-height:1.5;resize:vertical;"
            placeholder="输入公告正文、备忘笔记或终端命令..."
            required
          ></textarea>
        </div>
        <div class="form-group" style="display:flex;align-items:center;gap:0.5rem;">
          <input type="checkbox" id="note-pinned" style="width:auto;" />
          <label for="note-pinned" style="margin:0;cursor:pointer;">📌 置顶显示在最前面</label>
        </div>
        <div class="modal-actions">
          <button type="button" class="btn btn-ghost" onclick="closeNoteModal()">取消</button>
          <button type="submit" class="btn btn-accent">保存发布</button>
        </div>
      </form>
    </div>
  </div>

  <div class="toast hidden" id="toast"></div>

  <script>
    let currentFilter = "all";
    let cachedNotes = [];

    function showToast(msg) {{
      const t = document.getElementById("toast");
      t.textContent = msg;
      t.classList.remove("hidden");
      clearTimeout(window.__noteToast);
      window.__noteToast = setTimeout(() => t.classList.add("hidden"), 2600);
    }}

    function escapeHtml(str) {{
      return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }}

    async function loadNotes() {{
      const q = document.getElementById("search-input")?.value.trim() || "";
      const url = `/api/notes?category=${{encodeURIComponent(currentFilter)}}&q=${{encodeURIComponent(q)}}`;
      const res = await fetch(url);
      cachedNotes = await res.json();
      const grid = document.getElementById("note-grid");

      if (!Array.isArray(cachedNotes) || cachedNotes.length === 0) {{
        grid.innerHTML = '<div style="color:var(--text-muted);grid-column:1/-1;text-align:center;padding:3rem;background:rgba(17,24,39,0.4);border-radius:14px;border:1px dashed rgba(255,255,255,0.08);">暂无匹配的公告或便签，点击右上角「+ 新建便签 / 公告」添加第一条记录</div>';
        return;
      }}

      const catMap = {{
        bulletin: {{ label: "📢 节点公告", cls: "badge-bulletin" }},
        memo: {{ label: "📝 备忘速记", cls: "badge-memo" }},
        todo: {{ label: "✅ 待办事项", cls: "badge-todo" }},
        code: {{ label: "💻 常用命令", cls: "badge-code" }},
      }};

      grid.innerHTML = cachedNotes
        .map((n) => {{
          const c = catMap[n.category] || catMap.memo;
          const pinIcon = n.is_pinned ? "📌 " : "";
          const dt = n.updated_at
            ? new Date(n.updated_at).toLocaleString("zh-CN", {{
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
              }})
            : "";
          const bodyCls = n.category === "code" ? "note-body code-font" : "note-body";
          return `
            <div class="note-card ${{n.is_pinned ? "pinned" : ""}}">
              <div>
                <div class="note-header">
                  <span class="note-title">${{pinIcon}}${{escapeHtml(n.title)}}</span>
                  <span class="note-badge ${{c.cls}}">${{c.label}}</span>
                </div>
                <div class="${{bodyCls}}">${{escapeHtml(n.content)}}</div>
              </div>
              <div class="note-footer">
                <span>👤 ${{escapeHtml(n.author)}} · ${{dt}}</span>
                <div class="note-actions">
                  <button class="btn-action" onclick="copyNote(${{n.id}})">📋 复制</button>
                  <button class="btn-action" onclick="editNote(${{n.id}})">编辑</button>
                  <button class="btn-action" onclick="togglePin(${{n.id}})">${{n.is_pinned ? "取消置顶" : "置顶"}}</button>
                  <button class="btn-action" style="color:#fb7185;" onclick="deleteNote(${{n.id}})">删除</button>
                </div>
              </div>
            </div>
          `;
        }})
        .join("");
    }}

    function copyNote(id) {{
      const item = cachedNotes.find((x) => x.id === id);
      if (!item) return;
      navigator.clipboard.writeText(item.content);
      showToast("已复制内容到剪贴板");
    }}

    function openNoteModal() {{
      document.getElementById("note-id").value = "";
      document.getElementById("modal-note-heading").textContent = "新建便签 / 公告";
      document.getElementById("form-note").reset();
      document.getElementById("modal-note").classList.remove("hidden");
      document.getElementById("note-title").focus();
    }}

    function editNote(id) {{
      const item = cachedNotes.find((x) => x.id === id);
      if (!item) return;
      document.getElementById("note-id").value = String(item.id);
      document.getElementById("modal-note-heading").textContent = "编辑便签 / 公告";
      document.getElementById("note-cat").value = item.category;
      document.getElementById("note-title").value = item.title;
      document.getElementById("note-content").value = item.content;
      document.getElementById("note-pinned").checked = Boolean(item.is_pinned);
      document.getElementById("modal-note").classList.remove("hidden");
    }}

    function closeNoteModal() {{
      document.getElementById("modal-note").classList.add("hidden");
    }}

    async function togglePin(id) {{
      await fetch(`/api/notes/${{id}}/pin`, {{ method: "PATCH" }});
      await loadNotes();
    }}

    async function deleteNote(id) {{
      await fetch(`/api/notes/${{id}}`, {{ method: "DELETE" }});
      showToast("便签已删除");
      await loadNotes();
    }}

    function setFilter(cat, btn) {{
      currentFilter = cat;
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      loadNotes();
    }}

    document.getElementById("form-note").addEventListener("submit", async (e) => {{
      e.preventDefault();
      const noteId = document.getElementById("note-id").value.trim();
      const payload = {{
        title: document.getElementById("note-title").value.trim(),
        content: document.getElementById("note-content").value.trim(),
        category: document.getElementById("note-cat").value,
        is_pinned: document.getElementById("note-pinned").checked,
      }};

      if (noteId) {{
        await fetch(`/api/notes/${{noteId}}`, {{
          method: "PUT",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload),
        }});
        showToast("便签已更新");
      }} else {{
        await fetch("/api/notes", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload),
        }});
        showToast("新便签已发布");
      }}

      closeNoteModal();
      await loadNotes();
    }});

    loadNotes();
  </script>
</body>
</html>"""


def _render_speedtest_app(service: Service, identity: CurrentIdentity) -> str:
    """Render the dedicated Server Time, Latency & Speedtest web app."""
    visitor = (
        identity.user.username if identity.user else "访客会话 (Guest)"
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{service.name} — Pi 5 Node</title>
  <link rel="stylesheet" href="/static/css/style.css" />
  <style>
    .st-wrap {{
      max-width: 820px;
      width: 100%;
      margin: 2rem auto;
      padding: 0 1.25rem;
    }}
    .st-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
      gap: 0.9rem;
      margin: 1.25rem 0;
    }}
    .st-metric {{
      background: rgba(15, 23, 42, 0.75);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 12px;
      padding: 1rem 1.1rem;
    }}
    .st-metric-label {{
      font-size: 0.76rem;
      color: var(--text-muted);
      margin-bottom: 0.35rem;
    }}
    .st-metric-val {{
      font-size: 1.55rem;
      font-weight: 800;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      color: #f8fafc;
    }}
    .st-metric-unit {{
      font-size: 0.8rem;
      font-weight: 500;
      color: #38bdf8;
      margin-left: 0.25rem;
    }}
    .st-metric-sub {{
      font-size: 0.74rem;
      color: var(--text-muted);
      margin-top: 0.25rem;
      font-family: ui-monospace, SFMono-Regular, monospace;
    }}
    .st-controls {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-top: 1.25rem;
      padding-top: 1.1rem;
      border-top: 1px solid rgba(255, 255, 255, 0.08);
    }}
    .st-select {{
      background: #0f172a;
      color: #f1f5f9;
      border: 1px solid rgba(255, 255, 255, 0.16);
      border-radius: 8px;
      padding: 0.48rem 0.75rem;
      font-size: 0.84rem;
    }}
    .st-progress-track {{
      height: 8px;
      background: rgba(255, 255, 255, 0.06);
      border-radius: 999px;
      overflow: hidden;
      margin: 1rem 0 0.5rem;
    }}
    .st-progress-bar {{
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, #38bdf8, #10b981);
      transition: width 0.2s ease;
    }}
    .st-samples {{
      display: flex;
      align-items: flex-end;
      gap: 4px;
      height: 54px;
      padding: 8px 10px;
      background: rgba(0, 0, 0, 0.28);
      border-radius: 10px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      margin-top: 0.75rem;
    }}
    .st-bar {{
      flex: 1;
      background: rgba(56, 189, 248, 0.65);
      border-radius: 3px 3px 0 0;
      min-height: 4px;
      transition: height 0.15s ease;
    }}
    .st-status-line {{
      font-size: 0.82rem;
      color: var(--text-muted);
      display: flex;
      justify-content: space-between;
      margin-top: 0.35rem;
    }}
  </style>
</head>
<body>
  <div class="st-wrap">
    <div class="subapp-header">
      <a href="/" class="btn btn-ghost">← 返回控制台</a>
      <span class="status-tag status-tag-active">运行中 · 纯内存零闪存磨损</span>
    </div>

    <div class="subapp-card">
      <div style="display:flex;align-items:center;gap:0.85rem;margin-bottom:0.4rem;">
        <div class="subapp-icon" style="margin:0;">{service.icon}</div>
        <div>
          <h1 style="font-size:1.35rem;">{service.name}</h1>
          <p class="subapp-desc" style="margin:0.15rem 0 0;">
            测量当前设备 ({identity.client_ip}) 到树莓派服务器的时钟同步偏差、网络往返延迟与上下行吞吐速率。
          </p>
        </div>
      </div>

      <div class="subapp-status-box" style="margin-top:1.1rem;">
        <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:0.5rem;">
          <span><strong>服务器精确时间:</strong> <code id="srv-time-str">--:--:--.---</code></span>
          <span><strong>本机时间:</strong> <code id="loc-time-str">--:--:--.---</code></span>
          <span><strong>时钟偏差 (Offset):</strong> <code id="clock-offset-str">测量中...</code></span>
        </div>
      </div>

      <div class="st-grid">
        <div class="st-metric">
          <div class="st-metric-label">往返延迟 (Ping RTT)</div>
          <div>
            <span class="st-metric-val" id="val-ping">--</span>
            <span class="st-metric-unit">ms</span>
          </div>
          <div class="st-metric-sub" id="sub-ping">Min -- / Max -- ms</div>
        </div>

        <div class="st-metric">
          <div class="st-metric-label">网络抖动 (Jitter)</div>
          <div>
            <span class="st-metric-val" id="val-jitter">--</span>
            <span class="st-metric-unit">ms</span>
          </div>
          <div class="st-metric-sub" id="sub-jitter">连续采样波动率</div>
        </div>

        <div class="st-metric">
          <div class="st-metric-label">下行速度 (Download)</div>
          <div>
            <span class="st-metric-val" id="val-dl">--</span>
            <span class="st-metric-unit">Mbps</span>
          </div>
          <div class="st-metric-sub" id="sub-dl">-- MB/s</div>
        </div>

        <div class="st-metric">
          <div class="st-metric-label">上行速度 (Upload)</div>
          <div>
            <span class="st-metric-val" id="val-ul">--</span>
            <span class="st-metric-unit">Mbps</span>
          </div>
          <div class="st-metric-sub" id="sub-ul">-- MB/s</div>
        </div>
      </div>

      <div style="font-size:0.76rem;color:var(--text-muted);">延迟采样波形 (12 次连续探测)</div>
      <div class="st-samples" id="ping-bars"></div>

      <div class="st-progress-track">
        <div class="st-progress-bar" id="st-progress"></div>
      </div>
      <div class="st-status-line">
        <span id="st-stage-text">准备就绪，点击下方按钮开始完整测试</span>
        <span>访问身份: {visitor}</span>
      </div>

      <div class="st-controls">
        <div style="display:flex;align-items:center;gap:0.5rem;">
          <label for="st-size" style="font-size:0.82rem;color:var(--text-muted);">测速包大小:</label>
          <select id="st-size" class="st-select">
            <option value="2">2 MB (轻量快速)</option>
            <option value="4" selected>4 MB (标准推荐)</option>
            <option value="8">8 MB (局域网高速)</option>
            <option value="16">16 MB (千兆压测)</option>
          </select>
        </div>
        <div style="display:flex;gap:0.6rem;">
          <button type="button" class="btn btn-outline" id="btn-ping-only">仅测延迟与时间</button>
          <button type="button" class="btn btn-accent" id="btn-full-test">🚀 开始完整测速</button>
        </div>
      </div>
    </div>
  </div>

  <script>
    const pingBarsEl = document.getElementById("ping-bars");
    const progressEl = document.getElementById("st-progress");
    const stageTextEl = document.getElementById("st-stage-text");
    let latestOffsetMs = 0;
    let isRunning = false;

    function fmtTimeMs(msEpoch) {{
      const d = new Date(msEpoch);
      const pad = (n, w = 2) => String(n).padStart(w, "0");
      return `${{pad(d.getHours())}}:${{pad(d.getMinutes())}}:${{pad(d.getSeconds())}}.${{pad(d.getMilliseconds(), 3)}}`;
    }}

    setInterval(() => {{
      const now = Date.now();
      document.getElementById("loc-time-str").textContent = fmtTimeMs(now);
      document.getElementById("srv-time-str").textContent = fmtTimeMs(now + latestOffsetMs);
    }}, 80);

    async function runPingPhase(samples = 12) {{
      pingBarsEl.innerHTML = "";
      const rtts = [];
      const offsets = [];

      for (let i = 0; i < samples; i++) {{
        stageTextEl.textContent = `正在测量服务器时间与延迟 (${{i + 1}}/${{samples}})...`;
        progressEl.style.width = `${{Math.round(((i + 1) / samples) * 35)}}%`;

        const t0 = performance.now();
        const wall0 = Date.now();
        const res = await fetch(`/api/speedtest/ping?_=${{wall0}}_${{i}}`, {{ cache: "no-store" }});
        const data = await res.json();
        const t2 = performance.now();
        const wall2 = Date.now();

        const rtt = Math.max(0.2, t2 - t0);
        const srvTs = data.server_ts_ms;
        const offset = srvTs - (wall0 + wall2) / 2;

        rtts.push(rtt);
        offsets.push(offset);
        latestOffsetMs = offsets.reduce((a, b) => a + b, 0) / offsets.length;

        const sign = latestOffsetMs >= 0 ? "+" : "";
        document.getElementById("clock-offset-str").textContent = `${{sign}}${{latestOffsetMs.toFixed(1)}} ms`;

        const avgRtt = rtts.reduce((a, b) => a + b, 0) / rtts.length;
        const minRtt = Math.min(...rtts);
        const maxRtt = Math.max(...rtts);
        document.getElementById("val-ping").textContent = avgRtt.toFixed(1);
        document.getElementById("sub-ping").textContent = `Min ${{minRtt.toFixed(1)}} / Max ${{maxRtt.toFixed(1)}} ms`;

        if (rtts.length > 1) {{
          let diffs = 0;
          for (let j = 1; j < rtts.length; j++) {{
            diffs += Math.abs(rtts[j] - rtts[j - 1]);
          }}
          const jitter = diffs / (rtts.length - 1);
          document.getElementById("val-jitter").textContent = jitter.toFixed(1);
        }} else {{
          document.getElementById("val-jitter").textContent = "0.0";
        }}

        const maxBar = Math.max(30, ...rtts);
        pingBarsEl.innerHTML = rtts
          .map((v) => {{
            const h = Math.max(10, Math.round((v / maxBar) * 100));
            return `<div class="st-bar" style="height:${{h}}%" title="${{v.toFixed(1)}} ms"></div>`;
          }})
          .join("");

        await new Promise((r) => setTimeout(r, 60));
      }}
    }}

    async function runDownloadPhase(sizeMb) {{
      stageTextEl.textContent = `正在测试下行带宽 (${{sizeMb}} MB 内存流)...`;
      progressEl.style.width = "50%";

      const t0 = performance.now();
      const response = await fetch(`/api/speedtest/download?size_mb=${{sizeMb}}&_=${{Date.now()}}`, {{
        cache: "no-store",
      }});
      const reader = response.body.getReader();
      let received = 0;
      const total = sizeMb * 1024 * 1024;

      while (true) {{
        const {{ done, value }} = await reader.read();
        if (done) break;
        received += value.byteLength;
        const elapsedSec = Math.max(0.001, (performance.now() - t0) / 1000);
        const mbps = (received * 8) / (elapsedSec * 1e6);
        const mbs = received / (elapsedSec * 1024 * 1024);
        document.getElementById("val-dl").textContent = mbps.toFixed(1);
        document.getElementById("sub-dl").textContent = `${{mbs.toFixed(2)}} MB/s`;
        progressEl.style.width = `${{35 + Math.round((received / total) * 35)}}%`;
      }}
    }}

    async function runUploadPhase(sizeMb) {{
      stageTextEl.textContent = `正在测试上行带宽 (${{sizeMb}} MB 内存块)...`;
      progressEl.style.width = "75%";

      const totalBytes = sizeMb * 1024 * 1024;
      const buffer = new Uint8Array(totalBytes);
      const t0 = performance.now();

      await fetch(`/api/speedtest/upload?_=${{Date.now()}}`, {{
        method: "POST",
        headers: {{ "Content-Type": "application/octet-stream" }},
        body: buffer,
      }});

      const elapsedSec = Math.max(0.001, (performance.now() - t0) / 1000);
      const mbps = (totalBytes * 8) / (elapsedSec * 1e6);
      const mbs = totalBytes / (elapsedSec * 1024 * 1024);
      document.getElementById("val-ul").textContent = mbps.toFixed(1);
      document.getElementById("sub-ul").textContent = `${{mbs.toFixed(2)}} MB/s`;
      progressEl.style.width = "100%";
    }}

    document.getElementById("btn-ping-only").addEventListener("click", async () => {{
      if (isRunning) return;
      isRunning = true;
      try {{
        await runPingPhase(12);
        progressEl.style.width = "100%";
        stageTextEl.textContent = "✅ 服务器时间与延迟诊断完成";
      }} catch (e) {{
        stageTextEl.textContent = `❌ 测试出错: ${{e.message}}`;
      }} finally {{
        isRunning = false;
      }}
    }});

    document.getElementById("btn-full-test").addEventListener("click", async () => {{
      if (isRunning) return;
      isRunning = true;
      const sizeMb = parseInt(document.getElementById("st-size").value, 10) || 4;
      try {{
        await runPingPhase(12);
        await runDownloadPhase(sizeMb);
        await runUploadPhase(sizeMb);
        stageTextEl.textContent = "✅ 时间同步、延迟与上下行带宽测试全部完成";
      }} catch (e) {{
        stageTextEl.textContent = `❌ 测试中断: ${{e.message}}`;
      }} finally {{
        isRunning = false;
      }}
    }});

    runPingPhase(6).then(() => {{
      progressEl.style.width = "100%";
      stageTextEl.textContent = "已同步服务器时钟与初始延迟，可点击下方开始完整带宽测速";
    }});
  </script>
</body>
</html>"""


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

    if slug == "pi-status-note":
        return _render_notes_app(service, identity)
    if slug == "speedtest-node":
        return _render_speedtest_app(service, identity)

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
