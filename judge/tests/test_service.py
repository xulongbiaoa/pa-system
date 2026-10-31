"""统一决策服务测试（T03）：等价迁移 + 状态映射 + H6 可用性。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "eval"))

from gate.risk_rules import adjudicate  # noqa: E402
from judge.service import DecisionRequest, assess_candidate  # noqa: E402


def _pack():
    return {
        "swings": {"major": [{"bar": 5, "kind": "L", "close": 95.0,
                              "anchor": 94.3}]},
        "seg_avg_range": 2.0,
        "gaps": {"confidence": "确定"},
        "ema": {"confidence": "确定"},
        "trend": {"confidence": "确定", "label": "上升"},
        "last_close": 100.0,
    }


def _plan(**kw):
    p = {"side": "long", "entry": 100.0, "stop": 93.87,
         "targets": [110.0], "risk_frac": 0.01, "setup": "A1",
         "context": "上升",
         "cap_reason": "110 上方完好要塞封顶，目标按序列只能取到此处",
         "stop_basis": 94.3}
    p.update(kw)
    return p


def _req(plan, **kw):
    base = dict(snapshot_id="snap1", candidate={"plan": plan},
                feature_pack=_pack(), bars_left=50,
                strategy_version="v-test")
    base.update(kw)
    return DecisionRequest(**base)


def test_eligible_matches_adjudicate_pass():
    plan = _plan()
    r = assess_candidate(_req(plan))
    direct = adjudicate(plan, _pack(), bars_left=50)
    assert r.status == "eligible" and r.rule_hits == []
    assert r.gate == direct  # 原文一致，迁移不改裁决


def test_rejected_keeps_hard_hits_verbatim():
    plan = _plan(targets=[105.0])  # H1 净 RR 不足
    r = assess_candidate(_req(plan))
    direct = adjudicate(plan, _pack(), bars_left=50)
    assert r.status == "rejected" and r.reason_code == "H1"
    assert r.rule_hits == direct["hard_hits"]


def test_waiting_when_conditions_open():
    r = assess_candidate(_req(_plan(),
                              condition_result={"open_required": ["r2"]}))
    assert r.status == "waiting" and r.missing == ["r2"]
    assert r.gate is None  # 未进 gate 定价


def test_invalid_input_on_incomplete_plan():
    r = assess_candidate(_req({"entry": 100.0}))
    assert r.status == "invalid_input" and r.reason_code == "INVALID_INPUT"


def test_h6_unavailable_is_structured_not_pass():
    r = assess_candidate(_req(_plan(), ledger=None))
    assert r.h6_status == "unavailable"
    r2 = assess_candidate(_req(_plan(), ledger={}))
    assert r2.h6_status == "checked"
