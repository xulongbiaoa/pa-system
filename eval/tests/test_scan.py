"""逐根扫描测试：去重叠是这套协议的核心，必须能证明它真的在去重叠。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import scan  # noqa: E402


def _seg(n=100):
    return {"id": "synthetic",
            "bars": [{"t": i, "o": 100, "h": 101, "l": 99, "c": 100, "v": 1}
                     for i in range(n)]}


def _hit(entry_bar, exit_bar, side="long", r=1.0):
    return {"entry_bar": entry_bar, "exit_bar": exit_bar, "side": side,
            "r": r, "win": r > 0}


def test_scan_segment_drops_overlapping_hits(monkeypatch):
    hits = [
        _hit(40, 10),   # 留：离场 40+1+10 = 51
        _hit(45, 3),    # 丢：45 < 51，结局窗与上一笔重叠
        _hit(60, 2, side="short", r=-1.0),  # 留：60 >= 51
    ]
    monkeypatch.setattr(scan, "simple_baseline", lambda *a, **k: hits)
    out = scan.scan_segment(_seg())
    assert [t["entry_bar"] for t in out] == [40, 60]
    assert [t["setup"] for t in out] == ["A1", "A2"]


def test_scan_segment_tags_contract_fields(monkeypatch):
    monkeypatch.setattr(scan, "simple_baseline", lambda *a, **k: [_hit(50, 4)])
    t = scan.scan_segment(_seg())[0]
    for k in ("segment", "setup", "context", "order_type", "r"):
        assert k in t
    assert t["segment"] == "synthetic" and t["order_type"] == "market"


def test_scan_segment_keeps_adjacent_non_overlapping(monkeypatch):
    # 上一笔恰好在前一根离场 → 允许（entry_bar == last_exit 边界）
    hits = [_hit(40, 9), _hit(50, 2)]   # 离场 40+1+9 = 50
    monkeypatch.setattr(scan, "simple_baseline", lambda *a, **k: hits)
    assert len(scan.scan_segment(_seg())) == 2


def test_budget_uses_total_segments_not_hit_segments():
    trades = [{"segment": "s%d" % (i % 6), "r": 1.0} for i in range(12)]
    b = scan.budget(trades, total_segments=50, cells=2)
    assert b["trades_per_segment"] == 0.24          # 12/50，不是 12/6
    assert b["trades_per_cell"] == 6.0
    assert b["segments_needed_per_cell"] == 250     # 30/6 × 50
    assert b["bars_needed_per_cell"] == 120000


def test_budget_empty_pool_is_none_not_zero():
    b = scan.budget([], total_segments=50)
    assert b["trades"] == 0 and b["segments_needed_per_cell"] is None
