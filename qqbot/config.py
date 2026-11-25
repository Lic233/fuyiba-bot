"""配置：目录与平台常量。

只放常量和环境变量读取，不放逻辑。环境变量在 import 时读一次，改完要重启。

凭据二选一：
    config/appid.txt + config/secret.txt（各一行，最常见的用法）
    或环境变量 QQ_BOT_APPID / QQ_BOT_SECRET
"""
from __future__ import annotations

import os
from pathlib import Path

# 项目根目录（qqbot/ 的上一级）—— config/、data/ 都在这里。
ROOT_DIR = Path(__file__).resolve().parent.parent

# 静态配置与凭据（几乎不改）
CONFIG_DIR = Path(
    os.getenv("FUYIBA_CONFIG_DIR", "").strip() or ROOT_DIR / "config"
)
# 运行时数据（榜单、成员名册），自动创建
DATA_DIR = Path(
    os.getenv("FUYIBA_DATA_DIR", "").strip() or ROOT_DIR / "data"
)


def config_file(name: str) -> Path:
    """静态文件的统一入口：config/ 优先，找不到再回退 data/。"""
    preferred = CONFIG_DIR / name
    if preferred.exists():
        return preferred
    legacy = DATA_DIR / name
    return legacy if legacy.exists() else preferred


# --------------------------------------------------------------------------
# QQ 开放平台
# --------------------------------------------------------------------------

API_BASE = os.getenv("QQ_BOT_API_BASE", "").strip() or "https://api.bot.qq.com"
TOKEN_URL = API_BASE + "/app/getAppAccessToken"
GATEWAY_URL = API_BASE + "/gateway"

# GROUP_AND_C2C_EVENT：群 @ 消息、群全量消息都在这一位里。
# INTERACTION：按钮点击（INTERACTION_CREATE），1<<26。
# 面板按钮走的是回调型（action.type=1），不订这一位就收不到点击事件。
INTENTS = (1 << 25) | (1 << 26)

# 被动回复：同一个 msg_id 最多回 5 次，超了改发主动消息。
MAX_PASSIVE_REPLIES = 5

# 官方文本消息有长度上限，长回复按段切开分条发。
REPLY_CHUNK_CHARS = 800

# 排查用：FUYIBA_DEBUG=1 时把收到的原始事件正文也打出来。
DEBUG = os.getenv("FUYIBA_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

# 设了 FUYIBA_LOG=logs/bot.log 就同时追加到文件（start.bat 会自动设）。
LOG_FILE = os.getenv("FUYIBA_LOG", "").strip()

# 是否阻止 Windows 进入睡眠（显示器仍可关）。FUYIBA_KEEP_AWAKE=0 关掉。
KEEP_AWAKE = os.getenv("FUYIBA_KEEP_AWAKE", "").strip().lower() not in {
    "0", "false", "no", "off",
}
