"""机会状态机（设计 v2.2 §6/§15/§22 的 P1 核心，纯逻辑）。

把「判读写下 pending 然后蒸发」改成持久机会：同一 opportunity_id
跨多次测试与复核续等，条件集冻结，取消优先，三个计数分开记。

状态（§15）：WATCHING → TESTING → WAITING_BEHAVIOR → READY →
SUBMITTING → ORDER_PENDING → IN_POSITION → CLOSED；未成交状态可
→ CANCELLED（运营终结）/ INVALIDATED（价格反证）。机会状态与订单
生命周期分开表达：SUBMITTING/ORDER_PENDING 期间的失效只置
cancel_requested，不宣称终结。

计数（§22.2，互不混用）：
- assessment_count：被接受（revision 匹配、通过契约）的行为评估数；
  API 重试、迟到响应、重复任务不计。
- test_sequence：第一次测试成立或 leave_then_return 武装后出现新
  测试边界时递增；同次测试内复核、连续触及、模型自称二测不计。
- unknown_streak[cid]：被接受的评估仍判该条件 unknown 时递增；
  非 unknown 结果清零；API 错误不涉及。

unknown 终止（§22.3）：unknown_policy 必填（review_hold /
operational_expire），无默认值；只有 required/veto 条件达上限才
触发，enhancing 不触发。review_hold 停模型复核但确定性取消继续；
operational_expire 转 CANCELLED 并标运营终结（非策略反证）。

复核唤醒（§22.1）：recheck_mode 是冻结条件组的属性，模型不得
逐轮切换。new_evidence = 相关确定性结果变化即可唤醒，不必先离
开观察带；leave_then_return = 整根离开观察带（armed）后返回触及
才算新测试边界。预算用尽由调用方以 budget_available=False 传入，
本模块只标 deferred，不丢事实。
"""

from dataclasses import dataclass, field

WATCHING = "WATCHING"
TESTING = "TESTING"
WAITING_BEHAVIOR = "WAITING_BEHAVIOR"
READY = "READY"
SUBMITTING = "SUBMITTING"
ORDER_PENDING = "ORDER_PENDING"
IN_POSITION = "IN_POSITION"
CLOSED = "CLOSED"
CANCELLED = "CANCELLED"
INVALIDATED = "INVALIDATED"
PRE_SUBMIT = (WATCHING, TESTING, WAITING_BEHAVIOR, READY)
SUBMITTED = (SUBMITTING, ORDER_PENDING)

ROLE_REQUIRED = "required"
ROLE_ENHANCING = "enhancing"
ROLE_VETO = "veto"
MODE_NEW_EVIDENCE = "new_evidence"
MODE_LEAVE_RETURN = "leave_then_return"


@dataclass
class Condition:
    id: str
    role: str  # required | enhancing | veto
    basis_type: str = ""  # card | branch | skeleton | extra
    basis_ref: str = ""
    evaluator: str = "model"  # deterministic | model
    status: str = "not_met"  # met | not_met | unknown | not_applicable
    scope: str = "current"  # occurrence | current
    recheck_mode: str = MODE_NEW_EVIDENCE
    text: str = ""


@dataclass
class Opportunity:
    opportunity_id: str
    setup: str = ""
    side: str = ""
    point_id: str = ""
    map_version: object = None
    strategy_version: str = ""
    state: str = WATCHING
    revision: int = 0
    conditions: list = field(default_factory=list)
    cancel_conditions: list = field(default_factory=list)  # [{level, side}]
    assessment_count: int = 0
    test_sequence: int = 0
    unknown_streak: dict = field(default_factory=dict)
    unknown_policy: str = ""  # review_hold | operational_expire（必填才生效）
    unknown_limit: int = 0
    review_status: str = ""  # "" | held
    cancel_requested: bool = False
    armed: bool = False  # leave_then_return：已整根离开观察带
    deferred: bool = False  # 预算用尽待复核（事实不丢）
    reason_code: str = ""
    history: list = field(default_factory=list)

    def condition(self, cid):
        for c in self.conditions:
            if c.id == cid:
                return c
        return None

    def required_open(self):
        return [c for c in self.conditions
                if c.role == ROLE_REQUIRED and c.status != "met"
                and c.status != "not_applicable"]


@dataclass
class TransitionResult:
    new_state: str
    new_revision: int
    audit_events: list = field(default_factory=list)
    commands: list = field(default_factory=list)
    accepted: bool = True


def _audit(opp, kind, **kw):
    rec = {"kind": kind, "state": opp.state, "revision": opp.revision}
    rec.update(kw)
    opp.history.append(rec)
    return rec


def _finish(opp, audit, commands, accepted=True):
    return TransitionResult(new_state=opp.state, new_revision=opp.revision,
                            audit_events=audit, commands=commands,
                            accepted=accepted)


def apply_assessment(opp, statuses, *, revision, plan_valid=True,
                     cancel_hit=False, snapshot_id=None):
    """接受一份行为评估（§15 核心转移）。先核取消/否决，再核成立。

    statuses: {condition_id: met|not_met|unknown|not_applicable}。
    revision 必须等于当前 revision，迟到响应只落审计、不改状态。
    plan_valid=False 表示 required 已齐但定价/空间暂不成立
    （SPACE_INSUFFICIENT → 回 WAITING_BEHAVIOR，不是反证）。
    """
    audit = []
    if revision != opp.revision:
        audit.append(_audit(opp, "STALE_ASSESSMENT", snapshot_id=snapshot_id))
        return _finish(opp, audit, [], accepted=False)
    if opp.state not in (TESTING, WAITING_BEHAVIOR):
        audit.append(_audit(opp, "ASSESSMENT_IGNORED_STATE"))
        return _finish(opp, audit, [], accepted=False)
    if opp.review_status == "held":
        audit.append(_audit(opp, "ASSESSMENT_WHILE_HELD"))
        return _finish(opp, audit, [], accepted=False)

    opp.assessment_count += 1
    for cid, st in (statuses or {}).items():
        c = opp.condition(cid)
        if c is not None:
            c.status = st
        if st == "unknown":
            opp.unknown_streak[cid] = opp.unknown_streak.get(cid, 0) + 1
        elif cid in opp.unknown_streak:
            opp.unknown_streak[cid] = 0
    audit.append(_audit(opp, "ASSESSMENT", snapshot_id=snapshot_id,
                        n=opp.assessment_count))

    # 1) 取消/否决优先（同一快照同时满足时取消优先，不发新单）
    veto_met = [c.id for c in opp.conditions
                if c.role == ROLE_VETO and c.status == "met"]
    if cancel_hit or veto_met:
        opp.state = INVALIDATED
        opp.reason_code = "CONDITION_VETO" if veto_met else "CANCEL_HIT"
        opp.revision += 1
        audit.append(_audit(opp, "INVALIDATED", reason=opp.reason_code,
                            veto=veto_met))
        return _finish(opp, audit, [])

    # 2) unknown 达上限（仅 required/veto 计）
    if opp.unknown_policy and opp.unknown_limit:
        hot = [cid for cid, n in opp.unknown_streak.items()
               if n >= opp.unknown_limit
               and (c := opp.condition(cid)) is not None
               and c.role in (ROLE_REQUIRED, ROLE_VETO)
               and c.status == "unknown"]
        if hot:
            if opp.unknown_policy == "review_hold":
                opp.review_status = "held"
                opp.state = WAITING_BEHAVIOR
                audit.append(_audit(opp, "UNKNOWN_REVIEW_LIMIT", hot=hot))
            elif opp.unknown_policy == "operational_expire":
                opp.state = CANCELLED
                opp.reason_code = "UNKNOWN_OPERATIONAL_EXPIRED"
                opp.revision += 1
                audit.append(_audit(opp, "UNKNOWN_OPERATIONAL_EXPIRED",
                                    hot=hot))
            return _finish(opp, audit, [])

    # 3) veto unknown 阻断新入场（不放宽门槛），required 未齐续等
    veto_unknown = [c.id for c in opp.conditions
                    if c.role == ROLE_VETO and c.status == "unknown"]
    open_required = opp.required_open()
    if veto_unknown or open_required:
        opp.state = WAITING_BEHAVIOR
        audit.append(_audit(opp, "WAITING", open=[c.id for c in open_required],
                            veto_unknown=veto_unknown))
        return _finish(opp, audit, [])

    # 4) 全齐：定价有效才 READY，否则空间暂不足续等（非反证）
    if not plan_valid:
        opp.state = WAITING_BEHAVIOR
        opp.reason_code = "SPACE_INSUFFICIENT"
        audit.append(_audit(opp, "WAITING_SPACE"))
        return _finish(opp, audit, [])
    opp.state = READY
    opp.reason_code = ""
    opp.revision += 1
    audit.append(_audit(opp, "READY"))
    return _finish(opp, audit, [{"type": "build_order_intent",
                                 "opportunity_id": opp.opportunity_id,
                                 "revision": opp.revision}])


def transition(opp, event):
    """非评估类事件的转移（§15 表）。event = {"kind": ...}。"""
    kind = event.get("kind")
    audit, commands = [], []
    st = opp.state

    if kind == "zone_touched" and st == WATCHING:
        opp.state = TESTING
        opp.revision += 1
        if opp.test_sequence == 0:
            opp.test_sequence = 1
        audit.append(_audit(opp, "TESTING"))
        commands.append({"type": "assess_behavior",
                         "opportunity_id": opp.opportunity_id,
                         "revision": opp.revision})
    elif kind == "deterministic_cancel":
        if st in PRE_SUBMIT:
            opp.state = INVALIDATED
            opp.reason_code = event.get("reason", "CANCEL_HIT")
            opp.revision += 1
            audit.append(_audit(opp, "INVALIDATED", reason=opp.reason_code))
        elif st in SUBMITTED:
            opp.cancel_requested = True
            audit.append(_audit(opp, "CANCEL_REQUESTED"))
            commands.append({"type": "cancel_order",
                             "opportunity_id": opp.opportunity_id})
        elif st == IN_POSITION:
            audit.append(_audit(opp, "CANCEL_IN_POSITION_IGNORED"))
    elif kind == "api_error":
        # 系统结果，不是策略结论：不计 assessment、不动 unknown_streak
        audit.append(_audit(opp, "API_ERROR", detail=event.get("detail", "")))
    elif kind == "risk_reserved" and st == READY:
        opp.state = SUBMITTING
        opp.revision += 1
        audit.append(_audit(opp, "SUBMITTING"))
        commands.append({"type": "submit_order",
                         "opportunity_id": opp.opportunity_id,
                         "revision": opp.revision})
    elif kind == "order_accepted" and st == SUBMITTING:
        opp.state = ORDER_PENDING
        opp.revision += 1
        audit.append(_audit(opp, "ORDER_PENDING"))
    elif kind == "filled" and st in SUBMITTED:
        opp.state = IN_POSITION
        opp.revision += 1
        audit.append(_audit(opp, "IN_POSITION"))
        commands.append({"type": "protect_position",
                         "opportunity_id": opp.opportunity_id})
    elif kind == "order_cancelled" and st in SUBMITTED:
        opp.state = CANCELLED
        opp.reason_code = "ORDER_CANCELLED_ZERO_FILL"
        opp.revision += 1
        audit.append(_audit(opp, "CANCELLED"))
        commands.append({"type": "release_reservation",
                         "opportunity_id": opp.opportunity_id})
    elif kind == "position_closed" and st == IN_POSITION:
        opp.state = CLOSED
        opp.revision += 1
        audit.append(_audit(opp, "CLOSED"))
    elif kind == "resume_review" and opp.review_status == "held":
        opp.review_status = ""
        opp.unknown_streak = {}
        audit.append(_audit(opp, "RESUME_REVIEW",
                            operator=event.get("operator", ""),
                            reason=event.get("reason", "")))
        commands.append({"type": "assess_behavior",
                         "opportunity_id": opp.opportunity_id,
                         "revision": opp.revision})
    else:
        audit.append(_audit(opp, "TRANSITION_IGNORED", event=kind))
        return _finish(opp, audit, [], accepted=False)
    return _finish(opp, audit, commands)


def note_bar(opp, *, touches_band, fully_outside, changed_conditions=(),
             budget_available=True):
    """按 §22.1 判断本根新 K 是否唤醒复核。返回 (wake, reason)。

    - held 时不唤醒模型复核（确定性取消由调用方照常走 transition）。
    - new_evidence：任一 required 条件的确定性结果变化即唤醒，
      不要求先离开观察带（C18）。
    - leave_then_return：fully_outside 只武装（armed）；armed 后
      touches_band 才是新测试边界 → test_sequence += 1 并唤醒。
    - 仍有 model 型 required 未成立且来了新根 → 唤醒（受预算约束）；
      预算用尽标 deferred、保留待复核标记，不丢事实（C23 的前半）。
    """
    if opp.state not in (TESTING, WAITING_BEHAVIOR):
        return False, "state"
    if opp.review_status == "held":
        return False, "held"
    changed = set(changed_conditions or ())
    for c in opp.conditions:
        if c.role == ROLE_REQUIRED and c.recheck_mode == MODE_NEW_EVIDENCE \
                and c.id in changed:
            if not budget_available:
                opp.deferred = True
                return False, "deferred_budget"
            opp.deferred = False
            return True, "new_evidence"
    lr = [c for c in opp.conditions
          if c.role == ROLE_REQUIRED and c.recheck_mode == MODE_LEAVE_RETURN]
    if lr:
        if fully_outside:
            opp.armed = True
            return False, "armed"
        if opp.armed and touches_band:
            opp.armed = False
            opp.test_sequence += 1
            if not budget_available:
                opp.deferred = True
                return False, "deferred_budget"
            opp.deferred = False
            return True, "retest"
    # 新根兜底唤醒只适用于 new_evidence 模式的 model 条件；
    # leave_then_return 条件由上面的测试边界独占唤醒，否则每根都
    # 唤醒等于取消了该模式（§22.1 模式是冻结属性）。
    open_model = [c for c in opp.conditions if c.role == ROLE_REQUIRED
                  and c.evaluator == "model" and c.status != "met"
                  and c.recheck_mode == MODE_NEW_EVIDENCE]
    if open_model:
        if not budget_available:
            opp.deferred = True
            return False, "deferred_budget"
        opp.deferred = False
        return True, "new_bar_model"
    return False, "no_open_conditions"
