"""群消息业务处理：只做一件事 —— 弗一把。

路由很薄：所有命令和猜词都交给 ``mc_guess.MCGuess``，这里只负责
记名字、发面板（按钮）、以及冷场提醒的后台任务。
没有 AI、没有规则表、没有复读：不命中就完全不说话。
"""
from __future__ import annotations

import asyncio

from .base import Incoming, log, normalize_content
from .mc_guess import NUDGE_CHECK_INTERVAL, MCGuess
from .panel import build_rows
from .roster import Roster

HELP_WORDS = {"帮助", "弗一把帮助", "弗一把 帮助", "指令", "命令", "菜单", "玩法"}

HELP_TEXT = (
    "🎮 弗一把 · Minecraft 物品 & 生物\n"
    "发「弗一把」→ 弹面板，选简单 / 困难开局\n"
    "猜的时候直接发物品名，或者「猜 钻石剑」\n"
    "「弗一把 状态」看进度 ·「弗一把 榜单」看本群榜 ·「弗一把 结束」放弃\n"
    "20 轮全群共享；每猜一次给六维反馈：🟩 完全对上 · 🟨 沾边 · ⬜ 不对 · ⬆️⬇️ 更新/更旧"
)


class Handler:
    def __init__(self, sender, data_dir) -> None:
        self.sender = sender
        self.roster = Roster(data_dir)
        # 机器人自己的名字 / ID：启动后从 /users/@me 取，用来剥正文开头的「名字 + 空格」。
        self.bot_names: set[str] = set()
        self.bot_ids: set[str] = set()
        # 对局只在内存里；榜单落盘 data/mc_guess_rank.json。
        self.mc_guess = MCGuess(None, data_dir)
        # 冷场催更的后台任务：第一次有人开局才起。
        self._mc_ticker: asyncio.Task | None = None

    # ---- 入口 ----

    async def handle(self, event: Incoming) -> bool:
        """返回 True 表示这条消息归我处理。"""
        if event.is_bot or not event.group_openid:
            return False
        group, user = event.group_openid, event.user_openid
        # 按钮点击事件里没有昵称，所以每条消息都顺手记一下（猜中要写榜单）。
        self.roster.remember(group, user, event.username)

        command = (event.content or "").strip()
        candidates = [command]
        variant = self._strip_leading_name(command) if command else None
        if variant and variant != command:
            candidates.append(variant)

        for candidate in candidates:
            if candidate in HELP_WORDS:
                await self.sender.text(group, HELP_TEXT, event.msg_id)
                return True
            result = self.mc_guess.handle(candidate, group, user, self._owner(event))
            if not result:
                continue
            self._ensure_mc_ticker()
            # 面板和纯文字都走这条：按钮只签给发命令的人，谁唤出谁点。
            await self._deliver_panel(result, event, "弗一把")
            return True

        # 只 @ 不说话（或者点了个没配 data 的按钮）：给一句用法，别装死。
        if event.mentioned and self._mentions_me(event) and not command:
            await self.sender.text(group, HELP_TEXT, event.msg_id)
            return True
        return False

    # ---- 发送 ----

    async def _deliver_panel(self, result: dict, event: Incoming,
                             tag: str = "面板") -> None:
        """发面板（带按钮）或一句纯文字；按钮发不出去就退回文字版。"""
        group = event.group_openid
        panel = result.get("panel")
        if not panel:
            reply = str(result.get("reply") or "")
            if reply:
                await self.sender.text(group, reply, event.msg_id)
            return
        allowed = [event.user_openid] if event.user_openid else []
        try:
            await self.sender.panel(
                group, panel["text"],
                build_rows(panel["rows"], highlight=True, user_ids=allowed),
                event.msg_id,
            )
        except Exception as error:  # noqa: BLE001 - 按钮是附加能力，不能挡住流程
            log(f"[{tag}] 按钮面板发送失败，退回文字：{error!r}")
            await self.sender.text(
                group,
                panel["text"]
                + "\n\n（按钮发不出去，只能先把面板当文字看；"
                "发「弗一把 简单模式」/「弗一把 困难模式」也能开局。）",
                event.msg_id,
            )

    # ---- 冷场提醒 ----

    def _ensure_mc_ticker(self) -> None:
        task = self._mc_ticker
        if task is not None and not task.done():
            return
        try:
            self._mc_ticker = asyncio.create_task(self._mc_tick())
        except RuntimeError:      # 没有事件循环（纯同步调用）就当没有提醒
            self._mc_ticker = None

    async def _mc_tick(self) -> None:
        """每 20 秒看一眼有没有冷场的局，有就催一句（不占轮数、不改局内状态）。"""
        while True:
            await asyncio.sleep(NUDGE_CHECK_INTERVAL)
            for group in self.mc_guess.groups():
                line = self.mc_guess.nudge(group)
                if not line:
                    continue
                try:
                    await self.sender.text(group, line)
                except Exception as error:  # noqa: BLE001 - 催更失败不影响对局
                    log(f"[弗一把] 冷场提醒发送失败：{error!r}")

    # ---- 小工具 ----

    def _owner(self, event: Incoming) -> str:
        """猜的人叫什么：优先消息里的昵称，按钮事件只能拿 openid 反查名册。"""
        return (
            event.username
            or self.roster.name_of(event.group_openid, event.user_openid)
            or "群友"
        ).strip()

    def _strip_leading_name(self, command: str) -> str | None:
        """把正文开头的「@名字 / 机器人名字 + 空格」去掉，返回剩下的命令。"""
        head, separator, rest = command.partition(" ")
        if not separator or not rest.strip():
            return None
        bare = head.lstrip("@＠")
        if head.startswith(("@", "＠")) or bare in self.bot_names:
            return normalize_content(rest)
        return None

    def _mentions_me(self, event: Incoming) -> bool:
        """这条消息是不是在 @ 机器人本人（而不是 @ 别人）。"""
        if not event.mention_ids:
            return event.mentioned
        if not self.bot_ids:
            return event.mentioned
        mine = {value.casefold() for value in self.bot_ids}
        return any(value.casefold() in mine for value in event.mention_ids)
