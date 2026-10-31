"""H8 设计目标说明义务（2026-10-31 审计处置「RR 应试化」）。

core 口径：首目标毛 RR 取不到设计目标 2:1，必须点名封顶结构
（plan.cap_reason），不许默默贴着 1.5 地板画。gate 只在 H1 已过时
查 H8，避免与 H1 叠报。
"""
from gate.risk_rules import adjudicate

PACK = {
    "last_close": 100.0, "seg_avg_range": 2.0,
    "swings": {"major": [{"bar": 5, "kind": "L", "close": 98.6,
                          "anchor": 98.3}], "minor": []},
    "gaps": {"confidence": "确定"}, "ema": {"confidence": "确定"},
    "trend": {"confidence": "确定"},
}


def _plan(**kw):
    # 多：入 100、止损 97.87（风险 2.13，不压整数关口）、目标 103.62
    # → 毛 RR 1.7（过 H1 地板、不到设计目标 2:1）
    p = {"side": "long", "entry": 100.0, "stop": 97.87, "stop_basis": 98.3,
         "targets": [103.62], "risk_frac": 0.01, "setup": "A1",
         "context": "上升"}
    p.update(kw)
    return p


def test_h8_rejects_marginal_rr_without_cap_reason():
    v = adjudicate(_plan(), PACK, bars_left=300, mode="annotation")
    assert v["verdict"] == "reject"
    assert [h["rule"] for h in v["hard_hits"]] == ["H8"]


def test_h8_passes_with_cap_reason():
    v = adjudicate(_plan(cap_reason="上方 103.5 完好要塞封顶（带锚 6、未踩踏）"),
                   PACK, bars_left=300, mode="annotation")
    assert v["verdict"] == "pass"


def test_h8_silent_when_design_target_met():
    v = adjudicate(_plan(targets=[104.69]), PACK, bars_left=300,
                   mode="annotation")
    assert v["verdict"] == "pass"


def test_h8_not_stacked_on_h1_reject():
    v = adjudicate(_plan(targets=[102.0]), PACK, bars_left=300,
                   mode="annotation")
    rules = [h["rule"] for h in v["hard_hits"]]
    assert "H1" in rules and "H8" not in rules
