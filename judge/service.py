"""统一决策服务（设计 v2.2 T03 / §5 / §14.2）。

所有 runner 只提供数据与实验参数，裁决从这里进：assess_candidate
接收显式 DecisionRequest（快照、候选、条件核验结果、特征包、台账、
策略版本、模式），不隐式读取任何「最新版本」或全局状态；返回
DecisionResult，gate 的硬拒绝原样保存在 rule_hits 与 gate 里，
不许 runner 改写成笼统 no_trade。

状态口径（§14.2）：eligible 只表示策略候选可继续，不等于订单已
批准或成交；waiting = 条件核验仍有 required 未成立（missing 给
出清单）；rejected = gate 硬规则拒绝；invalid_input = 请求契约
不完整。模型/API 错误不走本枚举，由任务层另行记录。

H6 可用性单独成字段：未提供台账时 h6_status="unavailable"，不能
把「没查」记成「通过」（gate notes 里有同义说明，此处结构化）。
"""

from dataclasses import dataclass, field

from gate.risk_rules import adjudicate


@dataclass
class DecisionRequest:
    snapshot_id: str
    candidate: dict  # 至少含 plan{entry, stop, targets} 与 side/setup
    feature_pack: dict
    bars_left: int
    strategy_version: str = ""
    mode: str = "annotation"  # annotation | trainer
    feature_refs: tuple = ()
    flags: dict = None
    ledger: object = None  # {(setup, context): {n, wins}} 或 None
    condition_result: dict = None  # {"open_required": [cid...]}（机会层）


@dataclass
class DecisionResult:
    status: str  # eligible | waiting | rejected | invalid_input
    candidate: dict = None
    missing: list = field(default_factory=list)
    rule_hits: list = field(default_factory=list)  # gate hard_hits 原样
    soft_hits: list = field(default_factory=list)
    reason_code: str = ""
    h6_status: str = ""  # checked | unavailable
    versions: dict = field(default_factory=dict)
    gate: dict = None  # adjudicate 返回原文（迁移期兼容既有调用方）
    notes: list = field(default_factory=list)


def assess_candidate(request):
    cand = request.candidate or {}
    plan = cand.get("plan") or {}
    versions = {"strategy_version": request.strategy_version,
                "snapshot_id": request.snapshot_id}
    if not request.feature_pack or \
            any(plan.get(k) is None for k in ("entry", "stop", "targets")):
        return DecisionResult(status="invalid_input", candidate=cand,
                              reason_code="INVALID_INPUT",
                              versions=versions)

    # 机会层条件核验仍有 required 未成立 → waiting（不进 gate 定价）
    open_required = (request.condition_result or {}).get("open_required") or []
    if open_required:
        return DecisionResult(status="waiting", candidate=cand,
                              missing=list(open_required),
                              reason_code="CONDITION_MISSING",
                              h6_status="unavailable" if request.ledger is None
                              else "checked",
                              versions=versions)

    full_plan = dict(plan)
    for k in ("side", "setup", "context"):
        if cand.get(k) is not None and k not in full_plan:
            full_plan[k] = cand[k]
    gate = adjudicate(full_plan, request.feature_pack,
                      bars_left=request.bars_left,
                      feature_refs=list(request.feature_refs or ()),
                      flags=request.flags or {},
                      ledger=request.ledger,
                      mode=request.mode)
    hard = gate.get("hard_hits") or []
    return DecisionResult(
        status="rejected" if hard else "eligible",
        candidate=cand,
        rule_hits=hard,
        soft_hits=gate.get("soft_hits") or [],
        reason_code=hard[0]["rule"] if hard else "",
        h6_status="unavailable" if request.ledger is None else "checked",
        versions=versions,
        gate=gate,
        notes=gate.get("notes") or [])
