"""战场翻译器验收测试。

核心夹具 = 方案 §11 最小完整翻译样例（P1=100，观察带 [99.5,100.5]）：
主轨迹 b1..b6 与分支夹具（b5 改 low=99.8 触锚关账）共享前缀，
b4 之前两条剧情的状态投影必须逐字相同（前缀不变性）。
"""
from decimal import Decimal

import pytest

from battlefield.contracts import make_bar
from battlefield.facts import compute_facts
from battlefield.queries import (QueryService, make_token, propose_hypothesis,
                                 propose_watch_plan)
from battlefield.reducers import Battlefield, TEST_REJECTION_PROXY
from battlefield.repository import InMemoryRepository, replay
from battlefield.terrain import make_level, make_target

TF_MS = 900_000  # 15m


def bar(i, o, h, l, c):
    return make_bar("TEST", "15m", i * TF_MS, (i + 1) * TF_MS, o, h, l, c,
                    received_at=(i + 1) * TF_MS)


def level_p1():
    return make_level("P1", "100", "100", kind="manual", source="样板锚 §11",
                      available_at=0, confirmed_at=0, band=Decimal("0.5"))


def fresh_repo():
    kernel = Battlefield("TEST", "15m", TF_MS)
    repo = InMemoryRepository(kernel)
    kernel.register_level(level_p1())
    return kernel, repo


FIXTURE = [
    (99, "99.4", "98.6", 99),            # b0 先前 close=99
    (99, 102, "98.8", "101.5"),         # b1 上破尝试，收外；触锚；缺口未建立
    ("101.5", 103, 101, "102.5"),       # b2 整根在锚上方 -> 缺口建立
    ("102.5", "102.8", "100.2", "100.4"),  # b3 首次进带，未触锚 -> T1 开始
    ("100.8", "102.5", "100.7", "102.2"),  # b4 整根离开带 -> T1 拒绝（代理确认）
    ("102.2", "102.4", "100.3", "100.4"),  # b5 返回带 -> T2 开始
    ("100.8", 103, "100.7", "102.8"),   # b6 再次整根离开 -> T2 拒绝（代理确认）
]


def run_fixture(repo, bars=FIXTURE):
    per_bar = []
    for i, (o, h, l, c) in enumerate(bars):
        res = repo.commit_bar(bar(i, o, h, l, c))
        assert res["status"] == "applied"
        per_bar.append([e.type for e in res["events"]])
    return per_bar


def test_fixture_main_trajectory():
    kernel, repo = fresh_repo()
    per_bar = run_fixture(repo)
    assert "ATTEMPT_STARTED" in per_bar[1]
    assert "GAP_OPENED" not in per_bar[1]          # b1 缺口尚未建立
    assert "GAP_OPENED" in per_bar[2]              # b2 整根分离立账
    assert "TEST_STARTED" in per_bar[3]            # b3 T1
    assert "TEST_ENDED" in per_bar[4]              # b4 T1 结束
    assert "TEST_STARTED" in per_bar[5]            # b5 T2
    assert "TEST_ENDED" in per_bar[6]              # b6 T2 结束
    gap = list(kernel.gaps.values())[0]
    assert gap.status == "open"
    assert gap.test_count == 2                     # 两次调用/两根不算，必须完整往返才计数
    assert [t["outcome"] for t in gap.tests] == ["rejected_proxy", "rejected_proxy"]
    assert all(t["proxy"] == TEST_REJECTION_PROXY for t in gap.tests)


def test_fixture_both_sides_bar_flagged_unknown():
    kernel, repo = fresh_repo()
    repo.commit_bar(bar(0, *FIXTURE[0]))
    res = repo.commit_bar(bar(1, *FIXTURE[1]))
    att = [e for e in res["events"] if e.type == "ATTEMPT_STARTED"][0]
    assert att.payload.get("intrabar_order_unknown") is True


def test_fixture_branch_gap_closed_no_second_test():
    kernel, repo = fresh_repo()
    branch = list(FIXTURE)
    branch[5] = ("102.2", "102.4", "99.8", "100.4")   # b5' low 触锚
    per_bar = run_fixture(repo, branch)
    assert "GAP_CLOSED" in per_bar[5]
    assert "TEST_STARTED" not in per_bar[5]            # 先记已补，不再记二测
    gap = list(kernel.gaps.values())[0]
    assert gap.status == "closed"
    assert gap.test_count == 1                         # 只有 T1


def test_prefix_invariance():
    _, repo_a = fresh_repo()
    run_fixture(repo_a)
    branch = list(FIXTURE)
    branch[5] = ("102.2", "102.4", "99.8", "100.4")
    _, repo_b = fresh_repo()
    run_fixture(repo_b, branch)
    rev_b4 = 5  # b0..b4 共 5 根
    assert repo_a.projection_hash(rev_b4) == repo_b.projection_hash(rev_b4)


def test_mirror_down_gap_and_test():
    kernel = Battlefield("TEST", "15m", TF_MS)
    repo = InMemoryRepository(kernel)
    kernel.register_level(level_p1())
    seq = [
        (101, "101.4", "100.6", 101),              # 先前 close=101
        (101, "101.2", 98, "98.5"),                # 向下尝试，收外
        ("98.5", 99, 97, "97.5"),                  # 整根在锚下方 -> 向下缺口
        ("97.5", "99.8", "97.2", "99.6"),          # 返回带内，未触锚 -> T1
        ("99.2", "99.3", "97.5", "97.8"),          # 整根离开带（下方）-> 拒绝（代理）
    ]
    per_bar = []
    for i, (o, h, l, c) in enumerate(seq):
        res = repo.commit_bar(bar(i, o, h, l, c))
        per_bar.append([e.type for e in res["events"]])
    assert "GAP_OPENED" in per_bar[2]
    gap = list(kernel.gaps.values())[0]
    assert gap.direction == "down"
    assert "TEST_STARTED" in per_bar[3]
    assert "TEST_ENDED" in per_bar[4]
    assert gap.test_count == 1


def test_duplicate_idempotent_and_revision_conflict():
    kernel, repo = fresh_repo()
    repo.commit_bar(bar(0, *FIXTURE[0]))
    h1 = repo.projection_hash()
    dup = repo.commit_bar(bar(0, *FIXTURE[0]))
    assert dup["status"] == "duplicate_ignored"
    assert repo.projection_hash() == h1 and kernel.revision == 1
    conflict = repo.commit_bar(bar(0, 99, "99.4", "98.6", "98.9"))
    assert conflict["status"] == "revision_conflict"
    # 冲突 bar 被隔离：行情投影（位置/缺口/段）与 revision 不动，仅 data_health 记账
    st = kernel.state_dict()
    assert kernel.revision == 1
    assert st["levels"] == repo.state_at_revision(1)["levels"]
    assert st["gaps"] == [] and st["segments"] == []
    assert st["data_health"]["revision_conflicts"] == 1
    assert len(repo.quarantine) == 1


def test_late_bar_rejected_and_missing_bars_flagged():
    kernel, repo = fresh_repo()
    repo.commit_bar(bar(0, *FIXTURE[0]))
    repo.commit_bar(bar(1, *FIXTURE[1]))
    late = make_bar("TEST", "15m", TF_MS // 2, TF_MS // 2 + TF_MS, 99, 100, 98, 99,
                    received_at=3 * TF_MS)
    assert repo.commit_bar(late)["status"] == "late_rejected"
    # 跳过 b2 直接喂 b3（open_time 多一段）-> 缺根登记，不跨缺口认定
    res = repo.commit_bar(bar(3, *FIXTURE[3]))
    assert "DATA_GAP" in [e.type for e in res["events"]]
    assert kernel.data_health["missing_bars"] == 1
    assert kernel.data_health["continuity_broken"] is True


def test_facts_zero_range_and_warmup():
    b0 = bar(0, 100, 100, 100, 100)
    f0 = compute_facts([], b0)
    assert f0.body_ratio is None and f0.close_location is None and f0.warmup is True
    b1 = bar(1, 100, 101, 99, "100.5")
    f1 = compute_facts([b0], b1)
    assert f1.scale == 0                    # 此前只有零振幅
    assert f1.rel(f1.range) is None         # 尺度为零不填数伪装


def test_swing_confirmation_time_not_backdated():
    kernel = Battlefield("TEST", "15m", TF_MS, enable_swings=True)
    repo = InMemoryRepository(kernel)
    highs = [10, 12, 15, 13, 12]
    lows = [9, "9.5", 10, "10.5", 11]
    for i in range(5):
        repo.commit_bar(bar(i, lows[i], highs[i], lows[i], highs[i]))
        swings = [lv for lv in kernel.levels.values() if lv.level.kind == "swing"]
        if i < 4:
            assert swings == []             # 极值在 i=2，但右侧未满不得提前出现
        else:
            assert len(swings) == 1
            lv = swings[0].level
            assert lv.anchor == Decimal(15)
            assert lv.confirmed_at == 5 * TF_MS   # 第 5 根 close_time，不是极值根


def test_replay_determinism():
    bars = [bar(i, *row) for i, row in enumerate(FIXTURE)]
    r1 = replay("TEST", "15m", TF_MS, bars, levels=[level_p1()])
    r2 = replay("TEST", "15m", TF_MS, bars, levels=[level_p1()])
    assert r1.projection_hash() == r2.projection_hash()


def test_attempt_segment_result_vector():
    kernel, repo = fresh_repo()
    run_fixture(repo)
    seg = [s for s in kernel.segments.values() if s.level_key][0]
    res = seg.result(kernel.bars_by_id)
    assert res["sufficient"] is True
    assert res["p0"] == Decimal(99)
    assert res["net_progress"] == Decimal("3.8")
    assert res["favorable_excursion"] == Decimal(4)
    assert res["giveback"] == Decimal("0.2")
    assert res["giveback_ratio"] == Decimal("0.05")


def test_target_touched_only_when_registered_before():
    kernel, repo = fresh_repo()
    kernel.register_target(make_target("TGT-1", "102.5", formula="样板目标",
                                       anchor_refs=("P1@v1",), created_at=0, available_at=0))
    per_bar = run_fixture(repo)
    assert "TARGET_TOUCHED" in per_bar[2]


def test_query_binding_and_conditions():
    kernel, repo = fresh_repo()
    run_fixture(repo)
    qs = QueryService(repo, make_token(repo))
    scene = qs.get_scene()
    assert len(scene["open_gaps"]) == 1
    gap_id = scene["open_gaps"][0]["gap_id"]
    chk = qs.check_conditions({"plan_id": "w1", "conditions": [
        {"type": "gap_open", "gap_id": gap_id},
        {"type": "test_count_at_least", "level_id": "P1", "count": 2},
        {"type": "gap_closed", "gap_id": gap_id},
    ]})
    assert len(chk["satisfied"]) == 2 and len(chk["missing"]) == 1
    ev = qs.inspect_evidence(gap_id)
    assert ev["object"]["gap_id"] == gap_id and ev["bars"]
    with pytest.raises(ValueError):
        QueryService(repo, "TEST|15m|r999|0")


def test_snapshot_bound_reads():
    kernel, repo = fresh_repo()
    for i in range(4):
        repo.commit_bar(bar(i, *FIXTURE[i]))
    qs = QueryService(repo, make_token(repo))       # 绑定 b3 时点
    for i in range(4, 7):                           # 内核继续推进到 b6
        repo.commit_bar(bar(i, *FIXTURE[i]))
    bars = qs.read_bars()
    assert len(bars) == 4                           # 快照之后的数据不可见


def test_proposals_validated_and_fact_partition():
    kernel, repo = fresh_repo()
    run_fixture(repo)
    gap_id = list(kernel.gaps.values())[0].gap_id
    entry = propose_hypothesis(repo, {"text": "缺口守住", "support_refs": [gap_id],
                                      "counter_refs": []})
    assert entry["status"] == "proposed"
    with pytest.raises(ValueError):
        propose_hypothesis(repo, {"text": "无据", "support_refs": ["NOPE-1"]})
    with pytest.raises(ValueError):
        propose_watch_plan(repo, {"watch_level": "P1@v1", "watch_behavior": "返回带内"})
    plan = propose_watch_plan(repo, {"watch_level": "P1@v1", "watch_behavior": "返回带内被拒",
                                     "entry_trigger": "T2 结束后触发根", "cancel_if": "触锚关账"})
    assert plan["status"] == "proposed"
    assert kernel.state_dict()["levels"]  # 事实分区未被提案污染（levels 仍可投影）


def test_contest_forms_after_both_directions():
    kernel = Battlefield("TEST", "15m", TF_MS)
    repo = InMemoryRepository(kernel)
    kernel.register_level(level_p1())
    closes = [99, 101, 99, 100, 98]
    prev = 99
    for i, c in enumerate(closes):
        o = prev
        repo.commit_bar(bar(i, o, max(o, c) + Decimal("0.4"), min(o, c) - Decimal("0.4"), c))
        prev = c
    scene = kernel.state_dict()
    assert scene["contests"] and scene["contests"][0]["level_key"] == "P1@v1"
