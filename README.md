# 弗一把 · 单功能 QQ 官方机器人

一个**「弗一把」**的机器人：Minecraft 物品 & 生物猜猜猜，全群共享 20 轮，
每猜一次给六维反馈，猜中记进本群榜。

零第三方依赖（不需要 NoneBot / httpx / websockets），HTTP 用标准库 urllib，
WebSocket 自己实现。**填好 AppID 和 AppSecret 就能直接跑。**

```
fuyiba-bot/
├─ bot.py                    入口：--selftest / --check / 正式启动
├─ start.bat                 Windows 双击启动（带 UTF-8 和日志）
├─ config/
│   ├─ appid.txt             ← 填机器人的 AppID（一行）
│   ├─ secret.txt            ← 填机器人的 AppSecret（一行）
│   ├─ mc_guess_easy.json    简单题库（1.20.2 及以前）
│   └─ mc_guess_hard.json    困难题库（1.20.5 ~ 26.3 的新内容）
├─ data/                     运行时自动生成
│   ├─ mc_guess_rank.json    本群榜单（落盘，重启不丢）
│   └─ members.json          openid → 群名片（按钮事件里没有昵称，靠它反查）
└─ qqbot/
    ├─ config.py             目录与平台常量
    ├─ base.py               日志 / 事件解析 / HTTP
    ├─ net.py                WebSocket 客户端 + 网关事件循环
    ├─ api.py                QQ 开放平台接口 + 被动回复发送器
    ├─ panel.py              按钮面板（markdown + keyboard）
    ├─ roster.py             openid → 群名片
    ├─ handler.py            只路由「弗一把」
    ├─ mc_guess.py           游戏本体：开局、六维比对、榜单、冷场提醒
    ├─ mc_guess_data.py      简单题库加载与校验
    ├─ mc_guess_data_hard.py 困难题库加载与校验
    └─ selftest.py           离线自检
```

## 跑起来（三步）

1. **Python 3.10+**，命令行里 `python --version` 能看到版本就行，不用装任何包。
2. 去 [QQ 开放平台](https://q.qq.com/) 建一个机器人，拿到 **AppID / AppSecret**，
   在「开发设置」里把机器人拉进测试群或发布上线。需要的能力：
   - 群聊消息（接收 `GROUP_AT_MESSAGE_CREATE` / `GROUP_MESSAGE_CREATE`）
   - **群消息全量接收**：只是 @ 才回的话，别人猜词时没 @ 就收不到，这游戏就没法玩了
   - 按钮 / 交互事件（`INTERACTION_CREATE`，难度面板要用）
3. 把 AppID 写进 `config/appid.txt`、AppSecret 写进 `config/secret.txt`
   （各一行，别加引号、别留空格），然后：

```bash
python bot.py --check      # 先验一下凭据，能取到 token 和网关地址就对了
python bot.py             # 正式启动
```

Windows 上直接双击 `start.bat` 也行（日志写到 `logs/bot.log`）。

自检不需要凭据、不联网：`python bot.py --selftest`，会把「开局 → 猜错 → 猜中 →
榜单 → 认输 → 帮助」整条链路跑一遍。

## 群里怎么玩

| 发什么 | 效果 |
| --- | --- |
| `弗一把` | 弹面板，两个按钮：简单模式 / 困难模式（点了才开局） |
| `弗一把 简单模式` / `弗一把 困难模式` | 不点按钮、直接打字也能开局 |
| 直接发物品名，或 `猜 钻石剑` | 猜一次，占一轮 |
| `弗一把 状态` | 第几轮、还剩几次、谁参与过、本群榜 |
| `弗一把 榜单` | 本群完整榜（按猜中次数） |
| `弗一把 结束` / `认输` / `放弃` | 公布答案，散场 |
| `帮助` | 用法 |

规则细节（都写在 `mc_guess.py` 头部）：

- 20 轮**全群共享**，一局十分钟没人动就散场；
- 六维反馈：名称重合 / 加入版本（⬆️ 答案更新、⬇️ 更旧）/ 类型 / 标签 / 字数 / 生成世界；
- 带颜色的物品只认后缀：猜「羊毛」和「红色羊毛」都算对；
- 第 16、18 轮各给一个字的小提示；
- 猜中的人记一次胜场，进本群榜；同一件东西重复猜不烧轮数；
- 冷场 3 分钟催一句（最多两次，不占轮数）。

## 改题库

题库是纯 JSON，改完重启就生效（不用碰 Python）：

```json
{
  "name": "钻石剑", "version": "1.0", "type": "武器",
  "tags": ["战斗", "矿物"], "world": "主世界",
  "note": "两下砍死一只僵尸。",
  "aliases": ["diamond_sword"], "colored": false, "weight": 1
}
```

字段写错（版本档位 / 类型 / 标签不在词表里、别名互撞、`weight` 非正数）会在
**启动时**直接报错并指出是第几条，不会带着坏数据跑起来。

## 环境变量（可选）

| 变量 | 作用 |
| --- | --- |
| `QQ_BOT_APPID` / `QQ_BOT_SECRET` | 凭据，优先于 config 里的 txt |
| `QQ_BOT_API_BASE` | 接口地址，默认 `https://api.bot.qq.com` |
| `FUYIBA_LOG` | 日志文件路径（`start.bat` 设成 `logs/bot.log`） |
| `FUYIBA_DEBUG` | `1` 时打印收到的原始事件正文 |
| `FUYIBA_KEEP_AWAKE` | `0` 关掉「阻止 Windows 睡眠」 |
| `FUYIBA_CONFIG_DIR` / `FUYIBA_DATA_DIR` | 换 config / data 目录 |

## 说明

- 对局只在内存里，**重启就散场**；榜单和名册落盘，重启还在。
- 这个目录是从主项目 `qqchatbot-official` 里把「弗一把」单独抽出来的，
  只保留了它需要的网关、发送、面板和题库代码。
- 按钮只能点一次：点过之后同一条消息上的按钮会变灰，再开一局要重新发「弗一把」。
