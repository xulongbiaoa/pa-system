"""waits→Opportunity 桥测试：due 不再是终态，重判结果落回同一机会。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import forward_opportunity_bridge as bridge  # noqa: E402
from runtime.opportunity_store import FileOpportunityStore  # noqa: E402


def mk_wait(status="due"):
    return {"wait_id": "ev1::B3", "event": "ev1", "symbol": "BTCUSDT",
            "interval": "15m", "setup": "B3",
            "bands": [{"lo": 100.0, "hi": 102.0, "src": "map:P4"}],
            "frozen_missing": [
                {"condition": "回踩 P4 后收回带内",
                 "evidence": "决策根未收回",
                 "basis": {"type": "branch", "ref": "P4"}},
                {"condition": "净 RR 复核", "evidence": "",
                 "basis": {"type": "card", "ref": "B3-N5"}}],
            "watch": "P4 测试行为", "status": status,
            "due": {"t": 12345, "close": 101.0} if status == "due" else None,
            "closed": None, "history": []}


def test_opportunity_from_wait_keeps_frozen_conditions():
    opp = bridge.opportunity_from_wait(mk_wait())
    assert opp.state == "WAITING_BEHAVIOR" and opp.point_id == "P4"
    assert [c.text for c in opp.conditions] == ["回踩 P4 后收回带内", "净 RR 复核"]
    assert opp.conditions[0].recheck_mode == "leave_then_return"
    assert opp.conditions[1].recheck_mode == "new_evidence"


def test_dispatch_is_idempotent(tmp_path):
    store = FileOpportunityStore(str(tmp_path / "o.json"))
    waits = {"ev1::B3": mk_wait()}
    assert bridge.dispatch_due(waits, store) == 1
    assert bridge.dispatch_due(waits, store) == 0
    assert len(store.pending_tasks("rejudge")) == 1


def test_still_missing_reopens_wait_same_opportunity(tmp_path):
    store = FileOpportunityStore(str(tmp_path / "o.json"))
    waits = {"ev1::B3": mk_wait()}
    bridge.dispatch_due(waits, store)
    before = store.get("ev1::B3")
    state = bridge.apply_outcome(waits, store, "ev1::B3", "still_missing")
    after = store.get("ev1::B3")
    assert state == "WAITING_BEHAVIOR"
    assert after.assessment_count == before.assessment_count + 1
    assert after.test_sequence == before.test_sequence  # 重判不涨测试序
    assert waits["ev1::B3"]["status"] == "open"  # due 不再是终态
    assert store.pending_tasks("rejudge") == []


def test_invalidated_closes_both(tmp_path):
    store = FileOpportunityStore(str(tmp_path / "o.json"))
    waits = {"ev1::B3": mk_wait()}
    bridge.dispatch_due(waits, store)
    state = bridge.apply_outcome(waits, store, "ev1::B3", "invalidated")
    assert state == "INVALIDATED"
    assert waits["ev1::B3"]["status"] == "cancelled"


def test_ready_moves_opportunity(tmp_path):
    store = FileOpportunityStore(str(tmp_path / "o.json"))
    waits = {"ev1::B3": mk_wait()}
    bridge.dispatch_due(waits, store)
    state = bridge.apply_outcome(waits, store, "ev1::B3", "ready")
    assert state == "READY"
