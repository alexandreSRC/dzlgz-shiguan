"""撤销 / 重做栈。

与 v1 语义完全一致：整份 people 快照 + cutoff_person，上限 20 步，
新操作会截断"未来"分支。
"""
import json
import logging

logger = logging.getLogger(__name__)

MAX_HISTORY = 20


def _limit_for(people) -> int:
    """快照步数上限按谱牒规模自适应（★ 2026-09-26 审查修复 M5）。

    每步快照是**整本 people 的 JSON 串** —— 13,526 人的《全史存档》一步
    ≈8MB，20 步 ≈160MB 常驻内存，而且每次编辑都要全量 dumps 一次。
    大谱牒上把上限降下来（撤销深度换内存），小谱牒保持 20 步不变：
      ≤3000 人 → 20 步；≤8000 人 → 8 步；更大 → 4 步。
    """
    n = len(people or {})
    if n <= 3000:
        return MAX_HISTORY
    if n <= 8000:
        return 8
    return 4


class History:
    def __init__(self, on_apply):
        """on_apply(people, cutoff_person) —— 由调用方负责落盘与重绘。"""
        self._on_apply = on_apply
        self._stack = []
        self._index = -1

    # ------------------------------------------------------------ 记录
    def record(self, action, people, cutoff_person):
        if self._index < len(self._stack) - 1:
            self._stack = self._stack[:self._index + 1]
        self._stack.append({
            "action": action,
            "state": json.dumps(people),
            "cutoff": cutoff_person,
        })
        limit = _limit_for(people)
        while len(self._stack) > limit:
            self._stack.pop(0)
        self._index = len(self._stack) - 1

    def clear(self):
        self._stack.clear()
        self._index = -1

    # ------------------------------------------------------------ 查询
    @property
    def can_undo(self):
        return self._index > 0

    @property
    def can_redo(self):
        return self._index < len(self._stack) - 1

    @property
    def current_action(self):
        if 0 <= self._index < len(self._stack):
            return self._stack[self._index]["action"]
        return ""

    # ------------------------------------------------------------ 操作
    def undo(self):
        if not self.can_undo:
            logger.info("没有可撤回的操作")
            return False
        self._index -= 1
        entry = self._stack[self._index]
        logger.info(f"撤销操作: {entry['action']}")
        self._on_apply(json.loads(entry["state"]), entry.get("cutoff"))
        return True

    def redo(self):
        if not self.can_redo:
            logger.info("没有可恢复的操作")
            return False
        self._index += 1
        entry = self._stack[self._index]
        logger.info(f"恢复操作: {entry['action']}")
        self._on_apply(json.loads(entry["state"]), entry.get("cutoff"))
        return True
