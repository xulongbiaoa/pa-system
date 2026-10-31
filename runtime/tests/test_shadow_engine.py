"""T07 在线影子引擎端到端：事件→机会→唤醒→评估→决策→模拟持仓。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.levels import build_watch_levels  # noqa: E402
from runtime.opportunities import Condition, Opportunity  # noqa: E402
from runtime.opportunity_store import FileOpportunityStore  # noqa: E402
from runtime.shadow_engine import ShadowEngine  # noqa: E402

PLAN = {"side": "long", "entry": 100.0, "stop": 93.87, "targets": [110.0],
        "risk_frac": 0.01, "setup": "A1", "context": "上升",
        "cap_reason": "110 上方完好要塞封顶", "stop_basis": 94.3,
        "order_type": "limit"}


def _pack():
    return {"swings": {"major": [{"bar": 5, "kind": "L", "close": 95.0,
                                  "anchor": 94.3}]},
            "seg_avg_range": 2.0,
            "gaps": {"confidence": "确定"}, "ema": {"confidence": "确定"},
            "trend": {"confidence": "确定", "label": "上升"},
            "last_close": 100.0,
            "fortress": {"bands": [{"lo": 88.0, "hi": 90.0}]},
            "gaps_open": None}


def _opp():
    return Opportunity(
        opportunity_id="opp1", state="WATCHING",
        unknown_policy="review_hold",
        conditions=[
            Condition(id="r1", role="required", text="离开后回踩收回",
                      recheck_mode="leave_then_return"),
            Condition(id="r2", role="required", text="净 RR 复核")])


def _bar(t, o, h, l, c):
    return {"t": t, "o": o, "h": h, "l": l, "c": c}


def _engine(tmp_path, assessor):
    levels = build_watch_levels(
        map_doc={"points": [{"id": "P4", "lo": 100.0, "hi": 102.0}]},
        pack=None)
    store = FileOpportunityStore(str(tmp_path / "opps.json"))
    with store:
        store.upsert(_opp())
    return ShadowEngine(store, levels, bindings={"opp1": "P4"},
                        assessor=assessor,
                        pack_provider=lambda o, ctx: _pack())


def test_levels_sources():
    pack = _pack()
    pack["gaps"] = {"open": [{"anchor": 97.5, "kind": "breakout"}],
                    "confidence": "确定"}
    levels = build_watch_levels(
        map_doc={"points": [{"id": "P4", "lo": 100.0, "hi": 102.0}]},
        pack=pack)
    srcs = {lv.level_id: lv.source for lv in levels}
    assert srcs["P4"] == "model"
    assert any(lid.startswith("FORT") for lid in srcs)
    gap = [lv for lv in levels if lv.level_id.startswith("GAP")][0]
    assert gap.lo == gap.hi == 97.5
    assert gap.watch_lo == 97.0 and gap.watch_hi == 98.0  # ±0.25×2.0


def test_full_chain_to_simulated_position(tmp_path):
    calls = {"n": 0}

    def assessor(opp, ctx):
        calls["n"] += 1
        if calls["n"] < 3:
            return {"conditions": {"r1": "not_met", "r2": "met"}}
        return {"conditions": {"r1": "met", "r2": "met"}, "plan": PLAN}

    eng = _engine(tmp_path, assessor)
    eng.feed_bar(_bar(1, 109, 110, 108, 109))       # 远离，无事
    eng.feed_bar(_bar(2, 103, 103, 101, 101.5))     # 首次触及 → TESTING
    eng.run_assessments()                            # r1 未成 → WAITING
    eng.feed_bar(_bar(3, 107, 108, 104, 107))       # 整根离开 → 武装
    eng.run_assessments()
    eng.feed_bar(_bar(4, 100.5, 101.5, 99.5, 100.5))  # 返回再测 → 唤醒
    eng.run_assessments()                            # 全成 + 计划 → 决策

    with eng.store:
        opp = eng.store.get("opp1")
    assert opp.state == "IN_POSITION"
    assert opp.test_sequence >= 2
    assert "opp1" in eng.tracked
    kinds = eng.audit_kinds()
    assert "level_event" in kinds and "wake" in kinds
    assert "decision" in kinds and "position_opened" in kinds
    dec = [r for r in eng.audit if r["kind"] == "decision"][0]
    assert dec["status"] == "eligible"


def test_gate_reject_cancels_opportunity(tmp_path):
    bad = dict(PLAN, targets=[105.0])  # H1 净 RR 不足

    def assessor(opp, ctx):
        return {"conditions": {"r1": "met", "r2": "met"}, "plan": bad}

    eng = _engine(tmp_path, assessor)
    eng.feed_bar(_bar(1, 109, 110, 108, 109))
    eng.feed_bar(_bar(2, 103, 103, 101, 101.5))
    eng.run_assessments()
    with eng.store:
        opp = eng.store.get("opp1")
    assert opp.state == "CANCELLED" and opp.reason_code == "GATE_REJECTED"
    dec = [r for r in eng.audit if r["kind"] == "decision"][0]
    assert dec["status"] == "rejected" and dec["reason_code"] == "H1"
    assert eng.tracked == {}
