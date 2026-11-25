"""按钮面板：把「文字标签 + 命令」拼成平台要的 keyboard 结构。

几条平台硬限制（改之前先看）：
* 按钮只能挂在 markdown 消息上（msg_type=2）；
* 最多 5 行、每行最多 5 个，超了报 40034029；
* ``render_data.label`` 最多 10 个字符，而且实际是按宽度截的 —— 按钮上只放名字；
* 群里指令型按钮（type=2）点了只会把命令填进输入框，所以一律用回调型（type=1）。
"""
from __future__ import annotations

MAX_ROWS = 5
MAX_BUTTONS_PER_ROW = 5
MAX_LABEL_CHARS = 10


def make_button(label: str, data: str = "", style: int = 0, *,
                group_id: str = "", modal: str = "",
                user_ids: tuple[str, ...] | list[str] = ()) -> dict:
    """造一个回调型按钮。

    ``user_ids`` 非空时只有这些人能点（自己的面板只有自己能按）；
    ``group_id`` 非空时同组按钮互斥变灰；``modal`` 非空时点击先弹二次确认。
    """
    text = (label or "")[:MAX_LABEL_CHARS]
    allowed = [str(uid) for uid in user_ids if str(uid or "").strip()]
    action: dict = {
        "type": 1,
        "permission": ({"type": 0, "specify_user_ids": allowed} if allowed
                       else {"type": 2}),
        "data": data or label,
        "unsupport_tips": f"客户端版本过低，直接发「{data or label}」也一样",
    }
    if modal:
        action["modal"] = {"content": modal[:40], "confirm_text": "好的",
                           "cancel_text": "算了"}
    button: dict = {
        "render_data": {"label": text, "visited_label": text, "style": style},
        "action": action,
    }
    if group_id:
        button["group_id"] = group_id
    return button


def build_rows(rows: list[list], highlight: bool = False,
               user_ids: tuple[str, ...] | list[str] = ()) -> list[dict]:
    """``[["简单模式", "困难模式"]]`` → ``[{"buttons": [...]}]``。

    每一项可以是字符串（label 即 data），也可以是 ``(label, data)`` 二元组。
    超限的按钮直接丢掉（宁可少一行，也别整条消息被拒）。
    """
    built: list[dict] = []
    for row_index, row in enumerate(rows):
        if row_index >= MAX_ROWS:
            break
        buttons = []
        for index, item in enumerate(row):
            if isinstance(item, (tuple, list)) and len(item) == 2:
                label, data = str(item[0] or ""), str(item[1] or "")
            else:
                label, data = str(item or ""), ""
            if not label.strip():
                continue
            style = 1 if highlight and row_index == 0 and index == 0 else 0
            buttons.append(make_button(label, data, style, user_ids=user_ids))
            if len(buttons) >= MAX_BUTTONS_PER_ROW:
                break
        if buttons:
            built.append({"buttons": buttons})
    return built
