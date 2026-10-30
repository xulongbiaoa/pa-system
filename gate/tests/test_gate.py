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
    # H4 只约束 trainer 局内；annotation（标注/试点）下决策点即「当下」，不截止
    r = adjudicate(_plan(), _pack(), bars_left=5, mode="trainer")
    assert any(h["rule"] == "H4" for h in r["hard_hits"])


def test_h4_not_applied_in_annotation():
    r = adjudicate(_plan(), _pack(), bars_left=5, mode="annotation")
    assert not any(h["rule"] == "H4" for h in r["hard_hits"])
    assert r["verdict"] == "pass"


def test_h3_risk_frac_one_pct_is_the_cap():
    # core 红线 3：单笔风险 1%。1.0% 放行，1.1% 拒绝（原上限 1.5% 已收窄）
    assert adjudicate(_plan(risk_frac=0.01), _pack(), bars_left=50)["verdict"] == "pass"
    r = adjudicate(_plan(risk_frac=0.011), _pack(), bars_left=50)
    assert any(h["rule"] == "H3" for h in r["hard_hits"])


def test_h1_uses_first_target_not_last():
    # 首目标净 RR 不足 1.5，靠加一个远目标不能过关（与回放结算同口径）
    r = adjudicate(_plan(targets=[105.0, 130.0]), _pack(), bars_left=50)
    assert any(h["rule"] == "H1" for h in r["hard_hits"])
    assert r["rr_by_target"][0] < 1.5 < r["rr_by_target"][-1]


def test_soft_rule_uses_last_target_rr():
    # S1 阈值 2.5 按末级口径标定：首目标 1.6 / 末级 3.3 → 不降仓
    r = adjudicate(_plan(targets=[110.0, 130.0]), _pack(), bars_left=50,
                   flags={"parabolic": True})
    assert r["verdict"] == "pass" and r["risk_mult"] == 1.0
    assert not r["soft_hits"]


def test_h6_skipped_notes_when_ledger_missing():
    # 不传台账时不许静默：结果里必须写明 H6 未生效
    r = adjudicate(_plan(), _pack(), bars_left=50)
    assert r["verdict"] == "pass"
    assert any("H6" in n for n in r["notes"])


def test_h6_requires_context_enum():
    ledger = {("A1", "上升"): {"n": 3, "wins": 0}}
    r = adjudicate(_plan(context="下降趋势里的回调多"), _pack(), bars_left=50,
                   ledger=ledger)
    assert not any(h["rule"] == "H6" for h in r["hard_hits"])
    assert any("context" in n for n in r["notes"])


def test_size_hint_never_exceeds_risk_cap():
    """凯利建议只能降不能升：上限是 H3，建议值必须 ≤ 1%。"""
    from gate.risk_rules import RISK_FRAC_MAX
    ledger = {("A1", "上升"): {"n": 400, "wins": 340, "b": 3.0}}  # 极端优势
    r = adjudicate(_plan(), _pack(), bars_left=50, ledger=ledger)
    h = r["size_hint"]
    assert h is not None and h["binding"] == "cap"
    assert h["f_applied"] == RISK_FRAC_MAX and h["b_source"] == "ledger"


def test_size_hint_zero_when_evidence_thin():
    ledger = {("A1", "上升"): {"n": 2, "wins": 1, "b": 2.84}}
    h = adjudicate(_plan(), _pack(), bars_left=50, ledger=ledger)["size_hint"]
    assert h["f_applied"] == 0.0 and h["binding"] == "evidence"


def test_no_size_hint_without_ledger_cell():
    assert adjudicate(_plan(), _pack(), bars_left=50)["size_hint"] is None


def test_h2_round_level_reject_any_price_scale():
    # 关口判据按价格量级取步长：1.58 这类价格也有整数关口（0.05 一档），
    # 原来的 round(stop) 判据对非整数报价资产恒不命中（死代码）
    p = _pack()
    p["seg_avg_range"] = 0.4
    base = _plan(side="short", entry=11.5, stop=12.0, targets=[10.0])
    assert any(h["rule"] == "H2" for h in adjudicate(base, p, bars_left=50)["hard_hits"])
    off = _plan(side="short", entry=11.5, stop=11.91, targets=[10.0])
    assert not any(h["rule"] == "H2" for h in adjudicate(off, p, bars_left=50)["hard_hits"])


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
