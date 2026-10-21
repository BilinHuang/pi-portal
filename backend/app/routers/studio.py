"""Story Studio Router & Gemini API Multi-Key Streaming Engine (Feature A).

Supports:
- Multi-key loading and automatic failover/round-robin from `keys/*.key` (e.g. `Gemini1.key`, `gemini2.key`)
- 3 core creation modes:
  1. 错乱重写扩写 (Rewrite & Expand via scene decomposition + deep expansion)
  2. 剧情承接续写 (Context Continue via global summary + tail physical hook)
  3. 灵感起草全篇 (Idea to Full Story via multi-scene outline + sequential writing)
- Auto-loaded & user-editable System Prompts per mode
- Default `high` reasoning/thinking effort (`thinkingConfig`) with automatic fallback
- Real-time SSE token streaming, manual stop, and output persistence
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import KEYS_DIR, STUDIO_INPUT_DIR, STUDIO_OUTPUT_DIR
from ..database import get_db
from ..dependencies import CurrentIdentity, can_launch_service, get_current_identity
from ..models import Service, User
from .ai import _check_and_reset_daily

router = APIRouter(prefix="/api/studio", tags=["studio"])

STUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
STUDIO_INPUT_DIR.mkdir(parents=True, exist_ok=True)
KEYS_DIR.mkdir(parents=True, exist_ok=True)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Default models list (Gemini Flash Lite / Flash / Pro)
AVAILABLE_MODELS = [
    {"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash Lite"},
    {"id": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash Lite"},
]

# Default System Prompts for the 3 modes (auto-loaded in UI, user-editable)
DEFAULT_SYSTEM_PROMPTS: Dict[str, str] = {
    "rewrite": (
        "你是一位擅长硬核严肃文学与高张力戏剧冲突的小说家。\n"
        "创作规范：\n"
        "1. 叙事基调：冷峻客观的第三人称视角，注重微表情、肌肉绷紧、呼吸变化等极具真实感的生理反应。\n"
        "2. 动作具象化：严禁一笔带过。将器物的冰冷触感、受力痕迹、动作的施加与承接过程详尽拆解展开。\n"
        "3. 文本克制：绝不进行全知视角的道德评价与居高临下的旁白说教，完全通过肢体动作与心理压迫推动高潮。"
    ),
    "continue": (
        "你是一位擅长高张力严肃文学的小说家。\n"
        "创作要求：采用客观冷峻的第三人称视角，注重身体微动作、潜台词与生理应激反应。不进行任何道德评判，让戏剧冲突自然爆发。"
    ),
    "idea": (
        "你是一位擅长硬核严肃文学的虚构小说家。\n"
        "创作要求：客观冷峻的第三人称视角，注重环境白描、身体本能与心理潜台词。不进行任何道德评判，让戏剧冲突自然具象化呈现。"
    ),
}

# Thinking budget mapping for reasoning effort
THINKING_BUDGET_MAP: Dict[str, Optional[int]] = {
    "high": 8192,
    "medium": 4096,
    "low": 1024,
    "none": 0,
}

SAFETY_SETTINGS_BLOCK_NONE = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
]


def _natural_sort_key(s: str) -> List[Any]:
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]


# ==================== Multi-Key Pool Manager ====================
class KeyPoolManager:
    """Scans `keys/*.key` (e.g. Gemini1.key, gemini2.key) and rotates/fails over automatically."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rr_index = 0

    def load_keys(self) -> List[Dict[str, str]]:
        """Read all valid *.key files from KEYS_DIR."""
        keys: List[Dict[str, str]] = []
        if KEYS_DIR.exists():
            key_files = sorted(
                [p for p in KEYS_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".key"],
                key=lambda p: _natural_sort_key(p.name),
            )
            for kf in key_files:
                try:
                    raw_lines = kf.read_text(encoding="utf-8", errors="ignore").splitlines()
                    valid_lines = [
                        line.strip()
                        for line in raw_lines
                        if line.strip()
                        and not line.strip().startswith("#")
                        and not line.strip().startswith("//")
                        and not line.strip().startswith("YOUR_")
                    ]
                    if valid_lines:
                        k_val = valid_lines[0]
                        masked = (
                            f"{k_val[:6]}...{k_val[-4:]}"
                            if len(k_val) > 12
                            else "••••••"
                        )
                        keys.append(
                            {
                                "name": kf.name,
                                "key": k_val,
                                "masked": masked,
                            }
                        )
                except Exception:
                    continue

        # Fallback to environment variable if no key files have valid keys
        env_key = os.getenv("GEMINI_API_KEY", "").strip()
        if env_key and not any(item["key"] == env_key for item in keys):
            masked = f"{env_key[:6]}...{env_key[-4:]}" if len(env_key) > 12 else "••••••"
            keys.append({"name": "ENV:GEMINI_API_KEY", "key": env_key, "masked": masked})

        return keys

    def get_ordered_candidates(self, preferred_name: Optional[str] = None) -> List[Dict[str, str]]:
        """Return candidate keys starting with preferred_name or next round-robin index."""
        keys = self.load_keys()
        if not keys:
            return []

        if preferred_name and preferred_name != "auto":
            preferred = [k for k in keys if k["name"] == preferred_name]
            others = [k for k in keys if k["name"] != preferred_name]
            if preferred:
                return preferred + others

        with self._lock:
            start = self._rr_index % len(keys)
            self._rr_index = (self._rr_index + 1) % len(keys)
        return keys[start:] + keys[:start]


key_pool = KeyPoolManager()


# ==================== Task Manager (SSE Broadcast & Stop Control) ====================
class StudioTaskManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.status = "idle"
        self.status_msg = "系统待命"
        self.full_content = ""
        self.active_key_name = ""
        self.stop_requested = False
        self.active_resp: Any = None
        self.worker_thread: Optional[threading.Thread] = None
        self.listeners: List[queue.Queue[str]] = []

    def register_listener(self) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue(maxsize=400)
        with self.lock:
            self.listeners.append(q)
        return q

    def unregister_listener(self, q: queue.Queue[str]) -> None:
        with self.lock:
            if q in self.listeners:
                self.listeners.remove(q)

    def broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        msg = f"data: {json.dumps({'type': event_type, **data}, ensure_ascii=False)}\n\n"
        with self.lock:
            active_listeners = list(self.listeners)
        for q in active_listeners:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def stop(self) -> bool:
        with self.lock:
            if self.status != "running":
                return True
            self.stop_requested = True
            self.status = "stopped"
            self.status_msg = "⏹ 已手动中止生成，连接已释放"
            if self.active_resp:
                try:
                    self.active_resp.close()
                except Exception:
                    pass
                self.active_resp = None
            th = self.worker_thread

        self.broadcast("status", {"msg": "⏹ 已手动中止生成，连接已释放。"})
        self.broadcast("stopped", {})

        if th and th.is_alive() and th != threading.current_thread():
            th.join(timeout=1.5)
        return True


studio_mgr = StudioTaskManager()


# ==================== Gemini HTTP / SSE Client with Multi-Key Failover ====================
def _build_gemini_payload(
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.85,
    reasoning_effort: str = "high",
    include_thinking: bool = True,
) -> Dict[str, Any]:
    gen_config: Dict[str, Any] = {
        "temperature": temperature,
        "topP": 0.92,
    }
    if include_thinking and reasoning_effort in THINKING_BUDGET_MAP:
        budget = THINKING_BUDGET_MAP[reasoning_effort]
        if budget is not None and budget > 0:
            gen_config["thinkingConfig"] = {"thinkingBudget": budget}

    payload: Dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen_config,
        "safetySettings": SAFETY_SETTINGS_BLOCK_NONE,
    }
    if system_prompt and system_prompt.strip():
        payload["systemInstruction"] = {"parts": [{"text": system_prompt.strip()}]}
    return payload


def call_gemini_sync(
    prompt: str,
    system_prompt: str = "",
    model: str = "gemini-3.5-flash-lite",
    temperature: float = 0.4,
    reasoning_effort: str = "high",
    preferred_key: Optional[str] = None,
) -> Tuple[str, str]:
    """Call Gemini generateContent synchronously with multi-key failover.

    Returns (response_text, used_key_name).
    """
    candidates = key_pool.get_ordered_candidates(preferred_key)
    if not candidates:
        raise RuntimeError("未检测到有效 API Key，请在 keys/ 目录下配置 Gemini1.key 等密钥文件。")

    last_err = ""
    for item in candidates:
        if studio_mgr.stop_requested:
            return "", item["name"]

        key_name = item["name"]
        api_key = item["key"]

        for use_thinking in (True, False):
            payload = _build_gemini_payload(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                include_thinking=use_thinking,
            )
            url = f"{GEMINI_API_BASE}/{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(api_key)}"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                    cands = raw.get("candidates") or []
                    if not cands:
                        block_reason = raw.get("promptFeedback", {}).get("blockReason", "未知原因")
                        raise RuntimeError(f"模型未返回候选内容 (blockReason={block_reason})")
                    parts = cands[0].get("content", {}).get("parts") or []
                    text_chunks = [
                        p.get("text", "")
                        for p in parts
                        if not p.get("thought", False) and p.get("text")
                    ]
                    return "".join(text_chunks).strip(), key_name
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
                # If 400 due to thinkingConfig not supported on this model, retry without thinkingConfig
                if e.code == 400 and use_thinking and ("thinking" in err_body.lower() or "budget" in err_body.lower()):
                    continue
                last_err = f"[{key_name}] HTTP {e.code}: {err_body[:200]}"
                # If rate-limited (429) or quota/permission issue (403/503), failover to next key
                if e.code in (429, 403, 500, 503) and len(candidates) > 1:
                    studio_mgr.broadcast(
                        "status",
                        {"msg": f"⚠️ {key_name} 触发限流/异常 ({e.code})，自动切换下一个 Key..."},
                    )
                    break
                break
            except Exception as e:
                last_err = f"[{key_name}] {e}"
                break

    raise RuntimeError(f"调用 Gemini API 失败: {last_err}")


def stream_gemini_tokens(
    prompt: str,
    system_prompt: str = "",
    model: str = "gemini-3.5-flash-lite",
    temperature: float = 0.85,
    reasoning_effort: str = "high",
    preferred_key: Optional[str] = None,
) -> Generator[str, None, None]:
    """Stream tokens from Gemini streamGenerateContent?alt=sse with multi-key failover."""
    candidates = key_pool.get_ordered_candidates(preferred_key)
    if not candidates:
        raise RuntimeError("未检测到有效 API Key，请在 keys/ 目录下放入 Gemini1.key 等文件。")

    last_err = ""
    for item in candidates:
        if studio_mgr.stop_requested:
            return

        key_name = item["name"]
        api_key = item["key"]

        for use_thinking in (True, False):
            if studio_mgr.stop_requested:
                return

            payload = _build_gemini_payload(
                prompt=prompt,
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
                resp = urllib.request.urlopen(req, timeout=600)
                with studio_mgr.lock:
                    studio_mgr.active_resp = resp
                    studio_mgr.active_key_name = key_name

                notified_thinking = False
                for raw_line in resp:
                    if studio_mgr.stop_requested:
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
                        continue
                    parts = cands[0].get("content", {}).get("parts") or []
                    for p in parts:
                        if p.get("thought", False):
                            if not notified_thinking:
                                notified_thinking = True
                                studio_mgr.broadcast(
                                    "status",
                                    {"msg": f"🧠 [{key_name}] 模型正在深度推理 (High Reasoning)..."},
                                )
                            continue
                        txt = p.get("text", "")
                        if txt:
                            yield txt
                return
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
                if e.code == 400 and use_thinking and ("thinking" in err_body.lower() or "budget" in err_body.lower()):
                    continue
                last_err = f"[{key_name}] HTTP {e.code}: {err_body[:200]}"
                if e.code in (429, 403, 500, 503) and len(candidates) > 1:
                    studio_mgr.broadcast(
                        "status",
                        {"msg": f"⚠️ {key_name} 触发限额 ({e.code})，自动切换备用 Key..."},
                    )
                    break
                break
            except Exception as e:
                last_err = f"[{key_name}] {e}"
                break
            finally:
                with studio_mgr.lock:
                    if resp:
                        try:
                            resp.close()
                        except Exception:
                            pass
                    studio_mgr.active_resp = None

    if not studio_mgr.stop_requested:
        raise RuntimeError(f"流式生成失败: {last_err}")


def _save_output_file(mode_prefix: str, content: str) -> Optional[str]:
    if not content or not content.strip():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{mode_prefix}_{ts}.txt"
    fpath = STUDIO_OUTPUT_DIR / fname
    fpath.write_text(content.strip() + "\n", encoding="utf-8")
    return fname


# ==================== Worker Threads for 3 Modes ====================
def _run_rewrite_worker(
    raw_text: str,
    system_prompt: str,
    model: str,
    reasoning_effort: str,
    preferred_key: str,
) -> None:
    with studio_mgr.lock:
        studio_mgr.status = "running"
        studio_mgr.status_msg = "阶段 1/2：正在深度解构剧情、动作行迹与角色位阶..."
        studio_mgr.full_content = ""
        studio_mgr.stop_requested = False
    studio_mgr.broadcast("status", {"msg": studio_mgr.status_msg})

    split_prompt = f"""以下是一段原始、语序混乱且粗糙的剧情文本。
请梳理其发生的先后因果，将其重构拆解为 3 到 8 个独立且逻辑连贯的情节场景（Scene）。

你必须对每一幕的戏剧冲突、角色权力关系和器物进行细致提取。
严格输出标准 JSON 数组，严禁包含任何前缀、解释、Markdown 标记。格式如下：
[
  {{
    "id": 1,
    "plot_title": "场景核心事件（如：书房立规、更衣审视）",
    "leading_agent": "主控方姓名/称谓（施加控制、掌握主动权的角色）",
    "receptive_agent": "承制方姓名/称谓（承受动作、处于受制/顺应/克制状态的角色）",
    "props_and_instruments": ["出现的道具", "器物", "衣物或拘束介质（无则填无）"],
    "action_dynamics": "本幕具体的动作行迹、身体控制姿势、具体行为轨迹与物理交互",
    "power_and_mindset": "双方在这一幕的权力反差、心理压迫感与深层生理反应",
    "plot_points": "情节因果线索与发生先后的关键事件点",
    "raw_source": "该场景对应的原始粗稿段落"
  }}
]

原始粗稿：
{raw_text}"""

    try:
        resp_text, used_key = call_gemini_sync(
            prompt=split_prompt,
            system_prompt="你是一个专业的剧本结构分析师。只输出严格标准的 JSON 数组数据。",
            model=model,
            temperature=0.4,
            reasoning_effort=reasoning_effort,
            preferred_key=preferred_key,
        )
        if studio_mgr.stop_requested:
            return

        cleaned = re.sub(r"^```json\s*", "", resp_text, flags=re.MULTILINE)
        cleaned = re.sub(r"^```\s*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

        try:
            menu = json.loads(cleaned)
            if not isinstance(menu, list) or not menu:
                raise ValueError("Empty list")
        except Exception:
            chunks = [c.strip() for c in raw_text.split("\n\n") if c.strip()] or [raw_text]
            menu = [
                {
                    "id": i + 1,
                    "plot_title": f"第 {i + 1} 幕",
                    "leading_agent": "主控方",
                    "receptive_agent": "承制方",
                    "props_and_instruments": ["常规道具"],
                    "action_dynamics": "基于原文动作推进",
                    "power_and_mindset": "服从与掌控博弈",
                    "plot_points": "原文段落推进",
                    "raw_source": c,
                }
                for i, c in enumerate(chunks)
            ]

        total = len(menu)
        for item in menu:
            if studio_mgr.stop_requested:
                break
            cid = item.get("id", 1)
            title = item.get("plot_title", f"第 {cid} 幕")
            leading = item.get("leading_agent", "主控方")
            receptive = item.get("receptive_agent", "承制方")
            props_list = item.get("props_and_instruments", [])
            props = ", ".join(props_list) if isinstance(props_list, list) else str(props_list)
            actions = item.get("action_dynamics", "")
            tension = item.get("power_and_mindset", "")
            points = item.get("plot_points", "")
            raw_seg = item.get("raw_source", raw_text[:1500])

            with studio_mgr.lock:
                studio_mgr.status_msg = f"阶段 2/2：正在精修扩写第 [{cid}/{total}] 幕：{title}"
            studio_mgr.broadcast("status", {"msg": studio_mgr.status_msg})

            expand_prompt = f"""【深度场景执笔与扩写任务】

【本幕核心角色配置与动态】：
- 主控方：{leading}
- 承制方：{receptive}
- 登场器物/介质：{props}
- 核心物理交互与动作行迹：{actions}
- 权力压迫与生理心理状态：{tension}
- 本幕核心情节推进：{points}

【原始粗稿参考】：
{raw_seg}

【执笔要求】：
1. 严格以【主控方】与【承制方】的互动为核心，将列出的【核心物理交互】与【器物使用】逐一具象化描写，禁止笼统略过。
2. 细致刻画器物与身体接触的冷热感、施压与受压过程、呼吸频率与生理应激反馈。
3. 修正原始粗稿的病句与错乱语序，使整段文字具备长篇小说的厚重感与画面压迫力。
4. 篇幅必须充分展开，输出字数需大幅超越原始素材，严禁写摘要。
5. 直接输出本幕故事正文，不要输出任何额外解释、标题或后记。"""

            is_first_token = True
            for token in stream_gemini_tokens(
                prompt=expand_prompt,
                system_prompt=system_prompt,
                model=model,
                temperature=0.82,
                reasoning_effort=reasoning_effort,
                preferred_key=preferred_key,
            ):
                if studio_mgr.stop_requested:
                    break
                if is_first_token:
                    token = token.lstrip("\r\n")
                    if not token:
                        continue
                    is_first_token = False
                    header_line = f"### 第 {cid} 幕：{title}\n\n"
                    prefix = ("\n\n" if studio_mgr.full_content and not studio_mgr.full_content.endswith("\n\n") else "") + header_line
                    with studio_mgr.lock:
                        studio_mgr.full_content += prefix
                    studio_mgr.broadcast("token", {"content": prefix})

                with studio_mgr.lock:
                    studio_mgr.full_content += token
                studio_mgr.broadcast("token", {"content": token})

        saved_name = _save_output_file("rewrite", studio_mgr.full_content)
        with studio_mgr.lock:
            if not studio_mgr.stop_requested:
                studio_mgr.status = "done"
                suffix = f" (已存至 {saved_name})" if saved_name else ""
                studio_mgr.status_msg = f"✓ 全篇分幕重写扩写完成！{suffix}"
        if not studio_mgr.stop_requested:
            studio_mgr.broadcast("status", {"msg": studio_mgr.status_msg})
            studio_mgr.broadcast("done", {"saved_file": saved_name})

    except Exception as exc:
        with studio_mgr.lock:
            studio_mgr.status = "error"
            studio_mgr.status_msg = f"❌ 错误: {exc}"
        studio_mgr.broadcast("status", {"msg": studio_mgr.status_msg})
        studio_mgr.broadcast("done", {"error": str(exc)})


def _run_continue_worker(
    context: str,
    direction: str,
    system_prompt: str,
    model: str,
    reasoning_effort: str,
    preferred_key: str,
) -> None:
    with studio_mgr.lock:
        studio_mgr.status = "running"
        studio_mgr.status_msg = "阶段 1/2：正在提炼前文全局概括与角色状态快照..."
        studio_mgr.full_content = ""
        studio_mgr.stop_requested = False
    studio_mgr.broadcast("status", {"msg": studio_mgr.status_msg})

    try:
        if len(context) > 1500:
            summary_prompt = f"""请对以下已有小说内容进行高密度概括与梳理：
1. 前情核心脉络（150字以内交代清楚发生了什么）。
2. 主要人物当前的关系、处境与心理动机。
3. 文本结尾处正处于什么物理场景，悬而未决的核心矛盾是什么。

文本内容：
{context}"""
            summary_text, _ = call_gemini_sync(
                prompt=summary_prompt,
                system_prompt="你是一个严谨的剧情整理助手，只输出客观要点概括。",
                model=model,
                temperature=0.35,
                reasoning_effort=reasoning_effort,
                preferred_key=preferred_key,
            )
        else:
            summary_text = "前文较短，直接基于全文衔接。"

        if studio_mgr.stop_requested:
            return

        tail_text = context[-2000:]
        with studio_mgr.lock:
            studio_mgr.status_msg = "阶段 2/2：正在紧密承接结尾展开高张力续写..."
        studio_mgr.broadcast("status", {"msg": studio_mgr.status_msg})

        cont_prompt = f"""【小说承接续写任务】

【全局前情与角色状态概括】：
{summary_text}

【接续点（前文结尾片段）】：
-------------------------
...{tail_text}
-------------------------

【续写要求】：
1. 紧密承接上面结尾片段中角色的即时动作停顿、生理反应和环境状态，严禁复述前文，直接切入下一刻。
2. 剧情走向参考：{direction if direction else "顺应前文积累的内在张力自然爆发，推进核心冲突。"}
3. 保持与前情概括中的人物性格和动机高度一致，强化感官细节、压迫感与生理本能反馈。
4. 篇幅充分展开，直接输出续写正文，不要输出任何开场白、标题或后记。"""

        is_first_token = True
        for token in stream_gemini_tokens(
            prompt=cont_prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=0.85,
            reasoning_effort=reasoning_effort,
            preferred_key=preferred_key,
        ):
            if studio_mgr.stop_requested:
                break
            if is_first_token:
                token = token.lstrip("\r\n")
                if not token:
                    continue
                is_first_token = False
            with studio_mgr.lock:
                studio_mgr.full_content += token
            studio_mgr.broadcast("token", {"content": token})

        saved_name = _save_output_file("continue", studio_mgr.full_content)
        with studio_mgr.lock:
            if not studio_mgr.stop_requested:
                studio_mgr.status = "done"
                suffix = f" (已存至 {saved_name})" if saved_name else ""
                studio_mgr.status_msg = f"✓ 剧情承接续写完成！{suffix}"
        if not studio_mgr.stop_requested:
            studio_mgr.broadcast("status", {"msg": studio_mgr.status_msg})
            studio_mgr.broadcast("done", {"saved_file": saved_name})

    except Exception as exc:
        with studio_mgr.lock:
            studio_mgr.status = "error"
            studio_mgr.status_msg = f"❌ 错误: {exc}"
        studio_mgr.broadcast("status", {"msg": studio_mgr.status_msg})
        studio_mgr.broadcast("done", {"error": str(exc)})


def _run_idea_worker(
    idea: str,
    system_prompt: str,
    model: str,
    reasoning_effort: str,
    preferred_key: str,
) -> None:
    with studio_mgr.lock:
        studio_mgr.status = "running"
        studio_mgr.status_msg = "阶段 1/2：正在根据核心创意推演场景分幕大纲..."
        studio_mgr.full_content = ""
        studio_mgr.stop_requested = False
    studio_mgr.broadcast("status", {"msg": studio_mgr.status_msg})

    outline_prompt = f"""基于以下创意梗概，设计一部具有强烈戏剧张力和深层人性博弈的故事。
将其拆解规划为 3 到 5 个递进的场景分幕。
严格输出标准 JSON 数组，严禁输出任何额外说明。格式如下：
[
  {{
    "id": 1,
    "title": "分幕标题",
    "scene_goal": "该幕核心冲突与事件目标",
    "atmosphere": "环境色调与心理压迫点"
  }}
]

【故事创意】：
{idea}"""

    try:
        outline_resp, _ = call_gemini_sync(
            prompt=outline_prompt,
            system_prompt="你是一个专业的小说架构师。只返回标准 JSON 数组。",
            model=model,
            temperature=0.5,
            reasoning_effort=reasoning_effort,
            preferred_key=preferred_key,
        )
        if studio_mgr.stop_requested:
            return

        cleaned = re.sub(r"^```json\s*", "", outline_resp, flags=re.MULTILINE)
        cleaned = re.sub(r"^```\s*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

        try:
            scenes = json.loads(cleaned)
            if not isinstance(scenes, list) or not scenes:
                raise ValueError("Invalid scenes list")
        except Exception:
            scenes = [
                {
                    "id": 1,
                    "title": "序幕与核心对峙",
                    "scene_goal": "展开核心冲突与人物关系张力",
                    "atmosphere": "冷峻压抑",
                }
            ]

        total = len(scenes)
        running_summary = f"核心背景：{idea}\n"

        for sc in scenes:
            if studio_mgr.stop_requested:
                break
            sid = sc.get("id", 1)
            stitle = sc.get("title", f"第 {sid} 幕")
            sgoal = sc.get("scene_goal", sc.get("goal", ""))
            satmos = sc.get("atmosphere", sc.get("atmos", ""))

            with studio_mgr.lock:
                studio_mgr.status_msg = f"阶段 2/2：正在执笔创作第 [{sid}/{total}] 幕：{stitle}"
            studio_mgr.broadcast("status", {"msg": studio_mgr.status_msg})

            scene_prompt = f"""【执笔创作第 {sid} 幕】
故事背景：{idea}
前情概述：{running_summary}

当前幕目标：{stitle} - {sgoal}
氛围与感官重点：{satmos}

写作规范：
1. 采用客观而极具张力的第三人称视角，将该分幕的目标彻底具象化为生动的情节。
2. 细致刻画环境白描、身体本能与心理潜台词，篇幅充分展开（不得草草带过）。
3. 直接输出这一幕的故事正文，不写标题或解释。"""

            is_first_token = True
            for token in stream_gemini_tokens(
                prompt=scene_prompt,
                system_prompt=system_prompt,
                model=model,
                temperature=0.85,
                reasoning_effort=reasoning_effort,
                preferred_key=preferred_key,
            ):
                if studio_mgr.stop_requested:
                    break
                if is_first_token:
                    token = token.lstrip("\r\n")
                    if not token:
                        continue
                    is_first_token = False
                    header_line = f"## 第 {sid} 幕：{stitle}\n\n"
                    prefix = ("\n\n" if studio_mgr.full_content and not studio_mgr.full_content.endswith("\n\n") else "") + header_line
                    with studio_mgr.lock:
                        studio_mgr.full_content += prefix
                    studio_mgr.broadcast("token", {"content": prefix})

                with studio_mgr.lock:
                    studio_mgr.full_content += token
                studio_mgr.broadcast("token", {"content": token})

            running_summary += f"\n第 {sid} 幕完成了：{sgoal}。"

        saved_name = _save_output_file("idea", studio_mgr.full_content)
        with studio_mgr.lock:
            if not studio_mgr.stop_requested:
                studio_mgr.status = "done"
                suffix = f" (已存至 {saved_name})" if saved_name else ""
                studio_mgr.status_msg = f"✓ 灵感全篇创作完成！{suffix}"
        if not studio_mgr.stop_requested:
            studio_mgr.broadcast("status", {"msg": studio_mgr.status_msg})
            studio_mgr.broadcast("done", {"saved_file": saved_name})

    except Exception as exc:
        with studio_mgr.lock:
            studio_mgr.status = "error"
            studio_mgr.status_msg = f"❌ 错误: {exc}"
        studio_mgr.broadcast("status", {"msg": studio_mgr.status_msg})
        studio_mgr.broadcast("done", {"error": str(exc)})


# ==================== Request Schemas ====================
class RewriteStartRequest(BaseModel):
    text: str
    system_prompt: Optional[str] = None
    model: str = "gemini-3.5-flash-lite"
    reasoning_effort: str = "high"
    preferred_key: str = "auto"


class ContinueStartRequest(BaseModel):
    context: str
    direction: Optional[str] = ""
    system_prompt: Optional[str] = None
    model: str = "gemini-3.5-flash-lite"
    reasoning_effort: str = "high"
    preferred_key: str = "auto"


class IdeaStartRequest(BaseModel):
    idea: str
    system_prompt: Optional[str] = None
    model: str = "gemini-3.5-flash-lite"
    reasoning_effort: str = "high"
    preferred_key: str = "auto"


def _verify_and_deduct_quota(identity: CurrentIdentity, db: Session) -> None:
    """Deduct 1 AI call from logged-in user's quota if applicable."""
    if identity.user:
        user = db.query(User).filter(User.id == identity.user.id).first()
        if user:
            _check_and_reset_daily(user, db)
            if user.role != "admin" and user.ai_daily_limit != -1:
                if user.ai_used_today >= user.ai_daily_limit:
                    raise HTTPException(
                        status_code=429,
                        detail=f"今日 AI 配额已用尽 ({user.ai_daily_limit} 次)，请联系管理员提升限额",
                    )
            user.ai_used_today += 1
            db.commit()


def _require_studio_access(identity: CurrentIdentity, db: Session) -> None:
    svc = db.query(Service).filter(Service.slug == "story-studio").first()
    if svc and not can_launch_service(identity, svc):
        raise HTTPException(status_code=404, detail="Not Found")


# ==================== API Endpoints ====================
@router.get("/meta")
def get_studio_metadata(
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Return available keys (masked), models, default system prompts, and saved outputs."""
    _require_studio_access(identity, db)
    loaded_keys = [
        {"name": k["name"], "masked": k["masked"]}
        for k in key_pool.load_keys()
    ]
    outputs = []
    if STUDIO_OUTPUT_DIR.exists():
        for p in sorted(STUDIO_OUTPUT_DIR.glob("*.txt"), key=lambda x: x.stat().st_mtime, reverse=True)[:25]:
            outputs.append(
                {
                    "name": p.name,
                    "size": p.stat().st_size,
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
                }
            )
    return {
        "keys": loaded_keys,
        "keys_dir": str(KEYS_DIR),
        "models": AVAILABLE_MODELS,
        "default_prompts": DEFAULT_SYSTEM_PROMPTS,
        "outputs": outputs,
    }


@router.get("/outputs/{filename}")
def get_studio_output_file(
    filename: str,
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    _require_studio_access(identity, db)
    safe_name = Path(filename).name
    target = (STUDIO_OUTPUT_DIR / safe_name).resolve()
    if not str(target).startswith(str(STUDIO_OUTPUT_DIR.resolve())) or not target.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    return {
        "name": safe_name,
        "content": target.read_text(encoding="utf-8", errors="replace"),
    }


@router.get("/events")
def studio_sse_events(
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    _require_studio_access(identity, db)
    q = studio_mgr.register_listener()

    def event_stream():
        try:
            with studio_mgr.lock:
                snapshot = {
                    "type": "init",
                    "status": studio_mgr.status,
                    "status_msg": studio_mgr.status_msg,
                    "content": studio_mgr.full_content,
                }
            yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield msg
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            studio_mgr.unregister_listener(q)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/stop")
def stop_studio_task(
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    _require_studio_access(identity, db)
    studio_mgr.stop()
    return {"success": True}


@router.post("/start_rewrite")
def start_rewrite_api(
    payload: RewriteStartRequest,
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    _require_studio_access(identity, db)
    with studio_mgr.lock:
        if studio_mgr.status == "running" or (studio_mgr.worker_thread and studio_mgr.worker_thread.is_alive()):
            raise HTTPException(status_code=400, detail="上一任务仍在运行中，请先点击停止")

    raw_text = payload.text.strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="请输入或粘贴待重写的粗稿内容")

    _verify_and_deduct_quota(identity, db)
    sys_prompt = (payload.system_prompt or "").strip() or DEFAULT_SYSTEM_PROMPTS["rewrite"]

    th = threading.Thread(
        target=_run_rewrite_worker,
        args=(raw_text, sys_prompt, payload.model.strip(), payload.reasoning_effort, payload.preferred_key),
        daemon=True,
    )
    studio_mgr.worker_thread = th
    th.start()
    return {"status": "started"}


@router.post("/start_continue")
def start_continue_api(
    payload: ContinueStartRequest,
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    _require_studio_access(identity, db)
    with studio_mgr.lock:
        if studio_mgr.status == "running" or (studio_mgr.worker_thread and studio_mgr.worker_thread.is_alive()):
            raise HTTPException(status_code=400, detail="上一任务仍在运行中，请先点击停止")

    context = payload.context.strip()
    if not context:
        raise HTTPException(status_code=400, detail="请输入或粘贴前文内容")

    _verify_and_deduct_quota(identity, db)
    sys_prompt = (payload.system_prompt or "").strip() or DEFAULT_SYSTEM_PROMPTS["continue"]

    th = threading.Thread(
        target=_run_continue_worker,
        args=(
            context,
            (payload.direction or "").strip(),
            sys_prompt,
            payload.model.strip(),
            payload.reasoning_effort,
            payload.preferred_key,
        ),
        daemon=True,
    )
    studio_mgr.worker_thread = th
    th.start()
    return {"status": "started"}


@router.post("/start_idea")
def start_idea_api(
    payload: IdeaStartRequest,
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    _require_studio_access(identity, db)
    with studio_mgr.lock:
        if studio_mgr.status == "running" or (studio_mgr.worker_thread and studio_mgr.worker_thread.is_alive()):
            raise HTTPException(status_code=400, detail="上一任务仍在运行中，请先点击停止")

    idea = payload.idea.strip()
    if not idea:
        raise HTTPException(status_code=400, detail="请输入故事点子或核心冲突梗概")

    _verify_and_deduct_quota(identity, db)
    sys_prompt = (payload.system_prompt or "").strip() or DEFAULT_SYSTEM_PROMPTS["idea"]

    th = threading.Thread(
        target=_run_idea_worker,
        args=(idea, sys_prompt, payload.model.strip(), payload.reasoning_effort, payload.preferred_key),
        daemon=True,
    )
    studio_mgr.worker_thread = th
    th.start()
    return {"status": "started"}


# ==================== Story Studio Web UI Renderer ====================
def render_story_studio_app(service: Service, identity: CurrentIdentity) -> str:
    """Render the responsive Story Studio Web UI for `/apps/story-studio`."""
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
      margin: 1.5rem auto 6rem;
      padding: 0 1.1rem;
    }}
    .studio-config-bar {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 14px;
      padding: 1rem 1.2rem;
      margin-bottom: 1rem;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
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
      overflow-x: auto;
      padding-bottom: 2px;
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
      white-space: nowrap;
      transition: all 0.15s ease;
    }}
    .studio-tab.active {{
      background: rgba(56, 189, 248, 0.15);
      color: var(--accent);
      border-color: rgba(56, 189, 248, 0.4);
    }}
    .studio-panel {{
      display: none;
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 14px;
      padding: 1.25rem;
      margin-bottom: 1rem;
    }}
    .studio-panel.active {{
      display: block;
    }}
    .field-label {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--text-muted);
      margin: 0.75rem 0 0.4rem;
    }}
    .field-label:first-child {{
      margin-top: 0;
    }}
    .studio-textarea, .studio-input {{
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
    .studio-textarea:focus, .studio-input:focus {{
      border-color: var(--accent);
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
      margin-bottom: 0.45rem;
      font-size: 0.82rem;
      font-weight: 600;
      color: #38bdf8;
    }}
    .run-btn {{
      width: 100%;
      background: linear-gradient(135deg, #0ea5e9, #2563eb);
      color: #fff;
      border: none;
      padding: 0.9rem;
      border-radius: 11px;
      font-size: 0.96rem;
      font-weight: 700;
      margin-top: 1rem;
      cursor: pointer;
      transition: all 0.15s ease;
    }}
    .run-btn:disabled {{
      opacity: 0.45;
      cursor: not-allowed;
    }}
    .monitor-card {{
      display: none;
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 14px;
      padding: 1.25rem;
      margin-top: 1rem;
    }}
    .monitor-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.75rem;
      padding-bottom: 0.85rem;
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
    #stream-content {{
      font-size: 0.96rem;
      line-height: 1.85;
      color: #e2e8f0;
      white-space: pre-wrap;
      word-break: break-word;
      min-height: 140px;
    }}
    .floating-bar {{
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      background: rgba(15, 23, 42, 0.95);
      backdrop-filter: blur(14px);
      border-top: 1px solid var(--border-subtle);
      padding: 0.75rem 1.25rem;
      display: none;
      align-items: center;
      justify-content: space-between;
      z-index: 120;
    }}
    .history-bar {{
      margin-top: 1.5rem;
      background: rgba(15, 23, 42, 0.5);
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
      padding: 0.9rem 1.1rem;
    }}
    .history-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.45rem;
      margin-top: 0.55rem;
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
        <label for="model-select">Gemini 模型 (支持自定义输入)</label>
        <input list="model-options" id="model-select" value="gemini-3.5-flash-lite" />
        <datalist id="model-options">
          <option value="gemini-3.5-flash-lite">Gemini 3.5 Flash Lite</option>
          <option value="gemini-3.1-flash-lite">Gemini 3.1 Flash Lite</option>
        </datalist>
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
        <label for="key-select">API Key 调度 (keys/*.key)</label>
        <select id="key-select">
          <option value="auto" selected>🔄 自动轮询与故障切换</option>
        </select>
      </div>

      <div class="key-badge-bar">
        <span id="keys-status-text">正在检测 keys/ 目录...</span>
        <span>默认开启 <code>BLOCK_NONE</code> 与 <code>High Reasoning</code></span>
      </div>
    </div>

    <!-- Mode Tabs -->
    <div class="studio-tabs">
      <button class="studio-tab active" data-mode="rewrite" onclick="switchMode('rewrite', this)">
        1. 错乱重写扩写
      </button>
      <button class="studio-tab" data-mode="continue" onclick="switchMode('continue', this)">
        2. 剧情承接续写
      </button>
      <button class="studio-tab" data-mode="idea" onclick="switchMode('idea', this)">
        3. 灵感起草全篇
      </button>
    </div>

    <!-- Auto-Loaded & Editable System Prompt Box -->
    <div class="sys-prompt-box">
      <div class="sys-prompt-header">
        <span id="sys-prompt-label">当前模式 System Prompt（自动加载，可直接修改）</span>
        <button type="button" class="btn-action" onclick="resetCurrentSystemPrompt()">恢复默认准则</button>
      </div>
      <textarea id="system-prompt-input" class="studio-textarea" rows="4"></textarea>
    </div>

    <!-- Mode 1: Rewrite -->
    <div id="panel-rewrite" class="studio-panel active">
      <div class="field-label">
        <span>待重写的原始粗稿（自动执行：阶段1提取角色与动作骨架 → 阶段2逐幕扩写）</span>
      </div>
      <textarea
        id="rewrite-text"
        class="studio-textarea"
        rows="7"
        placeholder="在此粘贴语序混乱或简略的原始粗稿..."
      ></textarea>
      <button class="run-btn" onclick="startRewrite()">开始分幕解构 & 流式扩写</button>
    </div>

    <!-- Mode 2: Continue -->
    <div id="panel-continue" class="studio-panel">
      <div class="field-label">
        <span>已有前文内容（长文自动提炼全局前情概括 + 截取尾部 2000 字即时接续）</span>
      </div>
      <textarea
        id="continue-context"
        class="studio-textarea"
        rows="7"
        placeholder="在此粘贴前文或上一章内容..."
      ></textarea>
      <div class="field-label">
        <span>下一幕剧情走向 / 核心冲突提示（留空则顺应前文张力自主推演）</span>
      </div>
      <input
        type="text"
        id="continue-direction"
        class="studio-input"
        placeholder="例：两人爆发正面冲突，器物失控..."
      />
      <button class="run-btn" onclick="startContinue()">提炼前情 & 流式续写</button>
    </div>

    <!-- Mode 3: Idea -->
    <div id="panel-idea" class="studio-panel">
      <div class="field-label">
        <span>故事点子、人设或核心冲突梗概（阶段1规划 3~5 幕大纲 → 阶段2逐幕写透）</span>
      </div>
      <textarea
        id="idea-text"
        class="studio-textarea"
        rows="6"
        placeholder="例：深夜书房内，主控方审视承制方的违规记录，展开心理与肢体博弈..."
      ></textarea>
      <button class="run-btn" onclick="startIdea()">推演分幕大纲 & 全篇创作</button>
    </div>

    <!-- Live Streaming Monitor -->
    <div id="monitor-card" class="monitor-card">
      <div class="monitor-header">
        <div class="status-badge-row">
          <div class="pulse-dot" id="pulse-dot"></div>
          <span id="status-title">系统待命</span>
        </div>
        <button class="btn-danger-sm" id="stop-btn" onclick="stopTask()" disabled>⏹ 立即停止</button>
      </div>
      <div id="stream-content"></div>
    </div>

    <!-- Saved Outputs History -->
    <div class="history-bar">
      <div style="font-size:0.8rem;font-weight:600;color:var(--text-muted);">
        最近生成存档 (自动保存于 data/studio_outputs/)
      </div>
      <div class="history-list" id="history-list">
        <span style="font-size:0.78rem;color:var(--text-muted);">暂无历史记录</span>
      </div>
    </div>
  </div>

  <!-- Bottom Floating Bar -->
  <div class="floating-bar" id="floating-bar">
    <div style="font-size:0.84rem;color:var(--text-muted);">
      已生成 <strong style="color:var(--accent);" id="char-count">0</strong> 字
    </div>
    <button class="btn btn-accent" id="copy-btn" onclick="copyFullStory()">一键复制全文</button>
  </div>

  <div class="toast hidden" id="toast"></div>

  <script>
    let currentMode = "rewrite";
    let defaultPrompts = {{
      rewrite: "",
      continue: "",
      idea: "",
    }};
    let customPrompts = {{}};
    let fullText = "";
    let autoScroll = true;

    function showToast(msg) {{
      const t = document.getElementById("toast");
      t.textContent = msg;
      t.classList.remove("hidden");
      clearTimeout(window.__stToast);
      window.__stToast = setTimeout(() => t.classList.add("hidden"), 2500);
    }}

    window.addEventListener("scroll", () => {{
      const scrollBottom = document.documentElement.scrollHeight - window.innerHeight - window.scrollY;
      autoScroll = scrollBottom < 120;
    }}, {{ passive: true }});

    // Save edits in system prompt box per mode
    document.getElementById("system-prompt-input").addEventListener("input", (e) => {{
      customPrompts[currentMode] = e.target.value;
    }});

    function switchMode(mode, btn) {{
      // Save current textarea value before switching
      customPrompts[currentMode] = document.getElementById("system-prompt-input").value;
      currentMode = mode;

      document.querySelectorAll(".studio-panel").forEach((p) => p.classList.remove("active"));
      document.querySelectorAll(".studio-tab").forEach((b) => b.classList.remove("active"));
      document.getElementById(`panel-${{mode}}`).classList.add("active");
      btn.classList.add("active");

      const promptInput = document.getElementById("system-prompt-input");
      promptInput.value = customPrompts[mode] !== undefined ? customPrompts[mode] : (defaultPrompts[mode] || "");
    }}

    function resetCurrentSystemPrompt() {{
      delete customPrompts[currentMode];
      document.getElementById("system-prompt-input").value = defaultPrompts[currentMode] || "";
      showToast("已恢复当前模式的默认 System Prompt");
    }}

    async function loadStudioMeta() {{
      try {{
        const res = await fetch("/api/studio/meta");
        const data = await res.json();
        if (data.default_prompts) {{
          defaultPrompts = data.default_prompts;
          const promptInput = document.getElementById("system-prompt-input");
          if (!promptInput.value) {{
            promptInput.value = defaultPrompts[currentMode] || "";
          }}
        }}

        const keySelect = document.getElementById("key-select");
        const statusEl = document.getElementById("keys-status-text");
        if (Array.isArray(data.keys) && data.keys.length > 0) {{
          statusEl.innerHTML = `🔑 已加载 <strong>${{data.keys.length}}</strong> 个密钥: ` +
            data.keys.map((k) => `<code>${{k.name}}</code> (${{k.masked}})`).join(" · ");
          keySelect.innerHTML = `<option value="auto">🔄 自动轮询与故障切换 (${{data.keys.length}} Keys)</option>` +
            data.keys.map((k) => `<option value="${{k.name}}">${{k.name}} (${{k.masked}})</option>`).join("");
        }} else {{
          statusEl.innerHTML = `<span style="color:#fb7185;">⚠️ 未检测到有效密钥，请在项目 keys/ 目录下填入 Gemini1.key / gemini2.key</span>`;
        }}

        const histEl = document.getElementById("history-list");
        if (Array.isArray(data.outputs) && data.outputs.length > 0) {{
          histEl.innerHTML = data.outputs
            .map((o) => `<button class="btn-action" onclick="loadSavedOutput('${{o.name}}')">📄 ${{o.name}}</button>`)
            .join("");
        }}
      }} catch (e) {{
        console.error(e);
      }}
    }}

    async function loadSavedOutput(filename) {{
      try {{
        const res = await fetch(`/api/studio/outputs/${{encodeURIComponent(filename)}}`);
        const data = await res.json();
        document.getElementById("monitor-card").style.display = "block";
        document.getElementById("floating-bar").style.display = "flex";
        fullText = data.content || "";
        document.getElementById("stream-content").textContent = fullText;
        document.getElementById("char-count").textContent = fullText.length;
        document.getElementById("status-title").textContent = `📄 历史存档: ${{data.name}}`;
      }} catch (e) {{
        showToast("加载存档失败");
      }}
    }}

    function setRunningUI(isRunning) {{
      document.querySelectorAll(".run-btn").forEach((b) => (b.disabled = isRunning));
      document.getElementById("stop-btn").disabled = !isRunning;
      const dot = document.getElementById("pulse-dot");
      if (isRunning) {{
        dot.classList.add("live");
      }} else {{
        dot.classList.remove("live");
      }}
    }}

    function initSSE() {{
      const evtSource = new EventSource("/api/studio/events");
      evtSource.onmessage = (e) => {{
        try {{
          const ev = JSON.parse(e.data);
          const monitor = document.getElementById("monitor-card");
          const contentBox = document.getElementById("stream-content");
          const titleBox = document.getElementById("status-title");
          const floatBar = document.getElementById("floating-bar");
          const counter = document.getElementById("char-count");

          if (ev.type === "init") {{
            titleBox.textContent = ev.status_msg;
            if (ev.content || ev.status === "running") {{
              monitor.style.display = "block";
              floatBar.style.display = "flex";
              fullText = ev.content || "";
              contentBox.textContent = fullText;
              counter.textContent = fullText.length;
            }}
            setRunningUI(ev.status === "running");
          }} else if (ev.type === "status") {{
            titleBox.textContent = ev.msg;
          }} else if (ev.type === "token") {{
            fullText += ev.content;
            contentBox.textContent = fullText;
            counter.textContent = fullText.length;
            if (autoScroll) {{
              window.scrollTo(0, document.documentElement.scrollHeight);
            }}
          }} else if (ev.type === "stopped" || ev.type === "done") {{
            setRunningUI(false);
            loadStudioMeta();
          }}
        }} catch (err) {{}}
      }};
    }}

    async function sendStart(endpoint, payload) {{
      payload.system_prompt = document.getElementById("system-prompt-input").value.trim();
      payload.model = document.getElementById("model-select").value.trim() || "gemini-3.5-flash-lite";
      payload.reasoning_effort = document.getElementById("reasoning-select").value;
      payload.preferred_key = document.getElementById("key-select").value;

      document.getElementById("monitor-card").style.display = "block";
      document.getElementById("floating-bar").style.display = "flex";
      document.getElementById("stream-content").textContent = "";
      fullText = "";
      autoScroll = true;
      document.getElementById("char-count").textContent = "0";
      setRunningUI(true);

      try {{
        const res = await fetch(endpoint, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload),
        }});
        const data = await res.json();
        if (!res.ok) {{
          showToast(data.detail || data.error || "启动失败");
          document.getElementById("status-title").textContent = data.detail || "启动失败";
          setRunningUI(false);
        }}
      }} catch (e) {{
        showToast(e.message);
        setRunningUI(false);
      }}
    }}

    function startRewrite() {{
      sendStart("/api/studio/start_rewrite", {{
        text: document.getElementById("rewrite-text").value,
      }});
    }}

    function startContinue() {{
      sendStart("/api/studio/start_continue", {{
        context: document.getElementById("continue-context").value,
        direction: document.getElementById("continue-direction").value,
      }});
    }}

    function startIdea() {{
      sendStart("/api/studio/start_idea", {{
        idea: document.getElementById("idea-text").value,
      }});
    }}

    async function stopTask() {{
      const btn = document.getElementById("stop-btn");
      btn.disabled = true;
      await fetch("/api/studio/stop", {{ method: "POST" }});
      setRunningUI(false);
    }}

    function copyFullStory() {{
      const textToCopy = fullText || document.getElementById("stream-content").textContent;
      if (!textToCopy) return;
      navigator.clipboard.writeText(textToCopy).then(() => {{
        showToast("全文已复制到剪贴板 ✓");
      }});
    }}

    loadStudioMeta();
    initSSE();
  </script>
</body>
</html>"""
