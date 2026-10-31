"""内存 Repository（W04/W07 离线形态 / 方案 §9/§12）。

事件日志是事实记录，快照只是重放加速。相同版本与事件序列重建得到相同投影哈希。
- 同 ID 同内容 bar：幂等忽略（不产生事件、不涨 revision）。
- 同 ID 不同价格：记修订冲突并隔离，不应用到状态（进重建流程）。
- 迟到 bar（open_time 早于已处理序且 ID 未知）：拒绝并登记。
- 历史重建（replay）不派发任何实时命令——本层根本没有命令出口。
持久化（PostgreSQL）按方案 §12 是 W07 的事务存储形态，本版先以内存实现同一契约：
commit(expected_revision) 冲突即抛错，调用方重读再处理。
"""
from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional

from .contracts import Bar
from .reducers import Battlefield


class RevisionConflict(Exception):
    pass


class InMemoryRepository:
    def __init__(self, kernel: Battlefield):
        self.kernel = kernel
        self.bars_by_id: Dict[str, Bar] = {}
        self.quarantine: List[Bar] = []
        self.snapshots: Dict[int, dict] = {}   # revision -> 状态投影（加速重放/查询）
        self.rev_last_seq: Dict[int, int] = {}  # revision -> 该版本末事件 sequence

    # ---------- 写入 ----------
    def commit_bar(self, bar: Bar, expected_revision: Optional[int] = None) -> dict:
        """返回 {status: applied|duplicate_ignored|revision_conflict|late_rejected, events:[...]}"""
        if expected_revision is not None and expected_revision != self.kernel.revision:
            raise RevisionConflict(f"expected {expected_revision}, actual {self.kernel.revision}")
        existing = self.bars_by_id.get(bar.id)
        if existing is not None:
            if existing.same_content(bar):
                return {"status": "duplicate_ignored", "events": []}
            self.kernel.data_health["revision_conflicts"] += 1
            self.kernel.unresolved.append({"kind": "revision_conflict", "bar_id": bar.id})
            self.quarantine.append(bar)
            return {"status": "revision_conflict", "events": []}
        if self.kernel.bars and bar.open_time <= self.kernel.bars[-1].open_time:
            self.kernel.data_health["late_bars"] += 1
            self.kernel.unresolved.append({"kind": "late_bar", "bar_id": bar.id})
            return {"status": "late_rejected", "events": []}
        events = self.kernel.process_bar(bar)
        self.bars_by_id[bar.id] = bar
        self.snapshots[self.kernel.revision] = self.kernel.state_dict()
        self.rev_last_seq[self.kernel.revision] = self.kernel._seq
        return {"status": "applied", "events": events}

    # ---------- 读取 ----------
    def projection_hash(self, revision: Optional[int] = None) -> str:
        state = self.snapshots[revision] if revision is not None else self.kernel.state_dict()
        blob = json.dumps(state, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def state_at_revision(self, revision: int) -> Optional[dict]:
        return self.snapshots.get(revision)

    def events(self):
        return list(self.kernel.events)


def replay(symbol, timeframe, timeframe_ms, bars, *, levels=(), targets=(),
           enable_swings=False) -> InMemoryRepository:
    """从原始 bar 全量重建（研究模式）：结果只用于核对哈希，不触发任何实时动作。"""
    kernel = Battlefield(symbol, timeframe, timeframe_ms, enable_swings=enable_swings)
    repo = InMemoryRepository(kernel)
    for lv in levels:
        kernel.register_level(lv)
    for t in targets:
        kernel.register_target(t)
    for b in bars:
        repo.commit_bar(b)
    return repo
