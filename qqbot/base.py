"""基础层：日志、事件解析、HTTP 小工具。

上层（api / net / handler）都从这里拿基础能力；依赖只有 config。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .config import *  # noqa: F401,F403


# --------------------------------------------------------------------------
# 日志
# --------------------------------------------------------------------------


def log(message: str) -> None:
    line = time.strftime("[%H:%M:%S] ") + message
    print(line, flush=True)
    if not LOG_FILE:
        return
    try:
        path = Path(LOG_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def ensure_dirs() -> None:
    """建好 config/ 和 data/，顺便早暴露权限问题。"""
    for directory in (CONFIG_DIR, DATA_DIR):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            log(f"[数据] 建目录 {directory} 失败：{error}")


# --------------------------------------------------------------------------
# 电源：阻止系统睡眠（只在 Windows 有效）
# --------------------------------------------------------------------------

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def keep_awake(enable: bool = True) -> bool:
    """阻止 Windows 进入睡眠，显示器仍然可以关。返回是否成功下发。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        flags = (_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED) if enable else _ES_CONTINUOUS
        return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))
    except Exception as error:  # noqa: BLE001 - 电源策略失败不该影响机器人
        log(f"[电源] 设置失败：{error!r}")
        return False


# --------------------------------------------------------------------------
# 事件
# --------------------------------------------------------------------------


@dataclass
class Incoming:
    group_openid: str
    user_openid: str = ""
    username: str = ""
    content: str = ""
    msg_id: str = ""
    is_bot: bool = False
    event_type: str = ""
    mentioned: bool = False
    mention_ids: list[str] = field(default_factory=list)
    # 来自按钮点击（INTERACTION_CREATE）时，这里是互动事件 id。
    # 回复要用它当 event_id，不能当 msg_id 用。
    event_id: str = ""


# 按钮点击的回复锚点：把互动事件 id 包成 ``event:<id>`` 塞进 msg_id。
# 这样 handler 里所有 ``sender.xxx(..., event.msg_id)`` 都不用改，发送层认前缀。
EVENT_TOKEN_PREFIX = "event:"

# INTERACTION_CREATE 的 type=11：消息里的按钮被点击。
INTERACTION_TYPE_BUTTON = 11


def event_reply_token(interaction_id: str) -> str:
    return f"{EVENT_TOKEN_PREFIX}{interaction_id}" if interaction_id else ""


def split_reply_token(token: str) -> tuple[str, str]:
    """回复锚点 → ``("event"|"msg", id)``。"""
    token = token or ""
    if token.startswith(EVENT_TOKEN_PREFIX):
        return "event", token[len(EVENT_TOKEN_PREFIX):]
    return "msg", token


# 官方消息正文里的 @ 标记 / 表情标签，命令匹配前都要清掉。
_MARKUP_RE = re.compile(r"<qqbot-at-user[^>]*?/?>|<@!?[^>]+>")
_MENTION_MARKUP_RE = re.compile(r"<@!?[^>]+>|<qqbot-at-user")
_MENTION_ID_RE = re.compile(r"<@!?([^>\s]+)>|<qqbot-at-user[^>]*?id=\"([^\"]+)\"")
_TAG_RE = re.compile(r"<faceType=[^>]*>|<emoji[^>]*>|</?em[^>]*>", re.IGNORECASE)
# @ 标记被剥掉后正文开头常残留一个 @，会害得精确匹配的命令对不上。
_MENTION_PREFIX_RE = re.compile(r"^(?:[@＠]\s*)+")


def normalize_content(text: str) -> str:
    cleaned = _MARKUP_RE.sub("", text or "")
    cleaned = _TAG_RE.sub("", cleaned)
    cleaned = _MENTION_PREFIX_RE.sub("", cleaned)
    return cleaned.strip()


def mention_ids_in(raw: str) -> list[str]:
    """从正文里取出所有被 @ 的 ID。"""
    ids: list[str] = []
    for match in _MENTION_ID_RE.finditer(raw or ""):
        value = (match.group(1) or match.group(2) or "").strip().lstrip("@!").strip()
        if value and value not in ids:
            ids.append(value)
    return ids


def parse_group_event(event_type: str, d: dict) -> Incoming:
    author = d.get("author") or {}
    raw_content = str(d.get("content") or "")
    return Incoming(
        group_openid=str(d.get("group_openid") or ""),
        user_openid=str(author.get("member_openid") or author.get("id") or ""),
        username=str(author.get("username") or ""),
        content=normalize_content(raw_content),
        msg_id=str(d.get("id") or ""),
        is_bot=bool(author.get("bot")),
        event_type=event_type,
        mentioned=bool(_MENTION_MARKUP_RE.search(raw_content)),
        mention_ids=mention_ids_in(raw_content),
    )


def parse_interaction_event(d: dict) -> "Incoming | None":
    """把 INTERACTION_CREATE（按钮点击）转成 Incoming，走和打字一样的命令路。

    按钮的 ``action.data`` 写的就是**和文本命令一模一样**的字符串
    （点「简单模式」等于发「弗一把 简单模式」），所以业务层只有一套逻辑。
    """
    try:
        if int(d.get("type") or 0) != INTERACTION_TYPE_BUTTON:
            return None
    except (TypeError, ValueError):
        return None
    resolved = (d.get("data") or {}).get("resolved") or {}
    command = str(resolved.get("button_data") or "").strip()
    if not command:
        return None
    interaction_id = str(d.get("id") or "")
    return Incoming(
        group_openid=str(d.get("group_openid") or ""),
        user_openid=str(d.get("group_member_openid") or d.get("user_openid") or ""),
        content=normalize_content(command),
        msg_id=event_reply_token(interaction_id),
        event_id=interaction_id,
        event_type="INTERACTION_CREATE",
        mentioned=False,
    )


# --------------------------------------------------------------------------
# HTTP（标准库，跑在线程里避免阻塞事件循环）
# --------------------------------------------------------------------------


def http_json(method: str, url: str, payload: dict | None = None,
              headers: dict[str, str] | None = None, timeout: float = 30) -> dict:
    body = None
    request_headers = {"User-Agent": "fuyiba-bot/1.0"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw.strip() else {}
        except ValueError:
            data = {"raw": raw}
        if not isinstance(data, dict):
            data = {"raw": data}
        data.setdefault("_http_status", error.code)
        return data


async def http_json_async(method: str, url: str, payload: dict | None = None,
                          headers: dict[str, str] | None = None,
                          timeout: float = 30) -> dict:
    return await asyncio.to_thread(http_json, method, url, payload, headers, timeout)


# --------------------------------------------------------------------------
# 文本
# --------------------------------------------------------------------------


def split_text(text: str, limit: int = REPLY_CHUNK_CHARS) -> list[str]:
    """按段落把长回复切成分条，尽量不切断句子。"""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n"):
        candidate = f"{current}\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > limit:
            cut = paragraph.rfind("。", 0, limit)
            cut = cut + 1 if cut > limit // 2 else limit
            chunks.append(paragraph[:cut])
            paragraph = paragraph[cut:]
        current = paragraph
    if current:
        chunks.append(current)
    return [chunk.strip() for chunk in chunks if chunk.strip()]
