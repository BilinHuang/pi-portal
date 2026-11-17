"""Gemini Relay Station Router (`/api/relay` & `/apps/gemini-relay`).

Public Baseline (`6+`) built-in mini-app modeled after Story Studio:
- Shares the multi-key pool (`keys/*.key`) with automatic round-robin & 429/403/503 failover
- Customizable System Prompt (`systemInstruction`) with quick reset/clear
- Supports switching between Multi-turn Conversation (`chat`) and Single-turn Execution (`single`)
- Supports model selection, reasoning effort (`thinkingConfig`), and real-time SSE streaming with instant stop
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Generator, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import KEYS_DIR
from ..database import get_db
from ..dependencies import CurrentIdentity, can_launch_service, get_current_identity
from ..models import Service
from .studio import (
    AVAILABLE_MODELS,
    GEMINI_API_BASE,
    SAFETY_SETTINGS_BLOCK_NONE,
    THINKING_BUDGET_MAP,
    _verify_and_deduct_quota,
    key_pool,
)

router = APIRouter(prefix="/api/relay", tags=["relay"])

DEFAULT_RELAY_SYSTEM_PROMPT = (
    "你是一个高效、准确、客观的 AI 助手。请直接、清晰地回答用户的问题，遵循用户设定的格式与角色要求。"
)


class RelayMessageItem(BaseModel):
    role: str = Field(..., description="'user' or 'model'")
    content: str = Field(..., description="Message text content")


class RelayStreamRequest(BaseModel):
    mode: str = Field(default="chat", description="'chat' (multi-turn) or 'single' (single-turn)")
    prompt: str = Field(default="", description="Current user input")
    messages: List[RelayMessageItem] = Field(default_factory=list, description="Conversation history for multi-turn mode")
    system_prompt: Optional[str] = Field(default="")
    model: str = Field(default="gemini-3.5-flash-lite")
    reasoning_effort: str = Field(default="high")
    temperature: float = Field(default=0.7)
    preferred_key: str = Field(default="auto")


class RelayTaskController:
    """Tracks active upstream HTTP response so the user can abort streaming immediately."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.stop_requested = False
        self.active_resp: Any = None

    def reset_for_new_run(self) -> None:
        with self.lock:
            self.stop_requested = False
            if self.active_resp:
                try:
                    self.active_resp.close()
                except Exception:
                    pass
                self.active_resp = None

    def stop(self) -> None:
        with self.lock:
            self.stop_requested = True
            if self.active_resp:
                try:
                    self.active_resp.close()
                except Exception:
                    pass
                self.active_resp = None


relay_ctrl = RelayTaskController()


def _require_relay_access(identity: CurrentIdentity, db: Session) -> None:
    svc = db.query(Service).filter(Service.slug == "gemini-relay").first()
    if svc and not can_launch_service(identity, svc):
        raise HTTPException(status_code=404, detail="Not Found")


def _build_relay_payload(
    contents: List[Dict[str, Any]],
    system_prompt: str = "",
    temperature: float = 0.7,
    reasoning_effort: str = "high",
    include_thinking: bool = True,
) -> Dict[str, Any]:
    gen_config: Dict[str, Any] = {
        "temperature": max(0.0, min(2.0, float(temperature))),
        "topP": 0.92,
    }
    if include_thinking and reasoning_effort in THINKING_BUDGET_MAP:
        budget = THINKING_BUDGET_MAP[reasoning_effort]
        if budget is not None and budget > 0:
            gen_config["thinkingConfig"] = {"thinkingBudget": budget}

    payload: Dict[str, Any] = {
        "contents": contents,
        "generationConfig": gen_config,
        "safetySettings": SAFETY_SETTINGS_BLOCK_NONE,
    }
    if system_prompt and system_prompt.strip():
        payload["systemInstruction"] = {"parts": [{"text": system_prompt.strip()}]}
    return payload


def _stream_relay_events(
    contents: List[Dict[str, Any]],
    system_prompt: str,
    model: str,
    temperature: float,
    reasoning_effort: str,
    preferred_key: str,
) -> Generator[str, None, None]:
    """Yield SSE data lines (`data: {...}\\n\\n`) with multi-key failover."""

    def _sse(event_type: str, **kwargs: Any) -> str:
        return f"data: {json.dumps({'type': event_type, **kwargs}, ensure_ascii=False)}\n\n"

    candidates = key_pool.get_ordered_candidates(preferred_key)
    if not candidates:
        yield _sse("error", error="未检测到有效 API Key，请在 keys/ 目录下放入 Gemini1.key 等密钥文件。")
        return

    last_err = ""
    for item in candidates:
        if relay_ctrl.stop_requested:
            yield _sse("stopped")
            return

        key_name = item["name"]
        api_key = item["key"]

        for use_thinking in (True, False):
            if relay_ctrl.stop_requested:
                yield _sse("stopped")
                return

            payload = _build_relay_payload(
                contents=contents,
                system_prompt=system_prompt,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                include_thinking=use_thinking,
            )
            url = (
                f"{GEMINI_API_BASE}/{urllib.parse.quote(model)}:streamGenerateContent"
                f"?alt=sse&key={urllib.parse.quote(api_key)}"
            )
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = None
            try:
                yield _sse("status", msg=f"⚡ 正在通过 [{key_name}] 请求 {model}...")
                resp = urllib.request.urlopen(req, timeout=600)
                with relay_ctrl.lock:
                    relay_ctrl.active_resp = resp

                notified_thinking = False
                for raw_line in resp:
                    if relay_ctrl.stop_requested:
                        yield _sse("stopped")
                        return
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data_str)
                    except Exception:
                        continue
                    cands = chunk.get("candidates") or []
                    if not cands:
                        block_reason = chunk.get("promptFeedback", {}).get("blockReason")
                        if block_reason:
                            raise RuntimeError(f"请求被拦截 (blockReason={block_reason})")
                        continue
                    parts = cands[0].get("content", {}).get("parts") or []
                    for p in parts:
                        if p.get("thought", False):
                            if not notified_thinking:
                                notified_thinking = True
                                yield _sse("status", msg=f"🧠 [{key_name}] 模型正在深度思考...")
                            continue
                        txt = p.get("text", "")
                        if txt:
                            yield _sse("token", content=txt)

                yield _sse("status", msg=f"✓ 生成完成 (Key: {key_name})")
                yield _sse("done", key=key_name)
                return
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
                if e.code == 400 and use_thinking and (
                    "thinking" in err_body.lower() or "budget" in err_body.lower()
                ):
                    continue
                last_err = f"[{key_name}] HTTP {e.code}: {err_body[:240]}"
                if e.code in (429, 403, 500, 503) and len(candidates) > 1:
                    yield _sse(
                        "status",
                        msg=f"⚠️ {key_name} 触发限流/异常 ({e.code})，自动切换下一个 Key...",
                    )
                    break
                break
            except Exception as e:
                if relay_ctrl.stop_requested:
                    yield _sse("stopped")
                    return
                last_err = f"[{key_name}] {e}"
                break
            finally:
                with relay_ctrl.lock:
                    if resp:
                        try:
                            resp.close()
                        except Exception:
                            pass
                    relay_ctrl.active_resp = None

    if relay_ctrl.stop_requested:
        yield _sse("stopped")
    else:
        yield _sse("error", error=f"调用 Gemini API 失败: {last_err}")


@router.get("/meta")
def get_relay_metadata(
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Return available keys (masked), models, and default system prompt."""
    _require_relay_access(identity, db)
    loaded_keys = [
        {"name": k["name"], "masked": k["masked"]}
        for k in key_pool.load_keys()
    ]
    return {
        "keys": loaded_keys,
        "keys_dir": str(KEYS_DIR),
        "models": AVAILABLE_MODELS,
        "default_system_prompt": DEFAULT_RELAY_SYSTEM_PROMPT,
    }


@router.post("/stop")
def stop_relay_stream(
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Immediately stop the active relay generation stream."""
    _require_relay_access(identity, db)
    relay_ctrl.stop()
    return {"success": True}


@router.post("/stream")
def stream_relay_completion(
    payload: RelayStreamRequest,
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Stream Gemini response in either single-turn (`single`) or multi-turn (`chat`) mode."""
    _require_relay_access(identity, db)

    mode = (payload.mode or "chat").strip().lower()
    contents: List[Dict[str, Any]] = []

    if mode == "single":
        user_text = payload.prompt.strip()
        if not user_text and payload.messages:
            user_text = payload.messages[-1].content.strip()
        if not user_text:
            raise HTTPException(status_code=400, detail="请输入要发送的内容")
        contents = [{"role": "user", "parts": [{"text": user_text}]}]
    else:
        for msg in payload.messages:
            text = (msg.content or "").strip()
            if not text:
                continue
            role = "model" if msg.role in ("model", "assistant") else "user"
            contents.append({"role": role, "parts": [{"text": text}]})
        if payload.prompt and payload.prompt.strip():
            contents.append({"role": "user", "parts": [{"text": payload.prompt.strip()}]})
        if not contents:
            raise HTTPException(status_code=400, detail="对话内容不能为空")

    _verify_and_deduct_quota(identity, db)
    relay_ctrl.reset_for_new_run()

    model_name = (payload.model or "").strip() or "gemini-3.5-flash-lite"
    sys_prompt = (payload.system_prompt or "").strip()

    return StreamingResponse(
        _stream_relay_events(
            contents=contents,
            system_prompt=sys_prompt,
            model=model_name,
            temperature=payload.temperature,
            reasoning_effort=payload.reasoning_effort,
            preferred_key=payload.preferred_key,
        ),
        media_type="text/event-stream",
    )


# ==================== Gemini Relay Station Web UI Renderer ====================
def render_gemini_relay_app(service: Service, identity: CurrentIdentity) -> str:
    """Render the responsive Gemini Relay Station Web UI for `/apps/gemini-relay`."""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes, viewport-fit=cover" />
  <title>{service.name} — Pi 5 Portal</title>
  <link rel="stylesheet" href="/static/css/style.css?v=2.2" />
  <style>
    .studio-wrap {{
      max-width: 960px;
      margin: 1.5rem auto 4rem;
      padding: 0 1.1rem;
    }}
    .studio-config-bar {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 14px;
      padding: 1rem 1.2rem;
      margin-bottom: 1rem;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 0.85rem;
      align-items: end;
    }}
    .cfg-item label {{
      display: block;
      font-size: 0.76rem;
      color: var(--text-muted);
      margin-bottom: 0.3rem;
      font-weight: 600;
    }}
    .cfg-item select, .cfg-item input {{
      width: 100%;
      background: #0b1120;
      border: 1px solid rgba(255,255,255,0.14);
      border-radius: 8px;
      color: var(--text-main);
      padding: 0.5rem 0.7rem;
      font-size: 0.84rem;
      outline: none;
    }}
    .key-badge-bar {{
      grid-column: 1 / -1;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.5rem;
      padding-top: 0.55rem;
      border-top: 1px solid rgba(255,255,255,0.06);
      font-size: 0.78rem;
      color: var(--text-muted);
    }}
    .studio-tabs {{
      display: flex;
      gap: 0.5rem;
      margin-bottom: 1rem;
    }}
    .studio-tab {{
      flex: 1;
      text-align: center;
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      font-size: 0.88rem;
      font-weight: 600;
      padding: 0.7rem 1rem;
      border-radius: 11px;
      cursor: pointer;
      transition: all 0.15s ease;
    }}
    .studio-tab.active {{
      background: rgba(56, 189, 248, 0.15);
      color: var(--accent);
      border-color: rgba(56, 189, 248, 0.4);
    }}
    .sys-prompt-box {{
      background: rgba(15, 23, 42, 0.65);
      border: 1px solid rgba(56, 189, 248, 0.22);
      border-radius: 12px;
      padding: 0.95rem 1.1rem;
      margin-bottom: 1rem;
    }}
    .sys-prompt-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-bottom: 0.45rem;
      font-size: 0.82rem;
      font-weight: 600;
      color: #38bdf8;
    }}
    .studio-textarea {{
      width: 100%;
      background: #0b1120;
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 10px;
      color: var(--text-main);
      padding: 0.75rem 0.9rem;
      font-size: 0.9rem;
      line-height: 1.6;
      outline: none;
      resize: vertical;
    }}
    .studio-textarea:focus {{
      border-color: var(--accent);
    }}
    .relay-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 14px;
      padding: 1.2rem;
      margin-bottom: 1rem;
    }}
    .monitor-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.75rem;
      padding-bottom: 0.8rem;
      margin-bottom: 0.95rem;
      border-bottom: 1px solid var(--border-subtle);
    }}
    .status-badge-row {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--accent);
    }}
    .pulse-dot {{
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #64748b;
      flex-shrink: 0;
    }}
    .pulse-dot.live {{
      background: #10b981;
      box-shadow: 0 0 8px #10b981;
      animation: pulse 1.4s infinite;
    }}
    @keyframes pulse {{
      0%, 100% {{ opacity: 1; transform: scale(1); }}
      50% {{ opacity: 0.35; transform: scale(0.8); }}
    }}
    .chat-history {{
      display: flex;
      flex-direction: column;
      gap: 0.85rem;
      max-height: 520px;
      overflow-y: auto;
      padding-right: 0.25rem;
      margin-bottom: 1rem;
    }}
    .chat-empty {{
      text-align: center;
      color: var(--text-muted);
      font-size: 0.85rem;
      padding: 2.2rem 1rem;
      background: rgba(11, 17, 32, 0.5);
      border: 1px dashed rgba(255,255,255,0.08);
      border-radius: 10px;
    }}
    .msg-item {{
      border-radius: 12px;
      padding: 0.85rem 1rem;
      border: 1px solid rgba(255,255,255,0.08);
      line-height: 1.7;
      font-size: 0.92rem;
    }}
    .msg-user {{
      background: rgba(14, 165, 233, 0.12);
      border-color: rgba(56, 189, 248, 0.28);
      align-self: flex-end;
      width: 100%;
    }}
    .msg-model {{
      background: rgba(11, 17, 32, 0.85);
      border-color: rgba(255, 255, 255, 0.1);
      align-self: flex-start;
      width: 100%;
    }}
    .msg-meta {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-bottom: 0.35rem;
      font-weight: 600;
    }}
    .msg-text {{
      white-space: pre-wrap;
      word-break: break-word;
      color: #e2e8f0;
    }}
    .input-actions-row {{
      display: flex;
      gap: 0.65rem;
      margin-top: 0.85rem;
      flex-wrap: wrap;
    }}
    .run-btn {{
      flex: 1;
      min-width: 180px;
      background: linear-gradient(135deg, #0ea5e9, #2563eb);
      color: #fff;
      border: none;
      padding: 0.82rem 1.2rem;
      border-radius: 10px;
      font-size: 0.94rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.15s ease;
    }}
    .run-btn:disabled {{
      opacity: 0.45;
      cursor: not-allowed;
    }}
    .single-output-box {{
      background: #0b1120;
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 10px;
      padding: 1rem;
      min-height: 160px;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.8;
      font-size: 0.94rem;
      color: #e2e8f0;
      margin-bottom: 1rem;
    }}
  </style>
</head>
<body>
  <div class="studio-wrap">
    <div class="subapp-header">
      <a href="/" class="btn btn-ghost">← 返回</a>
      <span class="status-tag status-tag-active">{service.icon} {service.name}</span>
    </div>

    <!-- Top Engine & Key Bar -->
    <div class="studio-config-bar">
      <div class="cfg-item">
        <label for="model-select" style="display:flex;justify-content:space-between;align-items:center;">
          <span>Gemini 模型</span>
          <span style="display:inline-flex;gap:0.25rem;">
            <button type="button" class="btn-action" id="quick-35fl" onclick="setModelQuick('gemini-3.5-flash-lite')">3.5 FL</button>
            <button type="button" class="btn-action" id="quick-31fl" onclick="setModelQuick('gemini-3.1-flash-lite')">3.1 FL</button>
          </span>
        </label>
        <select id="model-select" onchange="onModelSelectChange()">
          <option value="gemini-3.5-flash-lite" selected>Gemini 3.5 Flash Lite (3.5 FL)</option>
          <option value="gemini-3.1-flash-lite">Gemini 3.1 Flash Lite (3.1 FL)</option>
          <option value="gemini-3.6-flash">Gemini 3.6 Flash</option>
          <option value="__custom__">自定义模型 ID...</option>
        </select>
        <input
          type="text"
          id="custom-model-input"
          placeholder="输入自定义模型 ID，如 gemini-3.1-flash-lite"
          style="display:none;margin-top:0.4rem;"
        />
      </div>

      <div class="cfg-item">
        <label for="reasoning-select">推理深度 (Reasoning Effort)</label>
        <select id="reasoning-select">
          <option value="high" selected>High (高深度推理 — 默认)</option>
          <option value="medium">Medium (中等推理)</option>
          <option value="low">Low (轻量快速)</option>
          <option value="none">None (关闭思考)</option>
        </select>
      </div>

      <div class="cfg-item">
        <label for="temp-input">温度 (Temperature)</label>
        <input type="number" id="temp-input" value="0.7" min="0" max="2" step="0.05" />
      </div>

      <div class="cfg-item">
        <label for="key-select">API Key 调度 (keys/*.key)</label>
        <select id="key-select">
          <option value="auto" selected>🔄 自动轮询与故障切换</option>
        </select>
      </div>

      <div class="key-badge-bar">
        <span id="keys-status-text">正在检测 keys/ 目录...</span>
        <span>共享多密钥池 · 支持自定义 System Prompt</span>
      </div>
    </div>

    <!-- Mode Switch Tabs: Multi-turn Chat vs Single-turn -->
    <div class="studio-tabs">
      <button class="studio-tab active" id="tab-chat" onclick="switchRelayMode('chat')">
        💬 多轮对话模式 (保留上下文)
      </button>
      <button class="studio-tab" id="tab-single" onclick="switchRelayMode('single')">
        ⚡ 单轮直连模式 (每次独立请求)
      </button>
    </div>

    <!-- Custom System Prompt Box -->
    <div class="sys-prompt-box">
      <div class="sys-prompt-header">
        <span>自定义系统提示词 (System Prompt / System Instruction)</span>
        <div style="display:flex;gap:0.4rem;">
          <button type="button" class="btn-action" onclick="resetSystemPrompt()">恢复默认</button>
          <button type="button" class="btn-action" onclick="clearSystemPrompt()">清空提示词</button>
        </div>
      </div>
      <textarea
        id="system-prompt-input"
        class="studio-textarea"
        rows="3"
        placeholder="在此输入自定义系统提示词（例如角色设定、输出格式规范、翻译准则等，留空则不附带系统指令）..."
      ></textarea>
    </div>

    <!-- Main Relay Interaction Card -->
    <div class="relay-card">
      <div class="monitor-header">
        <div class="status-badge-row">
          <div class="pulse-dot" id="pulse-dot"></div>
          <span id="status-title">系统待命</span>
        </div>
        <div style="display:flex;gap:0.45rem;align-items:center;">
          <button class="btn-action" id="clear-chat-btn" onclick="clearConversation()">🗑️ 清空对话</button>
          <button class="btn-action" onclick="copyLatestReply()">📋 复制最新回复</button>
          <button class="btn-danger-sm" id="stop-btn" onclick="stopRelay()" disabled>⏹ 立即停止</button>
        </div>
      </div>

      <!-- Multi-turn Chat History View -->
      <div id="chat-view">
        <div class="chat-history" id="chat-history">
          <div class="chat-empty">暂无对话记录。在下方输入内容开始多轮对话（支持 Ctrl+Enter / Cmd+Enter 发送）。</div>
        </div>
      </div>

      <!-- Single-turn Output View -->
      <div id="single-view" style="display:none;">
        <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.4rem;font-weight:600;">
          单轮响应输出（不携带历史上下文，仅发送当前 System Prompt + 下方输入）：
        </div>
        <div class="single-output-box" id="single-output">等待发送单轮请求...</div>
      </div>

      <!-- User Prompt Input -->
      <div>
        <div style="display:flex;justify-content:space-between;align-items:center;font-size:0.8rem;color:var(--text-muted);margin-bottom:0.35rem;font-weight:600;">
          <span id="prompt-label">输入对话消息</span>
          <span>快捷键: <code>Cmd/Ctrl + Enter</code> 发送</span>
        </div>
        <textarea
          id="user-prompt-input"
          class="studio-textarea"
          rows="4"
          placeholder="在此输入你的问题、指令或待处理文本..."
        ></textarea>
        <div class="input-actions-row">
          <button class="run-btn" id="send-btn" onclick="sendRelayRequest()">🚀 发送请求</button>
        </div>
      </div>
    </div>
  </div>

  <div class="toast hidden" id="toast"></div>

  <script>
    let relayMode = "chat"; // 'chat' | 'single'
    let defaultSystemPrompt = "";
    let chatMessages = []; // [{{ role: 'user' | 'model', content: '...' }}]
    let latestSingleOutput = "";
    let isStreaming = false;
    let activeAbortCtrl = null;

    function showToast(msg) {{
      const t = document.getElementById("toast");
      t.textContent = msg;
      t.classList.remove("hidden");
      clearTimeout(window.__relayToast);
      window.__relayToast = setTimeout(() => t.classList.add("hidden"), 2400);
    }}

    function escapeHtml(str) {{
      return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }}

    function switchRelayMode(mode) {{
      relayMode = mode;
      document.getElementById("tab-chat").classList.toggle("active", mode === "chat");
      document.getElementById("tab-single").classList.toggle("active", mode === "single");
      document.getElementById("chat-view").style.display = mode === "chat" ? "block" : "none";
      document.getElementById("single-view").style.display = mode === "single" ? "block" : "none";
      document.getElementById("clear-chat-btn").style.display = mode === "chat" ? "inline-block" : "none";
      document.getElementById("prompt-label").textContent =
        mode === "chat" ? "输入多轮对话消息" : "输入单轮独立指令 / 文本";
      document.getElementById("send-btn").textContent =
        mode === "chat" ? "🚀 发送对话" : "⚡ 执行单轮生成";
    }}

    function resetSystemPrompt() {{
      document.getElementById("system-prompt-input").value = defaultSystemPrompt;
      showToast("已恢复默认 System Prompt");
    }}

    function clearSystemPrompt() {{
      document.getElementById("system-prompt-input").value = "";
      showToast("已清空 System Prompt");
    }}

    function renderChatHistory() {{
      const box = document.getElementById("chat-history");
      if (!chatMessages.length) {{
        box.innerHTML =
          '<div class="chat-empty">暂无对话记录。在下方输入内容开始多轮对话（支持 Ctrl+Enter / Cmd+Enter 发送）。</div>';
        return;
      }}
      box.innerHTML = chatMessages
        .map((m, idx) => {{
          const isUser = m.role === "user";
          const roleLabel = isUser ? "👤 你 (User)" : "✨ Gemini";
          const cls = isUser ? "msg-item msg-user" : "msg-item msg-model";
          return `
            <div class="${{cls}}">
              <div class="msg-meta">
                <span>${{roleLabel}}</span>
                <div style="display:flex;gap:0.35rem;">
                  <button class="btn-action" onclick="copyMessageAt(${{idx}})">复制</button>
                  <button class="btn-action" onclick="deleteMessageAt(${{idx}})">删除</button>
                </div>
              </div>
              <div class="msg-text" id="msg-text-${{idx}}">${{escapeHtml(m.content)}}</div>
            </div>
          `;
        }})
        .join("");
      box.scrollTop = box.scrollHeight;
    }}

    function copyMessageAt(idx) {{
      const item = chatMessages[idx];
      if (!item) return;
      navigator.clipboard.writeText(item.content || "").then(() => showToast("已复制该条消息 ✓"));
    }}

    function deleteMessageAt(idx) {{
      if (isStreaming) return;
      chatMessages.splice(idx, 1);
      renderChatHistory();
    }}

    function clearConversation() {{
      if (isStreaming) return;
      chatMessages = [];
      latestSingleOutput = "";
      document.getElementById("single-output").textContent = "等待发送单轮请求...";
      renderChatHistory();
      document.getElementById("status-title").textContent = "已清空对话上下文";
    }}

    function copyLatestReply() {{
      let text = "";
      if (relayMode === "single") {{
        text = latestSingleOutput;
      }} else {{
        for (let i = chatMessages.length - 1; i >= 0; i--) {{
          if (chatMessages[i].role === "model" && chatMessages[i].content) {{
            text = chatMessages[i].content;
            break;
          }}
        }}
      }}
      if (!text) {{
        showToast("暂无可复制的回复内容");
        return;
      }}
      navigator.clipboard.writeText(text).then(() => showToast("最新回复已复制 ✓"));
    }}

    function setStreamingUI(running) {{
      isStreaming = running;
      document.getElementById("send-btn").disabled = running;
      document.getElementById("stop-btn").disabled = !running;
      const dot = document.getElementById("pulse-dot");
      if (running) {{
        dot.classList.add("live");
      }} else {{
        dot.classList.remove("live");
      }}
    }}

    async function loadRelayMeta() {{
      try {{
        const res = await fetch("/api/relay/meta");
        const data = await res.json();
        defaultSystemPrompt = data.default_system_prompt || "";
        const sysInput = document.getElementById("system-prompt-input");
        if (!sysInput.value) {{
          sysInput.value = defaultSystemPrompt;
        }}

        const keySelect = document.getElementById("key-select");
        const statusEl = document.getElementById("keys-status-text");
        if (Array.isArray(data.keys) && data.keys.length > 0) {{
          statusEl.innerHTML =
            `🔑 已加载 <strong>${{data.keys.length}}</strong> 个密钥: ` +
            data.keys.map((k) => `<code>${{k.name}}</code> (${{k.masked}})`).join(" · ");
          keySelect.innerHTML =
            `<option value="auto">🔄 自动轮询与故障切换 (${{data.keys.length}} Keys)</option>` +
            data.keys.map((k) => `<option value="${{k.name}}">${{k.name}} (${{k.masked}})</option>`).join("");
        }} else {{
          statusEl.innerHTML =
            `<span style="color:#fb7185;">⚠️ 未检测到有效密钥，请在项目 keys/ 目录下填入 Gemini1.key / gemini2.key</span>`;
        }}
      }} catch (e) {{
        console.error(e);
      }}
    }}

    async function sendRelayRequest() {{
      if (isStreaming) return;
      const promptEl = document.getElementById("user-prompt-input");
      const userText = promptEl.value.trim();
      if (!userText) {{
        showToast("请输入要发送的内容");
        promptEl.focus();
        return;
      }}

      const systemPrompt = document.getElementById("system-prompt-input").value.trim();
      const model = getSelectedModel();
      const reasoningEffort = document.getElementById("reasoning-select").value;
      const temperature = parseFloat(document.getElementById("temp-input").value) || 0.7;
      const preferredKey = document.getElementById("key-select").value;

      let requestBody = {{
        mode: relayMode,
        system_prompt: systemPrompt,
        model: model,
        reasoning_effort: reasoningEffort,
        temperature: temperature,
        preferred_key: preferredKey,
      }};

      let modelMsgIndex = -1;

      if (relayMode === "chat") {{
        chatMessages.push({{ role: "user", content: userText }});
        promptEl.value = "";
        requestBody.messages = chatMessages.map((m) => ({{ role: m.role, content: m.content }}));
        chatMessages.push({{ role: "model", content: "" }});
        modelMsgIndex = chatMessages.length - 1;
        renderChatHistory();
      }} else {{
        requestBody.prompt = userText;
        latestSingleOutput = "";
        document.getElementById("single-output").textContent = "";
      }}

      setStreamingUI(true);
      activeAbortCtrl = new AbortController();

      try {{
        const res = await fetch("/api/relay/stream", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(requestBody),
          signal: activeAbortCtrl.signal,
        }});

        if (!res.ok) {{
          let errDetail = "请求失败";
          try {{
            const errJson = await res.json();
            errDetail = errJson.detail || errJson.error || errDetail;
          }} catch (_) {{}}
          showToast(errDetail);
          document.getElementById("status-title").textContent = `❌ ${{errDetail}}`;
          if (relayMode === "chat" && modelMsgIndex >= 0 && !chatMessages[modelMsgIndex].content) {{
            chatMessages.splice(modelMsgIndex, 1);
            renderChatHistory();
          }}
          setStreamingUI(false);
          return;
        }}

        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        while (true) {{
          const {{ done, value }} = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, {{ stream: true }});
          const lines = buffer.split("\\n");
          buffer = lines.pop() || "";

          for (const rawLine of lines) {{
            const line = rawLine.trim();
            if (!line.startsWith("data:")) continue;
            const jsonStr = line.slice(5).trim();
            if (!jsonStr) continue;
            try {{
              const ev = JSON.parse(jsonStr);
              const t = (ev.type || "").trim();
              if (t === "status") {{
                document.getElementById("status-title").textContent = ev.msg;
              }} else if (t === "token") {{
                if (relayMode === "chat" && modelMsgIndex >= 0) {{
                  chatMessages[modelMsgIndex].content += ev.content;
                  const el = document.getElementById(`msg-text-${{modelMsgIndex}}`);
                  if (el) el.textContent = chatMessages[modelMsgIndex].content;
                  const histBox = document.getElementById("chat-history");
                  histBox.scrollTop = histBox.scrollHeight;
                }} else {{
                  latestSingleOutput += ev.content;
                  document.getElementById("single-output").textContent = latestSingleOutput;
                }}
              }} else if (t === "error") {{
                document.getElementById("status-title").textContent = `❌ ${{ev.error}}`;
                showToast(ev.error);
              }} else if (t === "stopped") {{
                document.getElementById("status-title").textContent = "⏹ 已手动停止生成";
              }} else if (t === "done") {{
                document.getElementById("status-title").textContent = `✓ 生成完成 (Key: ${{ev.key || "auto"}})`;
              }}
            }} catch (_) {{}}
          }}
        }}
      }} catch (err) {{
        if (err.name === "AbortError") {{
          document.getElementById("status-title").textContent = "⏹ 已手动停止生成";
        }} else {{
          document.getElementById("status-title").textContent = `❌ 网络或流异常: ${{err.message}}`;
        }}
      }} finally {{
        setStreamingUI(false);
        activeAbortCtrl = null;
      }}
    }}

    async function stopRelay() {{
      if (activeAbortCtrl) {{
        activeAbortCtrl.abort();
      }}
      try {{
        await fetch("/api/relay/stop", {{ method: "POST" }});
      }} catch (_) {{}}
      setStreamingUI(false);
    }}

    document.getElementById("user-prompt-input").addEventListener("keydown", (e) => {{
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {{
        e.preventDefault();
        sendRelayRequest();
      }}
    }});

    function getSelectedModel() {{
      const sel = document.getElementById("model-select").value;
      if (sel === "__custom__") {{
        return document.getElementById("custom-model-input").value.trim() || "gemini-3.5-flash-lite";
      }}
      return sel || "gemini-3.5-flash-lite";
    }}

    function updateQuickModelButtons() {{
      const cur = document.getElementById("model-select").value;
      const b35 = document.getElementById("quick-35fl");
      const b31 = document.getElementById("quick-31fl");
      if (b35) {{
        b35.style.borderColor = cur === "gemini-3.5-flash-lite" ? "rgba(56,189,248,0.6)" : "";
        b35.style.color = cur === "gemini-3.5-flash-lite" ? "#38bdf8" : "";
      }}
      if (b31) {{
        b31.style.borderColor = cur === "gemini-3.1-flash-lite" ? "rgba(56,189,248,0.6)" : "";
        b31.style.color = cur === "gemini-3.1-flash-lite" ? "#38bdf8" : "";
      }}
    }}

    function setModelQuick(modelId) {{
      const sel = document.getElementById("model-select");
      sel.value = modelId;
      onModelSelectChange();
      showToast(`已切换模型: ${{modelId}}`);
    }}

    function onModelSelectChange() {{
      const sel = document.getElementById("model-select").value;
      const customEl = document.getElementById("custom-model-input");
      customEl.style.display = sel === "__custom__" ? "block" : "none";
      updateQuickModelButtons();
    }}

    updateQuickModelButtons();
    loadRelayMeta();
  </script>
</body>
</html>"""
