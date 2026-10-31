"""事件器验收测试（design/事件器设计-v1.md §11，夹具带 [100,102]）。

E12（new_evidence 唤醒）与 E13（预算延后）、E14（位置资格）是机会/
调度/gate 层行为，不在本模块验收范围，归 P1 机会状态机。
"""

from runtime.events import (
    AttemptTracker, WatchLevel, advance_attempt, detect_price_events)

LV = WatchLevel(level_id="L1", level_version=1, kind="resistance",
                lo=100.0, hi=102.0, watch_lo=100.0, watch_hi=102.0)


def B(t, o, h, l, c):
    return {"t": t, "o": o, "h": h, "l": l, "c": c}


def types(events):
    return [e.type for e in events]


def run(tracker, prev, cur, level=LV):
    evs = detect_price_events(prev, cur, level, tracker)
    advance_attempt(tracker, evs, bar=cur, level=level)
    return evs


PREV_IN = B(0, 101, 101.5, 100.5, 101)  # 前收盘 101，带内


def test_e01_upside_attempt_close_outside():
    tr = AttemptTracker()
    evs = run(tr, PREV_IN, B(1, 101, 104, 101, 103))
    assert "UPSIDE_ATTEMPT_STARTED" in types(evs)
    assert "CLOSE_OUTSIDE_UP" in types(evs)
    att = tr.active("up")
    assert att is not None and att.state == "OUTSIDE_TRACKING"


def test_e02_same_bar_reclaim_order_unknown():
    tr = AttemptTracker()
    evs = run(tr, PREV_IN, B(1, 101, 103, 100.5, 101.5))
    assert "UPSIDE_ATTEMPT_STARTED" in types(evs)
    assert "UPSIDE_RECLAIMED" in types(evs)
    assert all(e.intrabar_order_unknown for e in evs
               if e.type in ("UPSIDE_ATTEMPT_STARTED", "UPSIDE_RECLAIMED"))
    assert tr.active("up") is None  # 已 RECLAIMED 终结


def test_e03_continuous_outside_same_attempt_separated():
    tr = AttemptTracker()
    run(tr, PREV_IN, B(1, 101, 104, 101, 103))
    att1 = tr.active("up")
    evs = run(tr, B(1, 101, 104, 101, 103), B(2, 103, 105, 102.5, 104))
    assert "UPSIDE_ATTEMPT_STARTED" not in types(evs)
    assert "OUTSIDE_SEPARATED_UP" in types(evs)
    assert tr.active("up").attempt_id == att1.attempt_id
    assert tr.active("up").away is True


def _to_separated(tr):
    run(tr, PREV_IN, B(1, 101, 104, 101, 103))
    run(tr, B(1, 101, 104, 101, 103), B(2, 103, 105, 102.5, 104))


def test_e04_retest_started():
    tr = AttemptTracker()
    _to_separated(tr)
    evs = run(tr, B(2, 103, 105, 102.5, 104), B(3, 104, 104, 101.8, 102.5))
    assert "RETEST_STARTED" in types(evs)
    assert tr.active("up").state == "RETESTING"
    assert tr.active("up").retest_sequence == 1


def test_e05_retest_and_reclaim_same_bar():
    tr = AttemptTracker()
    _to_separated(tr)
    evs = run(tr, B(2, 103, 105, 102.5, 104), B(3, 104, 104, 100.5, 101))
    assert "RETEST_STARTED" in types(evs) and "UPSIDE_RECLAIMED" in types(evs)
    assert tr.active("up") is None


def test_e06_second_attempt_links_previous():
    tr = AttemptTracker()
    run(tr, PREV_IN, B(1, 101, 103, 100.5, 101.5))  # 开始并收回
    first = tr.last_up_attempt_id
    evs = run(tr, B(1, 101, 103, 100.5, 101.5), B(2, 101, 103, 101, 102.5))
    assert "UPSIDE_ATTEMPT_STARTED" in types(evs)
    att = tr.active("up")
    assert att.attempt_id != first and att.previous_attempt_id == first


def test_e07_touch_only_no_attempt():
    tr = AttemptTracker()
    evs = run(tr, PREV_IN, B(1, 101, 102, 100, 101))  # high 恰等于上沿
    assert types(evs) == ["ZONE_TOUCHED"]
    assert tr.active("up") is None


def test_e08_dual_sided_no_order_claim():
    tr = AttemptTracker()
    evs = run(tr, PREV_IN, B(1, 101, 103, 99, 101))
    assert "UPSIDE_ATTEMPT_STARTED" in types(evs)
    assert "DOWNSIDE_ATTEMPT_STARTED" in types(evs)
    assert all(e.intrabar_order_unknown for e in evs
               if e.type.endswith("ATTEMPT_STARTED"))


def test_e09_cold_start_outside_no_backfill():
    tr = AttemptTracker()
    prev = B(0, 104, 104.5, 103.5, 104)  # 已在位外
    evs = run(tr, prev, B(1, 104, 105, 103.8, 104.5))
    assert "UPSIDE_ATTEMPT_STARTED" not in types(evs)
    assert tr.active("up") is None


def test_e10_duplicate_delivery_idempotent():
    tr = AttemptTracker()
    evs = detect_price_events(PREV_IN, B(1, 101, 104, 101, 103), LV, tr)
    t1 = advance_attempt(tr, evs, bar=B(1, 101, 104, 101, 103), level=LV)
    t2 = advance_attempt(tr, evs, bar=B(1, 101, 104, 101, 103), level=LV)
    assert t1 and t2 == []
    assert tr.active("up").retest_sequence == 0


def test_e11_continuous_retest_no_sequence_inflation():
    tr = AttemptTracker()
    _to_separated(tr)
    run(tr, B(2, 103, 105, 102.5, 104), B(3, 104, 104, 101.8, 102.5))
    # 仍在带边连续触及：不递增
    run(tr, B(3, 104, 104, 101.8, 102.5), B(4, 102.5, 103, 101.5, 102.8))
    assert tr.active("up").retest_sequence == 1
    # 整根重新离开 → 回 OUTSIDE_TRACKING；再返回才算第二次
    run(tr, B(4, 102.5, 103, 101.5, 102.8), B(5, 103, 104, 102.6, 103.5))
    assert tr.active("up").state == "OUTSIDE_TRACKING"
    evs = run(tr, B(5, 103, 104, 102.6, 103.5), B(6, 103, 103.5, 101.9, 102.6))
    assert "RETEST_STARTED" in types(evs)
    assert tr.active("up").retest_sequence == 2


def test_downside_mirror_attempt_and_reclaim():
    tr = AttemptTracker()
    evs = run(tr, PREV_IN, B(1, 101, 101.5, 98, 99))  # 下破收外
    assert "DOWNSIDE_ATTEMPT_STARTED" in types(evs)
    assert "CLOSE_OUTSIDE_DOWN" in types(evs)
    evs = run(tr, B(1, 101, 101.5, 98, 99), B(2, 99, 100.5, 98.5, 100.5))
    assert "DOWNSIDE_RECLAIMED" in types(evs)  # 收盘回到下沿上方
    assert tr.active("down") is None


def test_downside_separated_and_retest():
    tr = AttemptTracker()
    run(tr, PREV_IN, B(1, 101, 101.5, 98, 99))
    evs = run(tr, B(1, 101, 101.5, 98, 99), B(2, 98, 99.5, 96, 97))
    assert "OUTSIDE_SEPARATED_DOWN" in types(evs)  # 整根 high < 100
    evs = run(tr, B(2, 98, 99.5, 96, 97), B(3, 97, 100.2, 96.5, 99.5))
    assert "RETEST_STARTED" in types(evs)
    assert tr.active("down").retest_sequence == 1


def test_boundary_equality_is_not_outside():
    tr = AttemptTracker()
    evs = run(tr, PREV_IN, B(1, 101, 102.0, 100.5, 102.0))  # 收盘恰等于上沿
    assert "UPSIDE_ATTEMPT_STARTED" not in types(evs)
    assert "CLOSE_OUTSIDE_UP" not in types(evs)


def test_no_previous_bar_no_crossing_events():
    tr = AttemptTracker()
    evs = detect_price_events(None, B(1, 101, 104, 101, 103), LV, tr)
    assert evs == ()


def test_watch_band_wider_than_level_for_retest():
    lv = WatchLevel(level_id="L2", level_version=1, kind="resistance",
                    lo=100.0, hi=102.0, watch_lo=99.0, watch_hi=103.0)
    tr = AttemptTracker()
    run(tr, PREV_IN, B(1, 101, 104, 101, 103), level=lv)
    # 整根在观察带内（low 102.5 <= 103）→ 还没分离
    evs = run(tr, B(1, 101, 104, 101, 103), B(2, 103, 105, 102.5, 104), level=lv)
    assert "OUTSIDE_SEPARATED_UP" not in types(evs)
    evs = run(tr, B(2, 103, 105, 102.5, 104), B(3, 104, 106, 103.5, 105), level=lv)
    assert "OUTSIDE_SEPARATED_UP" in types(evs)
