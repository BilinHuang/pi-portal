"""Local 3-Tier Novel Reader Router & Web UI (Feature B).

Directory Hierarchy (modeled after user's G_S structure):
- Tier 1 (Epoch / 卷): Top-level directories inside `NOVELS_DIR` (e.g. `epoch1` .. `epoch6`)
- Tier 2 (Story Project & Guidelines / 篇章与设定):
  - Subdirectories inside an Epoch (e.g. `双生共振实验`, `guideline`, `ideas`)
  - Direct Epoch-level files (e.g. `catalog.md`, `naming_convention.md`)
- Tier 3 (Chapters / 章节正文):
  - `.txt` and `.md` files inside a Tier 2 directory (e.g. `001_对向X轴的齿轮死锁.txt`), sorted naturally.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import NOVELS_DIR
from ..database import get_db
from ..dependencies import CurrentIdentity, can_launch_service, get_current_identity
from ..models import Service

router = APIRouter(prefix="/api/reader", tags=["reader"])

NOVELS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown"}
META_FOLDER_NAMES = {"guideline", "guidelines", "ideas", "idea", "meta", "设定", "大纲", "notes"}


def _natural_sort_key(s: str) -> List[Any]:
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]


def _require_reader_access(identity: CurrentIdentity, db: Session) -> None:
    svc = db.query(Service).filter(Service.slug == "novel-reader").first()
    if svc and not can_launch_service(identity, svc):
        raise HTTPException(status_code=404, detail="Not Found")


def _safe_resolve(rel_path: str) -> Path:
    """Resolve a relative path inside NOVELS_DIR and prevent path traversal."""
    root = NOVELS_DIR.resolve()
    target = (root / rel_path.lstrip("/\\")).resolve()
    if target != root and not str(target).startswith(str(root) + "/"):
        raise HTTPException(status_code=404, detail="Not Found")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not Found")
    return target


def _is_visible_file(p: Path) -> bool:
    return p.is_file() and not p.name.startswith(".") and p.suffix.lower() in ALLOWED_EXTENSIONS


def _is_visible_dir(p: Path) -> bool:
    return p.is_dir() and not p.name.startswith(".")


@router.get("/tree")
def get_novel_library_tree(
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Return the complete 3-tier hierarchy of `NOVELS_DIR`."""
    _require_reader_access(identity, db)
    root = NOVELS_DIR.resolve()

    epochs: List[Dict[str, Any]] = []
    top_dirs = sorted([d for d in root.iterdir() if _is_visible_dir(d)], key=lambda p: _natural_sort_key(p.name))

    for epoch_dir in top_dirs:
        stories: List[Dict[str, Any]] = []
        meta_folders: List[Dict[str, Any]] = []
        epoch_files: List[Dict[str, Any]] = []

        # Direct files in Epoch (e.g. catalog.md, naming_convention.md)
        for f in sorted([x for x in epoch_dir.iterdir() if _is_visible_file(x)], key=lambda p: _natural_sort_key(p.name)):
            epoch_files.append(
                {
                    "name": f.name,
                    "title": f.stem,
                    "rel_path": str(f.relative_to(root)),
                    "size": f.stat().st_size,
                }
            )

        # Tier 2 subdirectories in Epoch
        sub_dirs = sorted([d for d in epoch_dir.iterdir() if _is_visible_dir(d)], key=lambda p: _natural_sort_key(p.name))
        for sdir in sub_dirs:
            chapters: List[Dict[str, Any]] = []
            for ch in sorted([x for x in sdir.iterdir() if _is_visible_file(x)], key=lambda p: _natural_sort_key(p.name)):
                chapters.append(
                    {
                        "name": ch.name,
                        "title": ch.stem,
                        "rel_path": str(ch.relative_to(root)),
                        "size": ch.stat().st_size,
                        "mtime": datetime.fromtimestamp(ch.stat().st_mtime, tz=timezone.utc).isoformat(),
                    }
                )

            folder_item = {
                "name": sdir.name,
                "rel_path": str(sdir.relative_to(root)),
                "chapter_count": len(chapters),
                "chapters": chapters,
                "is_meta": sdir.name.lower() in META_FOLDER_NAMES,
            }
            if folder_item["is_meta"]:
                meta_folders.append(folder_item)
            else:
                stories.append(folder_item)

        epochs.append(
            {
                "name": epoch_dir.name,
                "rel_path": str(epoch_dir.relative_to(root)),
                "stories": stories,
                "meta_folders": meta_folders,
                "epoch_files": epoch_files,
                "story_count": len(stories),
            }
        )

    return {
        "novels_dir": str(root),
        "epochs": epochs,
    }


@router.get("/content")
def get_chapter_content(
    path: str = Query(..., description="Relative file path inside NOVELS_DIR"),
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Read a specific `.txt` or `.md` file from the local novel library."""
    _require_reader_access(identity, db)
    target = _safe_resolve(path)
    if not _is_visible_file(target):
        raise HTTPException(status_code=404, detail="Not Found")

    text = target.read_text(encoding="utf-8", errors="replace")
    root = NOVELS_DIR.resolve()
    parent_dir = target.parent

    # Find siblings in the same folder for prev/next navigation
    siblings = sorted(
        [x for x in parent_dir.iterdir() if _is_visible_file(x)],
        key=lambda p: _natural_sort_key(p.name),
    )
    sibling_paths = [str(x.relative_to(root)) for x in siblings]
    cur_rel = str(target.relative_to(root))

    prev_path = None
    next_path = None
    if cur_rel in sibling_paths:
        idx = sibling_paths.index(cur_rel)
        if idx > 0:
            prev_path = sibling_paths[idx - 1]
        if idx < len(sibling_paths) - 1:
            next_path = sibling_paths[idx + 1]

    return {
        "name": target.name,
        "title": target.stem,
        "rel_path": cur_rel,
        "folder_name": parent_dir.name,
        "content": text,
        "char_count": len(text),
        "prev_path": prev_path,
        "next_path": next_path,
    }


# ==================== 3-Tier Novel Reader Web UI ====================
def render_novel_reader_app(service: Service, identity: CurrentIdentity) -> str:
    """Render the 3-tier Local Novel Reader Web UI for `/apps/novel-reader`."""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes, viewport-fit=cover" />
  <title>{service.name} — Pi 5 Portal</title>
  <link rel="stylesheet" href="/static/css/style.css?v=2.2" />
  <style>
    :root {{
      --reader-bg: #0b0f19;
      --reader-card: #111827;
      --reader-text: #e2e8f0;
      --reader-font-size: 18px;
      --reader-line-height: 1.9;
    }}
    body.theme-sepia {{
      --reader-bg: #1c1917;
      --reader-card: #262320;
      --reader-text: #d6d3d1;
    }}
    body.theme-oled {{
      --reader-bg: #000000;
      --reader-card: #09090b;
      --reader-text: #cbd5e1;
    }}
    .reader-shell {{
      max-width: 1120px;
      margin: 1.25rem auto 4rem;
      padding: 0 1rem;
    }}
    .resume-banner {{
      background: rgba(56, 189, 248, 0.1);
      border: 1px solid rgba(56, 189, 248, 0.3);
      border-radius: 12px;
      padding: 0.7rem 1rem;
      margin-bottom: 1rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.5rem;
      font-size: 0.84rem;
    }}
    /* 3-Tier Browser Layout */
    .tier-grid {{
      display: grid;
      grid-template-columns: 210px 280px 1fr;
      gap: 1rem;
      align-items: start;
    }}
    @media (max-width: 860px) {{
      .tier-grid {{
        grid-template-columns: 1fr;
      }}
    }}
    .tier-col {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 14px;
      padding: 0.9rem;
    }}
    .tier-col-header {{
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--text-muted);
      padding-bottom: 0.55rem;
      margin-bottom: 0.65rem;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .tier-list {{
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
    }}
    .tier-item {{
      width: 100%;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.5rem;
      background: rgba(15, 23, 42, 0.55);
      border: 1px solid rgba(255, 255, 255, 0.06);
      color: var(--text-main);
      padding: 0.62rem 0.8rem;
      border-radius: 9px;
      font-size: 0.86rem;
      font-weight: 600;
      cursor: pointer;
      text-align: left;
      transition: all 0.15s ease;
    }}
    .tier-item:hover {{
      border-color: rgba(56, 189, 248, 0.35);
      background: rgba(30, 41, 59, 0.75);
    }}
    .tier-item.active {{
      background: rgba(56, 189, 248, 0.16);
      border-color: rgba(56, 189, 248, 0.45);
      color: #38bdf8;
    }}
    .tier-count {{
      font-size: 0.72rem;
      color: var(--text-muted);
      background: rgba(255, 255, 255, 0.06);
      padding: 0.1rem 0.45rem;
      border-radius: 999px;
      flex-shrink: 0;
    }}
    .tier-sub-divider {{
      font-size: 0.73rem;
      color: var(--text-muted);
      margin: 0.75rem 0 0.35rem;
      padding-left: 0.2rem;
      font-weight: 600;
    }}
    /* Reading View */
    .reader-view {{
      background: var(--reader-card);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      padding: 1.5rem 1.75rem 2.25rem;
      margin-top: 1rem;
    }}
    @media (max-width: 640px) {{
      .reader-view {{
        padding: 1.15rem 1rem 1.75rem;
      }}
    }}
    .reader-toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.65rem;
      padding-bottom: 1rem;
      margin-bottom: 1.25rem;
      border-bottom: 1px solid var(--border-subtle);
    }}
    .reader-breadcrumb {{
      font-size: 0.82rem;
      color: var(--text-muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    .reader-controls {{
      display: flex;
      align-items: center;
      gap: 0.4rem;
      flex-wrap: wrap;
    }}
    .chapter-title {{
      font-size: 1.35rem;
      font-weight: 800;
      color: #f8fafc;
      margin-bottom: 0.4rem;
      line-height: 1.35;
    }}
    .chapter-meta {{
      font-size: 0.78rem;
      color: var(--text-muted);
      margin-bottom: 1.4rem;
    }}
    .chapter-body {{
      font-size: var(--reader-font-size);
      line-height: var(--reader-line-height);
      color: var(--reader-text);
      white-space: pre-wrap;
      word-break: break-word;
      letter-spacing: 0.015em;
    }}
    .chapter-nav-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.75rem;
      margin-top: 2rem;
      padding-top: 1.2rem;
      border-top: 1px solid var(--border-subtle);
    }}
  </style>
</head>
<body>
  <div class="reader-shell">
    <div class="subapp-header">
      <div style="display:flex;gap:0.5rem;align-items:center;">
        <a href="/" class="btn btn-ghost">← 返回</a>
        <button type="button" class="btn btn-outline hidden" id="btn-back-to-index" onclick="showIndexView()">
          📂 展开三层目录
        </button>
      </div>
      <span class="status-tag status-tag-active">{service.icon} {service.name}</span>
    </div>

    <!-- Resume Reading Banner -->
    <div id="resume-banner" class="resume-banner hidden">
      <div>
        <span>📖 上次阅读：</span>
        <strong id="resume-title" style="color:var(--accent);"></strong>
      </div>
      <button type="button" class="btn-action" id="btn-resume-read">继续阅读 →</button>
    </div>

    <!-- 3-Tier Directory Explorer -->
    <div id="explorer-view" class="tier-grid">
      <!-- Tier 1: Epochs -->
      <div class="tier-col">
        <div class="tier-col-header">
          <span>第一层 · 卷 / Epoch</span>
          <span id="epoch-count-label">0</span>
        </div>
        <div class="tier-list" id="tier1-epochs">正在读取目录...</div>
      </div>

      <!-- Tier 2: Stories & Guidelines -->
      <div class="tier-col">
        <div class="tier-col-header">
          <span>第二层 · 篇章与设定</span>
          <span id="story-count-label">0</span>
        </div>
        <div id="tier2-container">
          <div style="font-size:0.82rem;color:var(--text-muted);padding:0.5rem 0;">请先选择左侧 Epoch</div>
        </div>
      </div>

      <!-- Tier 3: Chapters -->
      <div class="tier-col">
        <div class="tier-col-header">
          <span id="tier3-header-title">第三层 · 章节正文</span>
          <span id="chapter-count-label">0</span>
        </div>
        <div class="tier-list" id="tier3-chapters">
          <div style="font-size:0.82rem;color:var(--text-muted);padding:0.5rem 0;">请选择第二层篇章文件夹</div>
        </div>
      </div>
    </div>

    <!-- Immersive Reader View -->
    <div id="reader-view" class="reader-view hidden">
      <div class="reader-toolbar">
        <div class="reader-breadcrumb" id="reader-breadcrumb">--</div>
        <div class="reader-controls">
          <button class="btn-action" onclick="adjustFont(-1)">A-</button>
          <button class="btn-action" onclick="adjustFont(1)">A+</button>
          <button class="btn-action" onclick="setTheme('default')">默认暗色</button>
          <button class="btn-action" onclick="setTheme('sepia')">暖灰护眼</button>
          <button class="btn-action" onclick="setTheme('oled')">纯黑 OLED</button>
        </div>
      </div>

      <h1 class="chapter-title" id="chapter-title"></h1>
      <div class="chapter-meta" id="chapter-meta"></div>
      <div class="chapter-body" id="chapter-body"></div>

      <div class="chapter-nav-bar">
        <button class="btn btn-outline" id="btn-prev-ch" onclick="goPrevChapter()">← 上一章</button>
        <button class="btn btn-ghost" onclick="showIndexView()">返回目录</button>
        <button class="btn btn-accent" id="btn-next-ch" onclick="goNextChapter()">下一章 →</button>
      </div>
    </div>
  </div>

  <div class="toast hidden" id="toast"></div>

  <script>
    const STORAGE_KEY = "pi_portal_novel_reader_state_v1";
    let libraryTree = [];
    let selectedEpochIdx = 0;
    let selectedFolderRel = "";
    let currentChapterData = null;
    let currentFontSize = parseInt(localStorage.getItem("pi_reader_font_size") || "18", 10);

    document.documentElement.style.setProperty("--reader-font-size", `${{currentFontSize}}px`);

    const savedTheme = localStorage.getItem("pi_reader_theme") || "default";
    setTheme(savedTheme, false);

    function escapeHtml(str) {{
      return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }}

    function adjustFont(delta) {{
      currentFontSize = Math.min(26, Math.max(14, currentFontSize + delta));
      document.documentElement.style.setProperty("--reader-font-size", `${{currentFontSize}}px`);
      localStorage.setItem("pi_reader_font_size", String(currentFontSize));
    }}

    function setTheme(mode, persist = true) {{
      document.body.classList.remove("theme-sepia", "theme-oled");
      if (mode === "sepia") document.body.classList.add("theme-sepia");
      if (mode === "oled") document.body.classList.add("theme-oled");
      if (persist) localStorage.setItem("pi_reader_theme", mode);
    }}

    async function initLibrary() {{
      const res = await fetch("/api/reader/tree");
      const data = await res.json();
      libraryTree = data.epochs || [];
      document.getElementById("epoch-count-label").textContent = String(libraryTree.length);

      if (libraryTree.length === 0) {{
        document.getElementById("tier1-epochs").innerHTML =
          `<div style="font-size:0.82rem;color:var(--text-muted);">未检测到卷目录，请将小说目录放入 <code>${{escapeHtml(data.novels_dir)}}</code></div>`;
        return;
      }}

      // Check saved progress
      try {{
        const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
        if (saved && saved.rel_path) {{
          const banner = document.getElementById("resume-banner");
          document.getElementById("resume-title").textContent = saved.rel_path;
          banner.classList.remove("hidden");
          document.getElementById("btn-resume-read").onclick = () => openChapter(saved.rel_path);
        }}
      }} catch (e) {{}}

      renderTier1(0);
    }}

    function renderTier1(activeIndex) {{
      selectedEpochIdx = activeIndex;
      const t1 = document.getElementById("tier1-epochs");
      t1.innerHTML = libraryTree
        .map(
          (ep, idx) => `
          <button type="button" class="tier-item ${{idx === activeIndex ? "active" : ""}}" onclick="renderTier1(${{idx}})">
            <span>📁 ${{escapeHtml(ep.name)}}</span>
            <span class="tier-count">${{ep.story_count}} 篇</span>
          </button>
        `
        )
        .join("");

      renderTier2(libraryTree[activeIndex]);
    }}

    function renderTier2(epoch) {{
      const container = document.getElementById("tier2-container");
      if (!epoch) {{
        container.innerHTML = "";
        return;
      }}

      const stories = epoch.stories || [];
      const metas = epoch.meta_folders || [];
      const files = epoch.epoch_files || [];
      document.getElementById("story-count-label").textContent = String(stories.length);

      let html = "";

      if (stories.length > 0) {{
        html += `<div class="tier-sub-divider">故事篇章</div><div class="tier-list">`;
        html += stories
          .map(
            (st) => `
            <button type="button" class="tier-item ${{selectedFolderRel === st.rel_path ? "active" : ""}}" onclick="selectTier2Folder('${{escapeHtml(st.rel_path)}}')">
              <span>📘 ${{escapeHtml(st.name)}}</span>
              <span class="tier-count">${{st.chapter_count}} 章</span>
            </button>
          `
          )
          .join("");
        html += `</div>`;
      }}

      if (metas.length > 0) {{
        html += `<div class="tier-sub-divider">设定与大纲夹</div><div class="tier-list">`;
        html += metas
          .map(
            (m) => `
            <button type="button" class="tier-item ${{selectedFolderRel === m.rel_path ? "active" : ""}}" onclick="selectTier2Folder('${{escapeHtml(m.rel_path)}}')">
              <span>🗂️ ${{escapeHtml(m.name)}}</span>
              <span class="tier-count">${{m.chapter_count}}</span>
            </button>
          `
          )
          .join("");
        html += `</div>`;
      }}

      if (files.length > 0) {{
        html += `<div class="tier-sub-divider">卷级索引 / 规范文档</div><div class="tier-list">`;
        html += files
          .map(
            (f) => `
            <button type="button" class="tier-item" onclick="openChapter('${{escapeHtml(f.rel_path)}}')">
              <span>📄 ${{escapeHtml(f.name)}}</span>
            </button>
          `
          )
          .join("");
        html += `</div>`;
      }}

      container.innerHTML = html || `<div style="font-size:0.82rem;color:var(--text-muted);">该卷暂无内容</div>`;

      // Auto-select first story folder if available
      if (stories.length > 0) {{
        selectTier2Folder(stories[0].rel_path);
      }} else if (metas.length > 0) {{
        selectTier2Folder(metas[0].rel_path);
      }} else {{
        document.getElementById("tier3-chapters").innerHTML = `<div style="font-size:0.82rem;color:var(--text-muted);">暂无章节</div>`;
        document.getElementById("chapter-count-label").textContent = "0";
      }}
    }}

    function selectTier2Folder(folderRel) {{
      selectedFolderRel = folderRel;
      const epoch = libraryTree[selectedEpochIdx];
      if (!epoch) return;

      // Update active highlight in Tier 2
      document.querySelectorAll("#tier2-container .tier-item").forEach((btn) => {{
        const isMatch = btn.getAttribute("onclick")?.includes(`'${{folderRel}}'`);
        btn.classList.toggle("active", Boolean(isMatch));
      }});

      const allFolders = [...(epoch.stories || []), ...(epoch.meta_folders || [])];
      const target = allFolders.find((x) => x.rel_path === folderRel);
      const t3 = document.getElementById("tier3-chapters");

      if (!target || !Array.isArray(target.chapters) || target.chapters.length === 0) {{
        document.getElementById("tier3-header-title").textContent = "第三层 · 章节正文";
        document.getElementById("chapter-count-label").textContent = "0";
        t3.innerHTML = `<div style="font-size:0.82rem;color:var(--text-muted);padding:0.4rem 0;">该文件夹下暂无 .txt / .md 文件</div>`;
        return;
      }}

      document.getElementById("tier3-header-title").textContent = `第三层 · ${{target.name}}`;
      document.getElementById("chapter-count-label").textContent = `${{target.chapters.length}} 章`;

      t3.innerHTML = target.chapters
        .map(
          (ch) => `
          <button type="button" class="tier-item" onclick="openChapter('${{escapeHtml(ch.rel_path)}}')">
            <span>📄 ${{escapeHtml(ch.name)}}</span>
            <span class="tier-count">${{(ch.size / 1024).toFixed(1)}} KB</span>
          </button>
        `
        )
        .join("");
    }}

    async function openChapter(relPath) {{
      const res = await fetch(`/api/reader/content?path=${{encodeURIComponent(relPath)}}`);
      if (!res.ok) return;
      const data = await res.json();
      currentChapterData = data;

      document.getElementById("explorer-view").classList.add("hidden");
      document.getElementById("reader-view").classList.remove("hidden");
      document.getElementById("btn-back-to-index").classList.remove("hidden");

      document.getElementById("reader-breadcrumb").textContent = data.rel_path;
      document.getElementById("chapter-title").textContent = data.title;
      document.getElementById("chapter-meta").textContent = `所属目录: ${{data.folder_name}} · 共 ${{data.char_count}} 字`;
      document.getElementById("chapter-body").textContent = data.content;

      document.getElementById("btn-prev-ch").disabled = !data.prev_path;
      document.getElementById("btn-next-ch").disabled = !data.next_path;

      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({{
          rel_path: data.rel_path,
          title: data.title,
          ts: Date.now(),
        }})
      );
      document.getElementById("resume-title").textContent = data.rel_path;
      document.getElementById("resume-banner").classList.remove("hidden");

      window.scrollTo({{ top: 0, behavior: "smooth" }});
    }}

    function showIndexView() {{
      document.getElementById("reader-view").classList.add("hidden");
      document.getElementById("explorer-view").classList.remove("hidden");
      document.getElementById("btn-back-to-index").classList.add("hidden");
    }}

    function goPrevChapter() {{
      if (currentChapterData && currentChapterData.prev_path) {{
        openChapter(currentChapterData.prev_path);
      }}
    }}

    function goNextChapter() {{
      if (currentChapterData && currentChapterData.next_path) {{
        openChapter(currentChapterData.next_path);
      }}
    }}

    document.addEventListener("keydown", (e) => {{
      const readerHidden = document.getElementById("reader-view").classList.contains("hidden");
      if (readerHidden) return;
      if (e.key === "ArrowLeft") goPrevChapter();
      if (e.key === "ArrowRight") goNextChapter();
    }});

    initLibrary();
  </script>
</body>
</html>"""
