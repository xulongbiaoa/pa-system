"""W06 单一大脑判读层测试：录制/可调用模型，不接真实模型。

验收点（方案 §10 + 大脑定案）：
- 一个任务同时拿到全局 scene 与局部 changes；
- 假设集中维护（add/confirm/challenge/supersede）且带修订历史；
- read_cursor 不符 = 过期，引用造假 = 契约错误，两者都不落盘、cursor 不推进；
- 模型不可用是系统结果，不记成策略无机会；
- 候选只进提案分区，事实投影（位置/缺口）纹丝不动。
"""
from decimal import Decimal

import pytest

from battlefield.brain import (BrainSession, CallableAdapter, ModelUnavailable,
                               RecordedAdapter)
from battlefield.contracts import make_bar
from battlefield.reducers import Battlefield
from battlefield.repository import InMemoryRepository
from battlefield.terrain import make_level

TF_MS = 900_000

FIXTURE = [
    (99, "99.4", "98.6", 99),
    (99, 102, "98.8", "101.5"),
    ("101.5", 103, 101, "102.5"),
    ("102.5", "102.8", "100.2", "100.4"),
    ("100.8", "102.5", "100.7", "102.2"),
    ("102.2", "102.4", "100.3", "100.4"),
    ("100.8", 103, "100.7", "102.8"),
]


def bar(i, o, h, l, c):
    return make_bar("TEST", "15m", i * TF_MS, (i + 1) * TF_MS, o, h, l, c,
                    received_at=(i + 1) * TF_MS)


def repo_at_b6():
    kernel = Battlefield("TEST", "15m", TF_MS)
    repo = InMemoryRepository(kernel)
    kernel.register_level(make_level("P1", "100", "100", kind="manual", source="样板锚",
                                     available_at=0, confirmed_at=0, band=Decimal("0.5")))
    for i, row in enumerate(FIXTURE):
        repo.commit_bar(bar(i, *row))
    return kernel, repo


def gap_id_of(kernel):
    return list(kernel.gaps.values())[0].gap_id


def test_package_has_global_and_local():
    kernel, repo = repo_at_b6()
    seen = {}

    def fn(pkg):
        seen.update(pkg)
        return {"read_cursor": pkg["snapshot_revision"], "action": "WATCH"}

    s = BrainSession(repo, CallableAdapter(fn))
    res = s.run_once()
    assert res["status"] == "ok"
    assert seen["scene"]["open_gaps"]                 # 全局：开放缺口在场
    assert seen["changes"]["events"]                  # 局部：自 cursor 0 以来的事件
    assert seen["snapshot_revision"] == 7
    assert s.read_revision == 7


def test_hypothesis_lifecycle_central():
    kernel, repo = repo_at_b6()
    gid = gap_id_of(kernel)
    s = BrainSession(repo, RecordedAdapter([
        {"read_cursor": 7, "action": "WATCH",
         "hypothesis_ops": [{"op": "add", "text": "向上缺口守住，趋势延续",
                             "support_refs": [gid], "counter_refs": [],
                             "reason": "两测被拒"}]},
    ]))
    assert s.run_once()["status"] == "ok"
    hyp = kernel.hypotheses[0]
    assert hyp["hyp_id"] == "H1" and hyp["status"] == "active"
    # 新根：触锚关账 + 收回
    repo.commit_bar(bar(7, "102.8", 103, 99, "99.5"))
    s.adapter = RecordedAdapter([
        {"read_cursor": 8, "action": "WATCH",
         "hypothesis_ops": [{"op": "challenge", "hyp_id": "H1",
                             "reason": "缺口关账且收回"}]},
    ])
    assert s.run_once()["status"] == "ok"
    assert hyp["status"] == "challenged"
    assert [h["op"] for h in hyp["history"]] == ["add", "challenge"]


def test_stale_and_contract_error_write_nothing():
    kernel, repo = repo_at_b6()
    s = BrainSession(repo, RecordedAdapter([
        {"read_cursor": 999, "action": "WATCH"},                       # 过期
        {"read_cursor": 7, "action": "WATCH",
         "hypothesis_ops": [{"op": "add", "text": "伪造引用",
                             "support_refs": ["GAP-NOPE-9"]}]},        # 引用造假
        {"read_cursor": 7, "action": "FLY"},                           # 动作越界
    ]))
    assert s.run_once()["status"] == "stale"
    assert s.run_once()["status"] == "contract_error"
    assert s.run_once()["status"] == "contract_error"
    assert kernel.hypotheses == [] and s.read_revision == 0


def test_model_unavailable_is_system_result():
    kernel, repo = repo_at_b6()

    def boom(pkg):
        raise ModelUnavailable("timeout")

    s = BrainSession(repo, CallableAdapter(boom))
    res = s.run_once()
    assert res["status"] == "model_unavailable"
    assert s.read_revision == 0 and kernel.hypotheses == []


def test_candidate_goes_to_proposals_not_facts():
    kernel, repo = repo_at_b6()
    gid = gap_id_of(kernel)
    before = kernel.state_dict()
    s = BrainSession(repo, RecordedAdapter([
        {"read_cursor": 7, "action": "PROPOSE_CANDIDATE",
         "candidate": {"setup": "G1", "refs": [gid], "reason": "二测被拒"}},
    ]))
    assert s.run_once()["status"] == "ok"
    after = kernel.state_dict()
    assert len(after["candidate_proposals"]) == 1
    assert after["levels"] == before["levels"] and after["gaps"] == before["gaps"]


def test_supersede_keeps_history():
    kernel, repo = repo_at_b6()
    gid = gap_id_of(kernel)
    s = BrainSession(repo, RecordedAdapter([
        {"read_cursor": 7, "action": "WATCH",
         "hypothesis_ops": [
             {"op": "add", "text": "趋势延续", "support_refs": [gid]},
             {"op": "supersede", "hyp_id": "H1", "text": "区间争夺",
              "support_refs": [gid], "reason": "双向事件出现"}]},
    ]))
    assert s.run_once()["status"] == "ok"
    h1, h2 = kernel.hypotheses
    assert h1["status"] == "superseded" and h2["status"] == "active"
    assert h2["supersedes"] == "H1"


def test_test_label_out_of_range_rejected():
    """简报里的测试编号必须由事件生成：点名缺口后写越界 T 编号 = 契约错误。"""
    kernel, repo = repo_at_b6()
    gid = gap_id_of(kernel)
    cnt = list(kernel.gaps.values())[0].test_count
    bad = {"read_cursor": 7, "action": "WAIT_BEHAVIOR",
           "hypothesis_ops": [{"op": "add", "text": f"{gid} 已完成 T{cnt + 2} 测试",
                               "support_refs": [gid], "counter_refs": [], "reason": "x"}],
           "watch_plan": None, "candidate": None}
    s = BrainSession(repo, RecordedAdapter([bad]))
    res = s.run_once()
    assert res["status"] == "contract_error" and "测试编号越界" in res["detail"]
    assert not kernel.hypotheses  # 不落盘


def test_test_label_current_and_next_allowed():
    """已测编号与预告下一次（test_count+1，含中文「第N次」）合法。"""
    kernel, repo = repo_at_b6()
    gid = gap_id_of(kernel)
    cnt = list(kernel.gaps.values())[0].test_count
    cn = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}.get(cnt + 1, "三")
    ok = {"read_cursor": 7, "action": "WAIT_BEHAVIOR",
          "hypothesis_ops": [{"op": "add",
                              "text": f"{gid} 已测至 T{cnt}，等第{cn}次回补测试",
                              "support_refs": [gid], "counter_refs": [], "reason": "x"}],
          "watch_plan": None, "candidate": None}
    s = BrainSession(repo, RecordedAdapter([ok]))
    res = s.run_once()
    assert res["status"] == "ok", res
