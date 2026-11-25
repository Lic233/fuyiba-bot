"""记住每个群里见过的人：member_openid → 群名片。

为什么需要：按钮点击事件（INTERACTION_CREATE）里**只有** openid，没有昵称，
而「谁猜中的」要写进榜单。所以每条群消息顺手记一下名字，点击时反查。
落盘 data/members.json，重启不丢。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .base import log


class Roster:
    def __init__(self, data_dir: Path) -> None:
        self.file = Path(data_dir) / "members.json"
        try:
            payload = json.loads(self.file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            payload = {}
        self.records: dict[str, dict[str, str]] = {}
        if isinstance(payload, dict):
            for group, members in payload.items():
                if isinstance(members, dict):
                    self.records[str(group)] = {
                        str(user): str(name) for user, name in members.items()
                        if isinstance(name, str)
                    }
        self._dirty = False
        self._last_save = 0.0

    def remember(self, group: str, user: str, name: str) -> None:
        """记一个名字。空名字不能把已记下的冲掉（按钮事件里就没有名字）。"""
        if not group or not user or not (name or "").strip():
            return
        members = self.records.setdefault(str(group), {})
        if members.get(str(user)) != name:
            members[str(user)] = name
            self._dirty = True
            self.flush()

    def name_of(self, group: str, user: str) -> str:
        """这个人的群名片；没见过就返回空串。"""
        return (self.records.get(str(group)) or {}).get(str(user), "")

    def flush(self, force: bool = False) -> None:
        """落盘。默认 30 秒内的多次改动合并成一次写。"""
        if not self._dirty:
            return
        now = time.time()
        if not force and now - self._last_save < 30:
            return
        temporary = self.file.with_name("members.tmp")
        try:
            temporary.write_text(
                json.dumps(self.records, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.file)
            self._dirty = False
            self._last_save = now
        except OSError as error:
            log(f"[名册] 保存失败：{error}")
