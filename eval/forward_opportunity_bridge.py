#!/usr/bin/env python3
"""waits → Opportunity 桥（设计 v2.2 §6.1 的 due→重判闭环）。

现状缺口：forward_waits.scan 只把 waits 标 due 就终结，无人消费。
本桥把 due 变成持久重判任务，并把重判结果落回同一机会：

- dispatch：每个 due 的 wait 生成/更新一个 Opportunity（冻结条件集
  来自 wait.frozen_missing，一字不改），并登记 request_key 唯一的
  rejudge 任务（opportunity_id:revision:due_t:rejudge）。幂等。
- apply：消费任务。still_missing → 同一机会回 WAITING_BEHAVIOR
  续等（assessment_count +1、test_sequence 不动），wait 重新 open
  等下一次离开-返回；invalidated → 机会 INVALIDATED、wait 关闭；
  ready → 机会 READY（后续 gate/执行不在本桥）。

迁移口径（§6.1）：存量 waits 的取消仍走 scan 的 proxy 口径
（收盘越带 1×段均幅 ×2 根 / 300 根 expired）；重判模式按 basis
分：branch 出处 = leave_then_return（与 scan 两段式同义），其余
= new_evidence。机会的 unknown_policy 留空——存量等待的运营终结
由 scan 的 expired 承担，不另设。

用法（由批量轮操作者显式运行，不挂自动流程）：
  python3 eval/forward_opportunity_bridge.py dispatch
  python3 eval/forward_opportunity_bridge.py apply <wait_id> <still_missing|ready|invalidated>
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forward_waits as fw  # noqa: E402
from runtime.opportunities import (  # noqa: E402
    Condition, Opportunity, apply_assessment, transition)
from runtime.opportunity_store import FileOpportunityStore  # noqa: E402

FWD = fw.FWD
OPP_PATH = os.path.join(FWD, "opportunities.json")


def opportunity_from_wait(wait):
    """冻结条件集 → Opportunity。missing 原文一字不改地进条件 text。"""
    conds = []
    point_id = ""
    for i, miss in enumerate(wait.get("frozen_missing") or []):
        if isinstance(miss, dict):
            basis = miss.get("basis") or {}
            text = miss.get("condition") or ""
            btype, bref = basis.get("type", ""), basis.get("ref", "")
        else:
            text, btype, bref = str(miss), "", ""
        if btype == "branch" and bref and not point_id:
            point_id = bref
        conds.append(Condition(
            id=f"m{i + 1}", role="required", basis_type=btype,
            basis_ref=bref, evaluator="model", status="not_met",
            recheck_mode="leave_then_return" if btype == "branch"
            else "new_evidence", text=text))
    return Opportunity(
        opportunity_id=wait["wait_id"], setup=wait.get("setup") or "",
        point_id=point_id, state="WAITING_BEHAVIOR",
        conditions=conds, assessment_count=1, test_sequence=1)


def dispatch_due(waits, store):
    """为所有 due 的 wait 登记重判任务。返回新登记数（幂等）。"""
    new = 0
    for wid, w in waits.items():
        if w.get("status") != "due":
            continue
        opp = store.get(wid)
        if opp is None:
            opp = opportunity_from_wait(w)
            store.upsert(opp)
        due_t = (w.get("due") or {}).get("t")
        key = f"{wid}:{opp.revision}:{due_t}:rejudge"
        _, created = store.add_task({
            "request_key": key, "type": "rejudge", "opportunity_id": wid,
            "revision": opp.revision, "due_t": due_t, "status": "pending"})
        new += int(created)
    return new


def apply_outcome(waits, store, wait_id, outcome):
    """消费一个 wait 的待处理 rejudge 任务并落账。返回机会终态。"""
    w = waits[wait_id]
    opp = store.get(wait_id)
    if opp is None:
        raise KeyError(f"机会不存在（先 dispatch）：{wait_id}")
    pend = [t for t in store.pending_tasks("rejudge")
            if t["opportunity_id"] == wait_id]
    if not pend:
        raise KeyError(f"无待处理 rejudge 任务：{wait_id}")
    task = pend[0]
    if outcome == "still_missing":
        statuses = {c.id: "not_met" for c in opp.conditions
                    if c.role == "required"}
        apply_assessment(opp, statuses, revision=opp.revision)
        w["status"] = "open"  # 同一机会续等：等下一次离开-返回
        w["due"] = None
    elif outcome == "ready":
        statuses = {c.id: "met" for c in opp.conditions
                    if c.role == "required"}
        apply_assessment(opp, statuses, revision=opp.revision,
                         plan_valid=True)
    elif outcome == "invalidated":
        transition(opp, {"kind": "deterministic_cancel",
                         "reason": "REJUDGE_INVALIDATED"})
        w["status"] = "cancelled"
        w["closed"] = {"proxy": "rejudge_invalidated"}
    else:
        raise ValueError(f"未知 outcome：{outcome}")
    store.upsert(opp)
    store.complete_task(task["request_key"], outcome)
    return opp.state


def _cli():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dispatch"
    waits = fw._load_waits()
    with FileOpportunityStore(OPP_PATH) as store:
        if cmd == "dispatch":
            n = dispatch_due(waits, store)
            print(json.dumps({"new_tasks": n,
                              "pending": len(store.pending_tasks("rejudge"))},
                             ensure_ascii=False))
        elif cmd == "apply":
            state = apply_outcome(waits, store, sys.argv[2], sys.argv[3])
            fw._save_waits(waits)
            print(json.dumps({"wait_id": sys.argv[2], "outcome": sys.argv[3],
                              "opportunity_state": state}, ensure_ascii=False))
        else:
            raise SystemExit(f"未知命令：{cmd}")


if __name__ == "__main__":
    _cli()
