"""机会状态机测试（设计 v2.2 §15/§22 验收 C02/C04/C16/C17/C18/C19）。"""

from runtime.opportunities import (
    Condition, Opportunity, apply_assessment, note_bar, transition)
from runtime.opportunity_store import FileOpportunityStore, StoreLocked


def mk_opp(**kw):
    conds = [Condition(id="r1", role="required"),
             Condition(id="r2", role="required", evaluator="deterministic"),
             Condition(id="b1", role="enhancing"),
             Condition(id="v1", role="veto")]
    return Opportunity(opportunity_id="opp1", conditions=conds, **kw)


def test_watch_to_testing_on_touch():
    opp = mk_opp()
    r = transition(opp, {"kind": "zone_touched"})
    assert opp.state == "TESTING" and opp.test_sequence == 1
    assert r.commands and r.commands[0]["type"] == "assess_behavior"


def test_assessment_missing_goes_waiting_and_counts():
    opp = mk_opp(state="TESTING")
    r = apply_assessment(opp, {"r1": "met", "r2": "not_met"},
                         revision=opp.revision)
    assert opp.state == "WAITING_BEHAVIOR" and opp.assessment_count == 1
    assert r.accepted


def test_enhancing_missing_does_not_block_ready():
    opp = mk_opp(state="TESTING")
    apply_assessment(opp, {"r1": "met", "r2": "met", "b1": "not_met",
                           "v1": "not_met"}, revision=opp.revision)
    assert opp.state == "READY"


def test_veto_unknown_blocks_but_not_invalidates():
    opp = mk_opp(state="TESTING")
    apply_assessment(opp, {"r1": "met", "r2": "met", "v1": "unknown"},
                     revision=opp.revision)
    assert opp.state == "WAITING_BEHAVIOR"


def test_cancel_has_priority_over_met():
    opp = mk_opp(state="TESTING")
    apply_assessment(opp, {"r1": "met", "r2": "met", "v1": "not_met"},
                     revision=opp.revision, cancel_hit=True)
    assert opp.state == "INVALIDATED" and opp.reason_code == "CANCEL_HIT"


def test_space_insufficient_waits_not_invalidates():
    opp = mk_opp(state="TESTING")
    apply_assessment(opp, {"r1": "met", "r2": "met", "v1": "not_met"},
                     revision=opp.revision, plan_valid=False)
    assert opp.state == "WAITING_BEHAVIOR"
    assert opp.reason_code == "SPACE_INSUFFICIENT"


def test_late_assessment_does_not_overwrite():
    opp = mk_opp(state="TESTING")
    apply_assessment(opp, {"r1": "met", "r2": "met", "v1": "not_met"},
                     revision=opp.revision)
    assert opp.state == "READY"
    rev = opp.revision
    opp.state = "WAITING_BEHAVIOR"  # 模拟后续状态已推进
    r = apply_assessment(opp, {"r1": "not_met"}, revision=rev - 1)
    assert r.accepted is False and opp.state == "WAITING_BEHAVIOR"
    assert opp.assessment_count == 1  # 迟到不计


def test_full_order_lifecycle():
    opp = mk_opp(state="READY")
    transition(opp, {"kind": "risk_reserved"})
    assert opp.state == "SUBMITTING"
    transition(opp, {"kind": "order_accepted"})
    assert opp.state == "ORDER_PENDING"
    transition(opp, {"kind": "filled"})
    assert opp.state == "IN_POSITION"
    transition(opp, {"kind": "position_closed"})
    assert opp.state == "CLOSED"


def test_cancel_after_submit_only_requests():
    opp = mk_opp(state="ORDER_PENDING")
    r = transition(opp, {"kind": "deterministic_cancel"})
    assert opp.state == "ORDER_PENDING" and opp.cancel_requested is True
    assert r.commands[0]["type"] == "cancel_order"
    transition(opp, {"kind": "order_cancelled"})
    assert opp.state == "CANCELLED"


def test_api_error_touches_nothing():
    opp = mk_opp(state="WAITING_BEHAVIOR", unknown_streak={"r1": 2})
    transition(opp, {"kind": "api_error", "detail": "timeout"})
    assert opp.assessment_count == 0 and opp.unknown_streak == {"r1": 2}
    assert opp.state == "WAITING_BEHAVIOR"


def test_unknown_streak_and_review_hold():
    opp = mk_opp(state="TESTING", unknown_policy="review_hold",
                 unknown_limit=2)
    apply_assessment(opp, {"r1": "unknown"}, revision=opp.revision)
    assert opp.review_status == ""
    apply_assessment(opp, {"r1": "unknown"}, revision=opp.revision)
    assert opp.review_status == "held" and opp.state == "WAITING_BEHAVIOR"
    # held 期间确定性取消照常生效
    transition(opp, {"kind": "deterministic_cancel"})
    assert opp.state == "INVALIDATED"


def test_unknown_operational_expire_is_not_strategy_rejection():
    opp = mk_opp(state="TESTING", unknown_policy="operational_expire",
                 unknown_limit=1)
    apply_assessment(opp, {"r1": "unknown"}, revision=opp.revision)
    assert opp.state == "CANCELLED"
    assert opp.reason_code == "UNKNOWN_OPERATIONAL_EXPIRED"


def test_resume_review_requires_command():
    opp = mk_opp(state="WAITING_BEHAVIOR", unknown_policy="review_hold",
                 unknown_limit=1, review_status="held",
                 unknown_streak={"r1": 1})
    transition(opp, {"kind": "resume_review", "operator": "user",
                     "reason": "模型恢复"})
    assert opp.review_status == "" and opp.unknown_streak == {}


def test_new_evidence_wakes_without_leaving_band():
    # C18：等收回上沿，没离带、新根完成收回 → 唤醒，不强制二测
    c = Condition(id="r1", role="required", evaluator="deterministic",
                  recheck_mode="new_evidence", status="not_met")
    opp = Opportunity(opportunity_id="o", state="WAITING_BEHAVIOR",
                      conditions=[c])
    wake, reason = note_bar(opp, touches_band=True, fully_outside=False,
                            changed_conditions=("r1",))
    assert wake and reason == "new_evidence" and opp.test_sequence == 0


def test_leave_then_return_counts_tests_not_assessments():
    # C19：同次测试复核多次只涨 assessment；离开返回才涨 test_sequence
    c = Condition(id="r1", role="required", recheck_mode="leave_then_return",
                  status="not_met")
    opp = Opportunity(opportunity_id="o", state="TESTING", conditions=[c],
                      test_sequence=1)
    wake, _ = note_bar(opp, touches_band=True, fully_outside=False)
    assert not wake  # 还没离开过，带内连续触及不算新测试
    wake, reason = note_bar(opp, touches_band=False, fully_outside=True)
    assert not wake and reason == "armed" and opp.armed is True
    wake, reason = note_bar(opp, touches_band=True, fully_outside=False)
    assert wake and reason == "retest" and opp.test_sequence == 2


def test_budget_exhausted_defers_not_drops():
    c = Condition(id="r1", role="required", status="not_met")
    opp = Opportunity(opportunity_id="o", state="WAITING_BEHAVIOR",
                      conditions=[c])
    wake, reason = note_bar(opp, touches_band=True, fully_outside=False,
                            budget_available=False)
    assert not wake and reason == "deferred_budget" and opp.deferred is True


def test_store_roundtrip_and_single_writer(tmp_path):
    path = str(tmp_path / "opps.json")
    with FileOpportunityStore(path) as store:
        opp = mk_opp(state="WAITING_BEHAVIOR")
        store.upsert(opp)
        store.add_task({"request_key": "opp1:0:111:rejudge",
                        "type": "rejudge", "opportunity_id": "opp1",
                        "status": "pending"})
        _, created = store.add_task({"request_key": "opp1:0:111:rejudge",
                                     "type": "rejudge",
                                     "opportunity_id": "opp1",
                                     "status": "pending"})
        assert created is False  # 请求键唯一，重复登记不新增
        try:
            FileOpportunityStore(path).acquire()
            raise AssertionError("第二写者不应拿到锁")
        except StoreLocked:
            pass
    store2 = FileOpportunityStore(path)
    got = store2.get("opp1")
    assert got.state == "WAITING_BEHAVIOR" and got.conditions[0].id == "r1"
    assert len(store2.pending_tasks("rejudge")) == 1
