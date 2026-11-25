"""QQ 开放平台 HTTP API 与被动回复发送器。不含业务逻辑。"""
from __future__ import annotations

import asyncio
import time

from .base import (
    API_BASE,
    GATEWAY_URL,
    MAX_PASSIVE_REPLIES,
    TOKEN_URL,
    http_json_async,
    log,
    split_reply_token,
    split_text,
)


class QQBotAPI:
    def __init__(self, appid: str, secret: str) -> None:
        self.appid = appid
        self.secret = secret
        self._token: str | None = None
        self._token_expire_at = 0.0
        self._token_lock = asyncio.Lock()

    async def token(self, force: bool = False) -> str:
        async with self._token_lock:
            if not force and self._token and time.time() < self._token_expire_at - 60:
                return self._token
            data = await http_json_async(
                "POST", TOKEN_URL,
                {"appId": self.appid, "clientSecret": self.secret},
            )
            token = data.get("access_token")
            if not token:
                raise RuntimeError(f"取 access_token 失败：{data}")
            expires_in = int(data.get("expires_in") or 7200)
            self._token = str(token)
            self._token_expire_at = time.time() + expires_in
            log(f"[鉴权] access_token 已刷新，{expires_in}s 后过期")
            return self._token

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"QQBot {await self.token()}"}

    async def gateway(self) -> str:
        data = await http_json_async("GET", GATEWAY_URL, headers=await self._headers())
        url = data.get("url")
        if not url:
            raise RuntimeError(f"取网关地址失败：{data}")
        return str(url)

    async def me(self) -> dict:
        """机器人自己的资料，用来拿 username / id 判断「是不是在 @ 我」。"""
        return await http_json_async("GET", f"{API_BASE}/users/@me",
                                     headers=await self._headers())

    @staticmethod
    def _attach_passive(payload: dict, msg_id: str | None = None,
                        msg_seq: int = 1, event_id: str = "") -> dict:
        """把「这条回给谁」塞进 payload。

        普通消息用 ``msg_id + msg_seq``（同一条最多 5 次）；按钮点击用
        ``event_id``，不吃主动消息的频控和每天 1000 条配额。
        ``event_id`` 要带事件类型前缀，裸 uuid 会被判 40034025。
        """
        if event_id:
            payload["event_id"] = (event_id if ":" in event_id
                                   else f"INTERACTION_CREATE:{event_id}")
        elif msg_id:
            payload["msg_id"] = msg_id
            payload["msg_seq"] = msg_seq
        return payload

    async def _post_group(self, group_openid: str, payload: dict,
                          kind: str = "消息") -> dict:
        """发群消息，顺带兜住 ``event_id`` 的两个坑。

        1. 必须带事件类型前缀；
        2. 平台登记有延迟（约 0.6~0.8 秒），收到就回会踩空 —— 撞上 40034025 就等着重试。
        """
        url = f"{API_BASE}/v2/groups/{group_openid}/messages"
        headers = await self._headers()
        event_id = str(payload.get("event_id") or "")
        data: dict = {}
        for attempt, delay in enumerate((0.0, 0.9, 1.4)):
            if delay:
                await asyncio.sleep(delay)
            current = dict(payload)
            if attempt == 2 and event_id:
                # 最后一试换个写法（万一平台哪天只认裸 id）
                current["event_id"] = (
                    event_id.split(":", 1)[1] if ":" in event_id
                    else f"INTERACTION_CREATE:{event_id}"
                )
            data = await http_json_async("POST", url, current, headers)
            if data.get("err_code") != 40034025 or not event_id:
                break
            log(f"[发送] event_id 还不认（第 {attempt + 1} 次），等平台登记后重试")
        if "id" not in data:
            raise RuntimeError(f"发{kind}失败：{data}")
        return data

    async def send_text(self, group_openid: str, content: str,
                        msg_id: str | None = None, msg_seq: int = 1,
                        event_id: str = "") -> dict:
        payload: dict = {"msg_type": 0, "content": content}
        self._attach_passive(payload, msg_id, msg_seq, event_id)
        return await self._post_group(group_openid, payload, "文本")

    async def send_markdown(self, group_openid: str, content: str,
                            msg_id: str | None = None, msg_seq: int = 1,
                            event_id: str = "") -> dict:
        payload: dict = {"msg_type": 2, "markdown": {"content": content}}
        self._attach_passive(payload, msg_id, msg_seq, event_id)
        return await self._post_group(group_openid, payload, "markdown")

    async def send_keyboard(self, group_openid: str, content: str, rows: list[dict],
                            msg_id: str | None = None, msg_seq: int = 1,
                            event_id: str = "") -> dict:
        """发「markdown + 底部按钮」。按钮只能挂在 markdown 上（msg_type=2）。"""
        payload: dict = {
            "msg_type": 2,
            "markdown": {"content": content},
            "keyboard": {"content": {"rows": rows}},
        }
        self._attach_passive(payload, msg_id, msg_seq, event_id)
        return await self._post_group(group_openid, payload, "按钮消息")

    async def interaction_ack(self, interaction_id: str, code: int = 0) -> dict:
        """回应按钮点击：官方要求 3 秒内回应，否则用户端一直转圈。"""
        if not interaction_id:
            return {}
        headers = await self._headers()
        for path in (
            f"{API_BASE}/interactions/{interaction_id}",
            f"{API_BASE}/v2/interactions/{interaction_id}",
        ):
            data = await http_json_async("PUT", path, {"code": int(code)},
                                         headers, timeout=8)
            if data.get("_http_status") == 404:
                continue
            if data.get("_http_status"):
                log(f"[按钮] 回应互动 {interaction_id[:8]}… 失败：{data}")
            return data
        log(f"[按钮] 回应互动的接口都不存在（{interaction_id[:8]}…）")
        return {"_http_status": 404}


class GroupSender:
    """把「发一条」包装成被动回复：自动递增 msg_seq，超过 5 次退回主动消息。"""

    def __init__(self, api: QQBotAPI) -> None:
        self.api = api
        self._seq: dict[tuple[str, str], int] = {}

    def _target(self, group: str, msg_id: str | None) -> tuple[str | None, int, str]:
        """算出这条回复的被动锚点 → ``(msg_id, msg_seq, event_id)``。"""
        if not msg_id:
            return None, 1, ""
        kind, target = split_reply_token(msg_id)
        key = (group, msg_id)
        count = self._seq.get(key, 0) + 1
        self._seq[key] = count
        if count > MAX_PASSIVE_REPLIES:
            log(f"[发送] {msg_id[:12]}… 已回满 {MAX_PASSIVE_REPLIES} 条，改发主动消息")
            return None, 1, ""
        if kind == "event":
            return None, 1, target
        return target or None, count, ""

    async def text(self, group: str, content: str, msg_id: str | None = None) -> None:
        reply_to, seq, event_id = self._target(group, msg_id)
        await self.api.send_text(group, content, reply_to, seq, event_id=event_id)
        log(f"[发送] 文本（{len(content)} 字）：{content[:40]!r}")

    async def markdown(self, group: str, content: str,
                       msg_id: str | None = None) -> None:
        reply_to, seq, event_id = self._target(group, msg_id)
        await self.api.send_markdown(group, content, reply_to, seq, event_id=event_id)
        log(f"[发送] markdown（{len(content)} 字）：{content[:40]!r}")

    async def panel(self, group: str, content: str, rows: list[dict],
                    msg_id: str | None = None) -> None:
        """发一条带按钮的 markdown 面板。行/列超限会被平台拒（40034029）。"""
        reply_to, seq, event_id = self._target(group, msg_id)
        await self.api.send_keyboard(group, content, rows, reply_to, seq,
                                     event_id=event_id)
        log(f"[发送] 按钮面板（{len(rows)} 行）：{content[:30]!r}")

    async def text_long(self, group: str, content: str,
                        msg_id: str | None = None) -> None:
        """长回复按段切成几条发：官方文本有长度上限，一条塞不下会被拒。"""
        chunks = split_text(content)
        if len(chunks) > 1:
            log(f"[发送] 回复 {len(content)} 字，切成 {len(chunks)} 条")
        for chunk in chunks:
            await self.text(group, chunk, msg_id)
