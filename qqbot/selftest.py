"""离线自检：不联网、不需要凭据，假装群里发几条消息把整条链路走一遍。

    python bot.py --selftest

覆盖：难度面板 → 开局 → 猜错（六维反馈）→ 重复猜 → 普通闲聊不抢 →
猜中（进榜）→ 榜单 → 状态 → 困难模式 + 「猜 X」前缀 → 认输 → 帮助。
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from .base import Incoming
from .handler import HELP_TEXT, Handler
from .mc_guess import MODE_BANKS, MODE_EASY, MODE_HARD


class FakeSender:
    """假发送器：把要发的东西记下来，自检里直接看。"""

    def __init__(self) -> None:
        self.items: list[dict] = []

    async def text(self, group: str, content: str, msg_id: str | None = None) -> None:
        self.items.append({"kind": "text", "content": content})

    async def panel(self, group: str, content: str, rows: list[dict],
                    msg_id: str | None = None) -> None:
        self.items.append({"kind": "panel", "content": content, "rows": rows})

    def last(self) -> dict | None:
        return self.items[-1] if self.items else None


async def selftest() -> int:
    failures = 0

    def expect(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(("  ✅ " if ok else "  ❌ ") + label + ("" if ok else f"　→ {detail}"))
        if not ok:
            failures += 1

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        sender = FakeSender()
        handler = Handler(sender, data_dir)

        async def send(text: str, user: str = "U1", name: str = "阿曼",
                       msg_id: str = "M1") -> tuple[bool, dict | None]:
            sender.items.clear()
            event = Incoming(group_openid="G1", user_openid=user, username=name,
                             content=text, msg_id=msg_id)
            handled = await handler.handle(event)
            return handled, sender.last()

        print("== 弗一把 ==")

        handled, last = await send("弗一把")
        expect("发「弗一把」回一块面板", handled and last and last["kind"] == "panel",
               repr(last))
        buttons = (last or {}).get("rows", [{}])[0].get("buttons", [])
        expect("面板是两个难度按钮",
               [b["render_data"]["label"] for b in buttons] == ["简单模式", "困难模式"]
               and [b["action"]["data"] for b in buttons]
               == ["弗一把 简单模式", "弗一把 困难模式"],
               repr(buttons))

        # 点「简单模式」＝发同样一句话（按钮的 data 就是文本命令）
        handled, last = await send("弗一把 简单模式", msg_id="event:INT1")
        text = (last or {}).get("content", "")
        game = handler.mc_guess._games.get("G1")
        expect("点按钮能开局", handled and game is not None and game.mode == MODE_EASY,
               repr(last))
        expect("开局文案带模式名和轮数", "简单模式" in text and "20 轮" in text, text)
        target = game.target

        # 猜错：挑一个同题库里不是答案的物品
        wrong = next(item for item in MODE_BANKS[MODE_EASY]["items"]
                     if item.name != target.name)
        handled, last = await send(wrong.name, user="U2", name="小美")
        text = (last or {}).get("content", "")
        expect("猜错给一轮六维反馈",
               handled and "第 1/20 轮" in text and "名称" in text and "生成世界" in text,
               text)

        handled, last = await send(wrong.name, user="U2", name="小美")
        expect("同一件东西不重复烧轮数",
               "已经猜过" in (last or {}).get("content", ""), repr(last))

        handled, last = await send("今天天气不错", user="U2", name="小美")
        expect("普通闲聊不抢", handled is False and last is None, repr(last))

        handled, last = await send(target.name, user="U2", name="小美")
        text = (last or {}).get("content", "")
        expect("猜中答案", handled and "猜中啦" in text and target.name in text, text)
        expect("猜中的人记进榜单", "第 1 次猜中" in text, text)

        handled, last = await send("弗一把 榜单")
        text = (last or {}).get("content", "")
        expect("「弗一把 榜单」能看本群榜",
               "本群弗一把榜" in text and "小美" in text and "1 次" in text, text)

        handled, last = await send("弗一把 状态")
        expect("没开局时「状态」给提示",
               "没在玩" in (last or {}).get("content", ""), repr(last))

        # 困难模式 + 「猜 X」前缀
        handled, last = await send("弗一把 困难模式", user="U3", name="阿岚")
        game = handler.mc_guess._games.get("G1")
        expect("困难模式能开局", game is not None and game.mode == MODE_HARD, repr(last))
        target = game.target
        handled, last = await send(f"猜 {target.name}", user="U3", name="阿岚")
        expect("「猜 X」前缀也认",
               "猜中啦" in (last or {}).get("content", ""), repr(last))

        # 认输
        await send("弗一把 简单模式", user="U4", name="老王")
        handled, last = await send("弗一把 结束")
        text = (last or {}).get("content", "")
        expect("「弗一把 结束」公布答案",
               "答案是" in text and handler.mc_guess._games.get("G1") is None, text)

        handled, last = await send("帮助")
        expect("「帮助」给用法", (last or {}).get("content") == HELP_TEXT, repr(last))

        expect("榜单落盘 data/mc_guess_rank.json",
               (data_dir / "mc_guess_rank.json").is_file())

        # 收尾：别把后台催更任务留在事件循环里
        ticker = handler._mc_ticker
        if ticker is not None and not ticker.done():
            ticker.cancel()
            try:
                await ticker
            except asyncio.CancelledError:
                pass

    print()
    if failures:
        print(f"自检失败 {failures} 项")
        return 1
    print("自检全部通过")
    return 0
