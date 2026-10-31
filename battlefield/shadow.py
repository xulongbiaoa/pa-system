"""滚动影子账本（W07 的文件形态 / 方案 §9 的重放纪律）。

设计：进程无状态，账本是文件。
- bars.jsonl：全部已收盘 K 线（只追加，不删——删旧根会让摆动序号漂移、旧引用失效）。
- brain_outputs.jsonl：已成功落账的大脑输出（按 read_cursor 升序）。
- 恢复 = 交错重放：逐根提交 bar，每当 repo revision 到达下一份输出的 read_cursor，
  就在该版本上原样重跑那份输出。投影确定性保证恢复结果与当时一致；
  任何一份输出在恢复时校验不过，立即停并报错，不带病继续。
- pending_package：大脑尚未消费到当前 revision 时，产出待判读包；没有新根就不开跑。
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Callable, List, Optional

from .brain import BrainSession, RecordedAdapter, build_task_package
from .contracts import Bar, make_bar
from .repository import InMemoryRepository
from .runner import build_battlefield


def _bar_to_json(b: Bar) -> dict:
    return {"symbol": b.symbol, "timeframe": b.timeframe, "open_time": b.open_time,
            "close_time": b.close_time, "open": str(b.open), "high": str(b.high),
            "low": str(b.low), "close": str(b.close), "source": b.source,
            "received_at": b.received_at, "data_revision": b.data_revision}


def _bar_from_json(d: dict) -> Bar:
    return make_bar(d["symbol"], d["timeframe"], d["open_time"], d["close_time"],
                    d["open"], d["high"], d["low"], d["close"],
                    source=d.get("source", "external"),
                    received_at=d.get("received_at", 0),
                    data_revision=d.get("data_revision", 1))


class ShadowBook:
    def __init__(self, workdir: str, symbol: str, timeframe: str, timeframe_ms: int,
                 factory: Optional[Callable[[List[Bar]], InMemoryRepository]] = None):
        self.workdir = workdir
        self.symbol = symbol
        self.timeframe = timeframe
        self.timeframe_ms = timeframe_ms
        self.factory = factory or (lambda bars: build_battlefield(symbol, timeframe, timeframe_ms, bars))
        os.makedirs(workdir, exist_ok=True)
        self.bars_path = os.path.join(workdir, "bars.jsonl")
        self.outputs_path = os.path.join(workdir, "brain_outputs.jsonl")
        self.runs_path = os.path.join(workdir, "runs.jsonl")

    # ---------- 读写 ----------
    def _read_bars(self) -> List[Bar]:
        if not os.path.exists(self.bars_path):
            return []
        with open(self.bars_path) as f:
            return [_bar_from_json(json.loads(line)) for line in f if line.strip()]

    def _read_outputs(self) -> List[dict]:
        if not os.path.exists(self.outputs_path):
            return []
        with open(self.outputs_path) as f:
            return [json.loads(line) for line in f if line.strip()]

    def _append_jsonl(self, path: str, obj: dict) -> None:
        with open(path, "a") as f:
            f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")

    # ---------- 交错重放恢复 ----------
    def rebuild(self):
        """返回 (repo, session)：战场与大脑状态都恢复到账本末尾。"""
        bars = self._read_bars()
        outputs = self._read_outputs()
        # 用空仓逐根推进，才能在每个 revision 上交错重跑大脑输出
        repo = self._empty_repo()
        session = BrainSession(repo, RecordedAdapter([]))
        pending = list(outputs)
        for b in bars:
            res = repo_bars_commit(repo, b)
            if res["status"] not in ("applied", "duplicate_ignored"):
                raise RuntimeError(f"恢复时 bar 异常: {b.id} -> {res['status']}")
            while pending and pending[0].get("read_cursor") == repo.kernel.revision:
                out = pending.pop(0)
                session.adapter = RecordedAdapter([out])
                result = session.run_once()
                if result["status"] != "ok":
                    raise RuntimeError(f"恢复时大脑输出校验不过: {result}")
        if pending:
            raise RuntimeError(f"有 {len(pending)} 份大脑输出的 read_cursor 在重放中从未到达")
        return repo, session

    def _empty_repo(self) -> InMemoryRepository:
        """与 factory 等价的空仓：factory 必须支持空 bars 构建。"""
        return self.factory([])

    # ---------- 推进 ----------
    def append_bars(self, new_bars: List[Bar]) -> int:
        existing = self._read_bars()
        last_open = existing[-1].open_time if existing else None
        added = 0
        for b in new_bars:
            if last_open is None or b.open_time > last_open:
                self._append_jsonl(self.bars_path, _bar_to_json(b))
                last_open = b.open_time
                added += 1
        return added

    def pending_package(self):
        repo, session = self.rebuild()
        if session.read_revision == repo.kernel.revision:
            return repo, session, None
        return repo, session, build_task_package(repo, session.read_revision)

    def apply_output(self, output: dict) -> dict:
        repo, session = self.rebuild()
        session.adapter = RecordedAdapter([output])
        result = session.run_once()
        if result["status"] == "ok":
            self._append_jsonl(self.outputs_path, output)
        self._append_jsonl(self.runs_path, {"result": result})
        return result


def repo_bars_commit(repo: InMemoryRepository, bar: Bar) -> dict:
    return repo.commit_bar(bar)
