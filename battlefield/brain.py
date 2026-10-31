"""单一大脑判读层（W06 / 方案 §10，2026-10-31 用户定性“一个全局大脑”后定案）。

设计定案：不再分 MAP / ARRIVAL 两个任务。一个判读任务同时读
- 全局：get_scene（地形/开放缺口/目标/争夺/假设/观察计划）；
- 局部：自上次 read cursor 以来的 get_changes（最近交战与事件）。
假设由这一个大脑集中维护（add / confirm / challenge / supersede，带修订历史）。

硬契约：
- 输出必须回显 read_cursor == 本次快照 revision，不符 = 过期评估（StaleAssessment），不落任何写入；
- 一切引用先全量核验、后统一落盘（校验不过 = 契约错误，不写一半）；
- 模型不可用/超时是系统结果（model_unavailable），绝不记成策略无机会，cursor 不推进；
- 候选只进 candidate_proposals 提案分区，不是事实、不是订单，gate 在本层之外；
- 本层没有任何写事实的通道：只能写假设/观察计划/候选三个提案分区。
"""
from __future__ import annotations

import copy
from typing import Callable, List, Optional

from .queries import QueryService, _validate_refs, make_token, propose_watch_plan
from .repository import InMemoryRepository

ACTIONS = ("WATCH", "WAIT_BEHAVIOR", "PROPOSE_CANDIDATE", "CANCEL",
           "INFORMATION_INSUFFICIENT")
HYP_OPS = ("add", "confirm", "challenge", "supersede")


class ModelUnavailable(Exception):
    """模型不可用/超时：系统结果，不是策略结论。"""


class StaleAssessment(Exception):
    """输出回显的 read_cursor 与快照不符：过期评估，丢弃不落盘。"""


class ModelContractError(ValueError):
    """输出违反契约（动作枚举/引用/字段）：契约错误，不落盘。"""


class RecordedAdapter:
    """录制回放适配器：按序返回预录输出（深拷贝），耗尽即 ModelUnavailable。"""

    def __init__(self, outputs: List[dict]):
        self._outputs = list(outputs)

    def __call__(self, package: dict) -> dict:
        if not self._outputs:
            raise ModelUnavailable("录制输出已耗尽")
        return copy.deepcopy(self._outputs.pop(0))


class CallableAdapter:
    def __init__(self, fn: Callable[[dict], dict]):
        self._fn = fn

    def __call__(self, package: dict) -> dict:
        return self._fn(package)


def _check_refs(kernel, refs) -> None:
    """引用核验：queries 的 ValueError 在大脑层统一转成契约错误。"""
    try:
        _validate_refs(kernel, refs)
    except ValueError as exc:
        raise ModelContractError(str(exc)) from exc


def build_task_package(repo: InMemoryRepository, since_revision: int) -> dict:
    """组装单次判读的完整输入：全局 scene + 局部 changes + 当前假设与计划。"""
    token = make_token(repo)
    qs = QueryService(repo, token)
    k = repo.kernel
    return {
        "token": token,
        "snapshot_revision": k.revision,
        "cursor": k.cursor,
        "scene": qs.get_scene(),
        "changes": qs.get_changes(since_revision),
        "side_up": qs.get_side_activity("up"),
        "side_down": qs.get_side_activity("down"),
        "hypotheses": copy.deepcopy(k.hypotheses),
        "watch_plans": copy.deepcopy(k.watch_plans),
    }


class BrainSession:
    """一个大脑的持续会话：持有 read cursor，逐次消费新事件并维护假设。"""

    def __init__(self, repo: InMemoryRepository, adapter):
        self.repo = repo
        self.adapter = adapter
        self.read_revision = 0          # 已消费到的状态 revision
        self.runs: List[dict] = []      # 每次运行的结果留痕（含系统结果）

    # ---------- 主入口 ----------
    def run_once(self) -> dict:
        package = build_task_package(self.repo, self.read_revision)
        try:
            output = self.adapter(package)
        except (ModelUnavailable, TimeoutError) as exc:
            result = {"status": "model_unavailable", "detail": str(exc),
                      "snapshot_revision": package["snapshot_revision"]}
            self.runs.append(result)
            return result
        try:
            applied = self._validate_and_apply(package, output)
        except StaleAssessment as exc:
            result = {"status": "stale", "detail": str(exc),
                      "snapshot_revision": package["snapshot_revision"]}
            self.runs.append(result)
            return result
        except ModelContractError as exc:
            result = {"status": "contract_error", "detail": str(exc),
                      "snapshot_revision": package["snapshot_revision"]}
            self.runs.append(result)
            return result
        self.read_revision = package["snapshot_revision"]
        result = {"status": "ok", "action": output.get("action"),
                  "snapshot_revision": package["snapshot_revision"], **applied}
        self.runs.append(result)
        return result

    # ---------- 校验后统一落盘 ----------
    def _validate_and_apply(self, package: dict, output) -> dict:
        k = self.repo.kernel
        if not isinstance(output, dict):
            raise ModelContractError("输出必须是对象")
        if output.get("read_cursor") != package["snapshot_revision"]:
            raise StaleAssessment(
                f"read_cursor={output.get('read_cursor')} != snapshot {package['snapshot_revision']}")
        action = output.get("action")
        if action not in ACTIONS:
            raise ModelContractError(f"动作不在枚举内: {action}")
        rev = package["snapshot_revision"]

        hyp_ops = output.get("hypothesis_ops") or []
        plan = output.get("watch_plan")
        candidate = output.get("candidate")

        # —— 先全量校验（假设操作按序校验：同批先 add 出的假设可被后续 op 引用） ——
        known_hyp_ids = {h.get("hyp_id") for h in k.hypotheses}
        planned = len(k.hypotheses)
        for op in hyp_ops:
            kind = op.get("op")
            if kind not in HYP_OPS:
                raise ModelContractError(f"假设操作不在枚举内: {kind}")
            if kind in ("confirm", "challenge", "supersede") \
                    and op.get("hyp_id") not in known_hyp_ids:
                raise ModelContractError(f"假设不存在: {op.get('hyp_id')}")
            if kind in ("add", "supersede"):
                if not op.get("text"):
                    raise ModelContractError("add/supersede 必须带 text")
                refs = list(op.get("support_refs", [])) + list(op.get("counter_refs", []))
                if not refs:
                    raise ModelContractError("新假设必须至少带一条可核验引用")
                _check_refs(k, refs)
                planned += 1
                known_hyp_ids.add(f"H{planned}")
        if plan is not None:
            for f in ("watch_level", "watch_behavior", "entry_trigger", "cancel_if"):
                if not plan.get(f):
                    raise ModelContractError(f"观察计划缺四段链字段: {f}")
            _check_refs(k, [plan["watch_level"]])
        if action == "PROPOSE_CANDIDATE":
            if not candidate:
                raise ModelContractError("PROPOSE_CANDIDATE 必须带 candidate")
            refs = list(candidate.get("refs", []))
            if not refs:
                raise ModelContractError("候选必须带可核验引用")
            _check_refs(k, refs)

        # —— 再统一落盘（只写提案分区） ——
        applied = {"hypotheses_changed": [], "watch_plan_added": None,
                   "candidate_proposed": None}
        for op in hyp_ops:
            applied["hypotheses_changed"].append(self._apply_hyp_op(op, rev))
        if plan is not None:
            entry = propose_watch_plan(self.repo, plan)
            applied["watch_plan_added"] = entry.get("plan_id") or "watch_plan"
        if action == "PROPOSE_CANDIDATE":
            entry = {"status": "proposed", "revision": rev, **copy.deepcopy(candidate)}
            k.candidate_proposals.append(entry)
            applied["candidate_proposed"] = entry
        return applied

    def _find_hyp(self, hyp_id: Optional[str]):
        for h in self.repo.kernel.hypotheses:
            if h.get("hyp_id") == hyp_id:
                return h
        return None

    def _apply_hyp_op(self, op: dict, rev: int) -> str:
        k = self.repo.kernel
        kind = op["op"]
        if kind in ("add", "supersede"):
            new_id = f"H{len(k.hypotheses) + 1}"
            entry = {"hyp_id": new_id, "kind": "hypothesis", "status": "active",
                     "text": op["text"],
                     "support_refs": list(op.get("support_refs", [])),
                     "counter_refs": list(op.get("counter_refs", [])),
                     "history": [{"revision": rev, "op": kind,
                                  "reason": op.get("reason", "")}]}
            if kind == "supersede":
                old = self._find_hyp(op["hyp_id"])
                old["status"] = "superseded"
                old["history"].append({"revision": rev, "op": "superseded_by",
                                       "by": new_id, "reason": op.get("reason", "")})
                entry["supersedes"] = op["hyp_id"]
            k.hypotheses.append(entry)
            return new_id
        hyp = self._find_hyp(op["hyp_id"])
        if kind == "challenge":
            hyp["status"] = "challenged"
        hyp["history"].append({"revision": rev, "op": kind,
                               "reason": op.get("reason", "")})
        return hyp["hyp_id"]
