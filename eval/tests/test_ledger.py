"""台账 v1 测试：三处同时累加、b 由实现值算、gate_view 的两种口径不串味。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eval.ledger import (  # noqa: E402
    accumulate, cell_b, empty_cell, gate_view, ingest_trades, load, save, summary,
)
from gate.risk_rules import adjudicate  # noqa: E402


def test_accumulate_updates_three_strata():
    store = {}
    accumulate(store, "A1", "上升", "market", 2.0)
    accumulate(store, "A1", "上升", "limit", -1.0)
    seg = store["A1"]
    assert seg["all"]["n"] == 2 and seg["all"]["wins"] == 1
    assert seg["by_context"]["上升"]["n"] == 2
    assert seg["by_order_type"]["market"]["n"] == 1
    assert seg["by_order_type"]["limit"]["n"] == 1


def test_cell_b_from_realized_r():
    # 2 胜各 +3R、2 负各 −1R → b = 3/1 = 3.0
    store = {}
    for r in (3.0, 3.0, -1.0, -1.0):
        accumulate(store, "A2", "下降", "market", r)
    assert cell_b(store["A2"]["all"]) == 3.0


def test_cell_b_none_when_one_side_missing():
    store = {}
    for r in (2.0, 1.5):
        accumulate(store, "B1", "震荡", "market", r)
    assert cell_b(store["B1"]["all"]) is None      # 无亏损样本 → 不给 b
    assert cell_b(empty_cell()) is None

def test_gate_view_keeps_h6_semantics():
    store = {}
    for _ in range(3):
        accumulate(store, "A1", "上升", "market", -1.0)
    view = gate_view(store)
    assert view[("A1", "上升")]["wins"] == 0 and view[("A1", "上升")]["n"] == 3

def test_save_load_roundtrip(tmp_path):
    store = {}
    accumulate(store, "A1", "上升", "limit", 1.5)
    p = str(tmp_path / "m.json")
    save(store, p)
    assert load(p) == store
    assert load(str(tmp_path / "absent.json")) == {}


def test_ingest_trades_and_summary():
    store = {}
    ingest_trades(store, [
        {"setup": "B3", "context": "震荡", "order_type": "limit", "r": 2.0, "win": True},
        {"setup": "B3", "context": "震荡", "order_type": "market", "r": -1.0, "win": False},
    ])
    rows = summary(store)
    assert rows[0]["setup"] == "B3" and rows[0]["n"] == 2
    assert rows[0]["win_rate"] == 0.5 and rows[0]["b"] == 2.0
    assert rows[0]["by_order_type"] == {"limit": 1, "market": 1}
