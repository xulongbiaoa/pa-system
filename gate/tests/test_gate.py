"""裁决层测试：硬规则拒绝、软规则只降仓、回放口径。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "eval"))

from gate.risk_rules import adjudicate  # noqa: E402
from replay import simulate_trade  # noqa: E402


def _pack():
    return {
        "swings": {"major": [{"bar": 5, "kind": "L", "close": 95.0, "anchor": 94.3}]},
        "seg_avg_range": 2.0,
        "gaps": {"confidence": "确定"},
        "ema": {"confidence": "确定"},
        "trend": {"confidence": "确定"},
    }


def _plan(**kw):
    p = {
        "side": "long",
        "entry": 100.0,
        "stop": 93.87,  # 在摆动低点 94.3 之外，且不压整数位
        "targets": [110.0],  # 净 RR 约 1.59
        "risk_frac": 0.01,
        "setup": "A1",
        "context": "上升",
    }
    p.update(kw)
    return p


def test_pass_clean_plan():
    r = adjudicate(_plan(), _pack(), bars_left=50, feature_refs=["trend.label"])
    assert r["verdict"] == "pass" and r["risk_mult"] == 1.0


def test_h1_rr_reject():
    r = adjudicate(_plan(targets=[105.0]), _pack(), bars_left=50)
    assert r["verdict"] == "reject" and any(h["rule"] == "H1" for h in r["hard_hits"])


def test_h2_stop_inside_structure_reject():
    r = adjudicate(_plan(stop=95.0), _pack(), bars_left=50)
    assert any(h["rule"] == "H2" for h in r["hard_hits"])


def test_h4_cutoff_reject():
    r = adjudicate(_plan(), _pack(), bars_left=5)
    assert any(h["rule"] == "H4" for h in r["hard_hits"])


def test_h5_undefined_feature_reject():
    pack = _pack()
    pack["gaps"] = {"confidence": "未定"}
    r = adjudicate(_plan(), pack, bars_left=50, feature_refs=["gaps.open"])
    assert any(h["rule"] == "H5" for h in r["hard_hits"])


def test_h6_suspended_mode_reject():
    ledger = {("A1", "上升"): {"n": 3, "wins": 0}}
    r = adjudicate(_plan(), _pack(), bars_left=50, ledger=ledger)
    assert any(h["rule"] == "H6" for h in r["hard_hits"])


def test_soft_rule_downgrades_not_rejects():
    r = adjudicate(_plan(), _pack(), bars_left=50, flags={"parabolic": True})
    assert r["verdict"] == "pass" and r["risk_mult"] == 0.5
    assert any(s["rule"] == "S1" for s in r["soft_hits"])


def test_replay_stop_priority_same_bar():
    bars = [{"o": 101, "h": 112, "l": 93, "c": 105, "v": 1}]  # 同根同碰止损与目标
    t = simulate_trade(bars, "long", 100.0, 94.0, 110.0)
    assert t["exit_price"] == 94.0 and t["r"] < 0  # 止损优先


def test_replay_target_hit():
    bars = [{"o": 101, "h": 111, "l": 99, "c": 108, "v": 1}]
    t = simulate_trade(bars, "long", 100.0, 94.0, 110.0)
    assert t["exit_price"] == 110.0 and t["win"]
