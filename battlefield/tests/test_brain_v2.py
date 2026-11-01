"""简报 v2 契约测试（2026-11-01）：role/phase/claims + conclusion/delta/handoff。

验收点：
- v2 输出可落账，结构化字段随假设存续，supersede 默认继承角色；
- claims/delta/handoff 的引用造假一律契约错误、不落盘；
- 角色唯一性：落盘后同角色 active 超过一条 = 契约错误；
- v1 输出（无 v2 字段）照常兼容。
"""
from decimal import Decimal

from battlefield.brain import BrainSession, RecordedAdapter
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


def repo6():
    kernel = Battlefield("TEST", "15m", TF_MS)
    repo = InMemoryRepository(kernel)
    kernel.register_level(make_level("P1", "100", "100", kind="manual",
                                     source="样板锚", available_at=0,
                                     confirmed_at=0, band=Decimal("0.5")))
    for i, row in enumerate(FIXTURE):
        repo.commit_bar(bar(i, *row))
    return kernel, repo


def v2_output(gid, cursor=7):
    return {
        "schema_version": "battlefield.brain-output/v2",
        "read_cursor": cursor, "action": "WAIT_BEHAVIOR",
        "conclusion": "多方防守占优，尚未形成上攻；最近支撑测试未决。",
        "hypothesis_ops": [
            {"op": "add", "role": "primary", "phase": "等待确认",
             "text": "价格在下方支撑结构内整理，最近缺口测试未决，下方防线未失守。",
             "support_refs": [gid], "counter_refs": [],
             "claims": [
                 {"claim": "最近防线尚未失守", "effect": "supports",
                  "weight": "core",
                  "fact": "最近向上缺口仍开放，测试进行中未触线关账",
                  "refs": [gid]},
                 {"claim": "测试未收官，守住未确认", "effect": "unresolved",
                  "weight": "core",
                  "fact": "第1次测试仍在进行", "refs": [gid]},
             ],
             "reason": "立论：最近防线未决、下方结构未失守"},
            {"op": "add", "role": "backup", "phase": "等待确认",
             "text": "若最近缺口触线关账，防守结构失效，空方接管节奏。",
             "support_refs": [gid], "counter_refs": [], "reason": "备推演"},
        ],
        "delta": {"kind": "new_branch",
                  "what_changed": "本轮新立主备一对",
                  "what_it_means": "战场进入以最近缺口测试定去留的阶段",
                  "effect_on_hypothesis": "新立", "refs": [gid]},
        "handoff": {"trigger": "最近向上缺口被触线并关账",
                    "trigger_refs": [gid],
                    "not_triggered_by": ["仅开始回补测试", "测试尚未收官"],
                    "status": "not_triggered"},
        "watch_plan": None,
        "candidate": None,
    }


def test_v2_output_applies_and_persists():
    kernel, repo = repo6()
    gid = list(kernel.gaps.values())[0].gap_id
    s = BrainSession(repo, RecordedAdapter([v2_output(gid)]))
    res = s.run_once()
    assert res["status"] == "ok", res
    main, backup = kernel.hypotheses
    assert main["role"] == "primary" and main["phase"] == "等待确认"
    assert main["claims"][0]["claim"] == "最近防线尚未失守"
    assert backup["role"] == "backup"
    assert res["output_summary"]["has_delta"] and res["output_summary"]["has_handoff"]


def test_v2_supersede_inherits_role_and_confirm_refreshes_phase():
    kernel, repo = repo6()
    gid = list(kernel.gaps.values())[0].gap_id
    s = BrainSession(repo, RecordedAdapter([v2_output(gid)]))
    assert s.run_once()["status"] == "ok"
    repo.commit_bar(bar(7, "102.8", 103, 99, "99.5"))
    out2 = {
        "schema_version": "battlefield.brain-output/v2",
        "read_cursor": 8, "action": "WAIT_BEHAVIOR",
        "hypothesis_ops": [
            {"op": "supersede", "hyp_id": "H1",
             "text": "缺口关账后结构翻面，改以回补完成后的新剧本推演。",
             "support_refs": [gid], "counter_refs": [], "reason": "触线关账，演化"},
            {"op": "confirm", "hyp_id": "H2", "phase": "接近失效",
             "reason": "备推演的前提正在逼近"},
        ],
        "delta": {"kind": "invalidated", "what_changed": "最近缺口触线关账",
                  "what_it_means": "原主推演失效", "effect_on_hypothesis": "失效",
                  "refs": [gid]},
        "handoff": {"trigger": "最近向上缺口被触线并关账",
                    "trigger_refs": [gid], "status": "triggered"},
    }
    s.adapter = RecordedAdapter([out2])
    res = s.run_once()
    assert res["status"] == "ok", res
    new_main = kernel.hypotheses[-1]
    assert new_main["role"] == "primary"          # 接管继承角色
    assert kernel.hypotheses[0]["status"] == "superseded"
    assert kernel.hypotheses[1]["phase"] == "接近失效"  # confirm 刷新阶段


def test_v2_bad_claim_ref_rejected():
    kernel, repo = repo6()
    gid = list(kernel.gaps.values())[0].gap_id
    out = v2_output(gid)
    out["hypothesis_ops"][0]["claims"][0]["refs"] = ["GAP-NOPE-1"]
    s = BrainSession(repo, RecordedAdapter([out]))
    assert s.run_once()["status"] == "contract_error"
    assert kernel.hypotheses == []


def test_v2_role_conflict_rejected():
    kernel, repo = repo6()
    gid = list(kernel.gaps.values())[0].gap_id
    out = v2_output(gid)
    out["hypothesis_ops"][1]["role"] = "primary"   # 两个主推演
    s = BrainSession(repo, RecordedAdapter([out]))
    assert s.run_once()["status"] == "contract_error"
    assert kernel.hypotheses == []


def test_v2_bad_delta_kind_and_handoff_without_refs_rejected():
    kernel, repo = repo6()
    gid = list(kernel.gaps.values())[0].gap_id
    out = v2_output(gid)
    out["delta"]["kind"] = "有点变强"
    s = BrainSession(repo, RecordedAdapter([out]))
    assert s.run_once()["status"] == "contract_error"

    kernel, repo = repo6()
    gid = list(kernel.gaps.values())[0].gap_id
    out = v2_output(gid)
    out["handoff"]["trigger_refs"] = []
    s = BrainSession(repo, RecordedAdapter([out]))
    assert s.run_once()["status"] == "contract_error"
    assert kernel.hypotheses == []


def test_retire_deactivates_without_creating():
    # 假设卫生：存量多余 active 用 retire 销账——只退役、不新建，
    # 退役后同标的只剩主备一对；退役不存在的假设 = 契约错误
    kernel, repo = repo6()
    gid = list(kernel.gaps.values())[0].gap_id
    s = BrainSession(repo, RecordedAdapter([v2_output(gid)]))
    assert s.run_once()["status"] == "ok"
    repo.commit_bar(bar(7, "102.8", 103, 101, "101.5"))
    out2 = {
        "schema_version": "battlefield.brain-output/v2",
        "read_cursor": 8, "action": "WAIT_BEHAVIOR",
        "hypothesis_ops": [
            {"op": "add", "text": "历史遗留的第三条推演",
             "support_refs": [gid], "counter_refs": [], "reason": "模拟存量"},
        ],
    }
    s.adapter = RecordedAdapter([out2])
    assert s.run_once()["status"] == "ok"
    assert len(kernel.hypotheses) == 3
    repo.commit_bar(bar(8, "101.5", 102, 100, "100.5"))
    out3 = {
        "schema_version": "battlefield.brain-output/v2",
        "read_cursor": 9, "action": "WAIT_BEHAVIOR",
        "hypothesis_ops": [
            {"op": "retire", "hyp_id": "H3", "reason": "存量清理：只留主备一对"},
        ],
    }
    s.adapter = RecordedAdapter([out3])
    res = s.run_once()
    assert res["status"] == "ok", res
    assert len(kernel.hypotheses) == 3                      # 没新建
    assert kernel.hypotheses[2]["status"] == "superseded"   # 只销账
    assert kernel.hypotheses[2]["history"][-1]["op"] == "retired"
    repo.commit_bar(bar(9, "100.5", 101, 99, "99.5"))
    out4 = {
        "schema_version": "battlefield.brain-output/v2",
        "read_cursor": 10, "action": "WAIT_BEHAVIOR",
        "hypothesis_ops": [{"op": "retire", "hyp_id": "H99", "reason": "无此假设"}],
    }
    s.adapter = RecordedAdapter([out4])
    assert s.run_once()["status"] == "contract_error"


def test_v1_legacy_roles_replay_compatible():
    # 账本重放兼容：存量 v1 输出用过 role 旧写法 main/alt，且墓碑清理批
    # 同批多条同角色 supersede——写入时都合法，重放不许追溯拒收；
    # role 规范化为 primary/backup 后落账
    kernel, repo = repo6()
    gid = list(kernel.gaps.values())[0].gap_id
    out = {
        "schema_version": "battlefield.brain-output/v1",
        "read_cursor": 7, "action": "WAIT_BEHAVIOR",
        "hypothesis_ops": [
            {"op": "add", "role": "main", "text": "旧写法主推演",
             "support_refs": [gid], "counter_refs": [], "reason": "v1"},
            {"op": "add", "role": "alt", "text": "旧写法备推演",
             "support_refs": [gid], "counter_refs": [], "reason": "v1"},
            {"op": "supersede", "hyp_id": "H1", "role": "main",
             "text": "清理说明式文本", "support_refs": [gid],
             "counter_refs": [], "reason": "墓碑批"},
            {"op": "supersede", "hyp_id": "H2", "role": "alt",
             "text": "清理说明式文本二", "support_refs": [gid],
             "counter_refs": [], "reason": "墓碑批"},
        ],
    }
    s = BrainSession(repo, RecordedAdapter([out]))
    res = s.run_once()
    assert res["status"] == "ok", res
    roles = [h.get("role") for h in kernel.hypotheses]
    assert roles == ["primary", "backup", "primary", "backup"], roles


def test_v1_output_still_applies():
    kernel, repo = repo6()
    gid = list(kernel.gaps.values())[0].gap_id
    s = BrainSession(repo, RecordedAdapter([
        {"read_cursor": 7, "action": "WATCH",
         "hypothesis_ops": [{"op": "add", "text": "旧版式假设",
                             "support_refs": [gid], "counter_refs": [],
                             "reason": "v1"}]},
    ]))
    assert s.run_once()["status"] == "ok"
    assert "role" not in kernel.hypotheses[0]
