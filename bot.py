#!/usr/bin/env python3
"""弗一把 · 单功能 QQ 官方机器人入口。

整个项目只做一件事：群里的「弗一把」（Minecraft 物品 & 生物猜猜猜）。

零第三方依赖：HTTP 用 urllib，WebSocket 自己实现，不用 httpx / websockets / NoneBot。

用法：
    python bot.py --selftest     # 不联网，跑一遍本地自检
    python bot.py --check        # 验 AppID/AppSecret，取 token + 网关地址
    python bot.py                # 正式连网关（双击 start.bat 也行）

凭据（二选一）：
    config/appid.txt + config/secret.txt（各一行，最省事）
    或环境变量 QQ_BOT_APPID / QQ_BOT_SECRET

目录：
    config/   凭据、题库（mc_guess_easy.json / mc_guess_hard.json）
    data/     运行时数据（榜单 mc_guess_rank.json、群成员名册 members.json）
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from qqbot.api import GroupSender, QQBotAPI
from qqbot.base import KEEP_AWAKE, ensure_dirs, keep_awake, log
from qqbot.config import CONFIG_DIR, DATA_DIR
from qqbot.handler import Handler
from qqbot.mc_guess import MODE_BANKS
from qqbot.net import Gateway


def read_credential(filename: str, env_name: str) -> str:
    """凭据：config/ 优先，其次 data/（旧布局），最后环境变量。"""
    for base in (CONFIG_DIR, DATA_DIR):
        path = base / filename
        if path.is_file():
            value = path.read_text(encoding="utf-8-sig").strip()
            if value:
                return value
    return os.getenv(env_name, "").strip()


def mask(value: str) -> str:
    if len(value) <= 6:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


async def check_credentials(appid: str, secret: str) -> int:
    api = QQBotAPI(appid, secret)
    try:
        token = await api.token()
        url = await api.gateway()
    except Exception as error:  # noqa: BLE001 - 排查用，直接打印原因
        log(f"[检查] 失败：{error!r}")
        return 1
    log(f"[检查] AppID {mask(appid)} 鉴权成功，token {mask(token)}")
    log(f"[检查] 网关地址：{url}")
    return 0


async def main_async(args: argparse.Namespace) -> int:
    if args.selftest:
        from qqbot.selftest import selftest

        return await selftest()

    ensure_dirs()

    appid = read_credential("appid.txt", "QQ_BOT_APPID")
    secret = read_credential("secret.txt", "QQ_BOT_SECRET")
    if not appid or not secret:
        # 新克隆下来的仓库里这两个文件不存在（被 .gitignore 挡住），先建出空文件，
        # 省得还得自己右键新建 —— 打开填一行就能跑。
        for name in ("appid.txt", "secret.txt"):
            try:
                (CONFIG_DIR / name).touch(exist_ok=True)
            except OSError:
                pass
        log("缺少凭据。把机器人的 AppID 写进 config/appid.txt、"
            "AppSecret 写进 config/secret.txt（各一行，不要引号、不要空格），"
            "或者设环境变量 QQ_BOT_APPID / QQ_BOT_SECRET。")
        log(f"要填的文件：{CONFIG_DIR / 'appid.txt'} 和 {CONFIG_DIR / 'secret.txt'}")
        return 2

    if args.check:
        return await check_credentials(appid, secret)

    api = QQBotAPI(appid, secret)
    sender = GroupSender(api)
    handler = Handler(sender, DATA_DIR)

    log(f"[题库] 简单 {len(MODE_BANKS['简单']['items'])} 条 / "
        f"困难 {len(MODE_BANKS['困难']['items'])} 条（困难 = 简单 + 1.20.2 之后的新内容）")
    log(f"启动：AppID {mask(appid)}，数据目录 {DATA_DIR}")

    try:
        profile = await api.me()
        username = str(profile.get("username") or "").strip()
        if username:
            handler.bot_names.add(username)
            log(f"[资料] 机器人名字：{username}")
        for field_name in ("id", "union_openid"):
            value = str(profile.get(field_name) or "").strip()
            if value:
                handler.bot_ids.add(value)
        if handler.bot_ids:
            log(f"[资料] 机器人 ID：{sorted(handler.bot_ids)}")
        else:
            log("[资料] 警告：没取到机器人 ID，@ 判定会退化成「有 @ 就算叫我」")
    except Exception as error:  # noqa: BLE001 - 拿不到名字不影响主流程
        log(f"[资料] 取机器人名字失败：{error!r}")

    if keep_awake(KEEP_AWAKE):
        log("[电源] 已请求阻止系统睡眠（显示器仍可关闭；要关掉设 FUYIBA_KEEP_AWAKE=0）")
    elif KEEP_AWAKE and sys.platform != "win32":
        log("[电源] 非 Windows，跳过防休眠")

    gateway = Gateway(api, handler)
    try:
        await gateway.run()
    except KeyboardInterrupt:
        log("已停止")
    finally:
        keep_awake(False)
        handler.roster.flush(force=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="弗一把 QQ 官方机器人")
    parser.add_argument("--selftest", action="store_true", help="本地自检，不联网")
    parser.add_argument("--check", action="store_true", help="只验证凭据与网关")
    args = parser.parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
