"""在线影子引擎（设计 v2.2 T07 组装）：把已落地的零件接成一条
可回放的在线链——

  逐根已收盘 K 线 → 事件器推进尝试（事实事件）
  → 绑定机会按双 recheck 模式记账（note_bar）→ 唤醒生成复核任务
  → 评估器（生产=模型经 model_client 契约注入；测试=脚本化）
  → apply_assessment 推进机会状态
  → READY 且带计划 → 统一决策服务（judge.service）裁决
  → eligible：模拟订单链走完（SUBMITTING→ORDER_PENDING→
    IN_POSITION），登记 tracked 持仓待批量回放解析（沿用现行
    forward_shadow 的「登记—后解析」口径，本引擎不另造一套
    成交语义）；rejected：机会以 GATE_REJECTED 终结（该候选
    死亡，新计划 = 新机会）。

全程审计：每个事件、唤醒、任务、评估、裁决都追加进 audit
（内存列表 + 可选 JSONL 落盘），带 bar_t 与机会 revision，
事后可按审计链回放整条决策。

边界：只吃已收盘 K 线；不连真实行情、不下真实单；评估器与
特征包提供者都是注入的可调用对象，本模块不读文件、不调模型。
"""

import json
import os

from dataclasses import asdict

from judge.service import DecisionRequest, assess_candidate
from runtime.events import (AttemptTracker, advance_attempt,
                            detect_price_events)
from runtime.opportunities import (
    WAITING_BEHAVIOR, apply_assessment, note_bar, transition)

LIFECYCLE = 300


class ShadowEngine:
    def __init__(self, store, levels, bindings=None, assessor=None,
                 pack_provider=None, ledger=None, audit_path=None,
                 strategy_version=""):
        self.store = store
        self.levels = {lv.level_id: lv for lv in levels}
        self.trackers = {lv.level_id: AttemptTracker() for lv in levels}
        self.bindings = dict(bindings or {})  # opportunity_id -> level_id
        self.assessor = assessor              # fn(opp_dict, ctx) -> outcome
        self.pack_provider = pack_provider    # fn(opp_dict, ctx) -> pack
        self.ledger = ledger
        self.strategy_version = strategy_version
        self.audit_path = audit_path
        self.audit = []
        self.tracked = {}                     # opportunity_id -> position
        self.bar_count = 0
        self.prev_bar = None                  # 事件器需要前一根

    # ---- 审计 ----
    def _log(self, kind, bar_t, **fields):
        row = {"kind": kind, "bar_t": bar_t, "seq": len(self.audit)}
        row.update(fields)
        self.audit.append(row)
        if self.audit_path:
            with open(self.audit_path, "a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    # ---- 逐根推进 ----
    def feed_bar(self, bar):
        """推进一根已收盘 K 线，返回本根产生的审计行。"""
        start = len(self.audit)
        self.bar_count += 1
        level_events = {}
        for lid, lv in self.levels.items():
            evs = detect_price_events(self.prev_bar, bar, lv,
                                      self.trackers[lid])
            advance_attempt(self.trackers[lid], evs, bar=bar, level=lv)
            for ev in evs:
                level_events.setdefault(lid, []).append(ev.type)
                self._log("level_event", bar["t"], level_id=lid,
                          event=asdict(ev))
        self.prev_bar = bar
        with self.store:
            for oid, lid in self.bindings.items():
                opp = self.store.get(oid)
                if opp is None or opp.state in (
                        "CLOSED", "CANCELLED", "INVALIDATED",
                        "IN_POSITION", "ORDER_PENDING", "SUBMITTING"):
                    continue
                lv = self.levels[lid]
                self._drive_opportunity(opp, lv, bar,
                                        level_events.get(lid, []))
                self.store.upsert(opp)
        return self.audit[start:]

    def _drive_opportunity(self, opp, lv, bar, ev_types):
        if opp.state == "WATCHING" and "ZONE_TOUCHED" in ev_types:
            transition(opp, {"kind": "zone_touched"})
            self._log("opp_transition", bar["t"], opportunity_id=opp.opportunity_id,
                      to="TESTING", via="zone_touched")
        if opp.state not in ("TESTING", WAITING_BEHAVIOR):
            return
        touches = bar["l"] <= lv.watch_hi and bar["h"] >= lv.watch_lo
        fully_outside = bar["l"] > lv.watch_hi or bar["h"] < lv.watch_lo
        changed = tuple(c.id for c in opp.conditions
                        if c.evaluator == "deterministic"
                        and ev_types) if ev_types else ()
        wake, reason = note_bar(opp, touches_band=touches,
                                fully_outside=fully_outside,
                                changed_conditions=changed)
        if ev_types and opp.state == WAITING_BEHAVIOR:
            # 绑定位置出了新事实事件 = 新证据，唤醒复核（§22.1）
            wake, reason = True, "level_event:" + ev_types[-1]
        if wake:
            key = f"{opp.opportunity_id}:{opp.revision}:{bar['t']}:rejudge:{reason}"
            _, created = self.store.add_task(
                {"request_key": key, "type": "rejudge",
                 "opportunity_id": opp.opportunity_id, "status": "pending",
                 "wake_reason": reason, "bar_t": bar["t"]})
            if created:
                self._log("wake", bar["t"], opportunity_id=opp.opportunity_id,
                          reason=reason, test_sequence=opp.test_sequence)

    # ---- 消费复核任务 ----
    def run_assessments(self):
        """消费 pending 的 rejudge 任务；返回处理条数。"""
        if self.assessor is None:
            return 0
        done = 0
        with self.store:
            for task in self.store.pending_tasks("rejudge"):
                opp = self.store.get(task["opportunity_id"])
                if opp is None:
                    self.store.complete_task(task["request_key"],
                                             "opp_missing")
                    continue
                ctx = {"bar_t": task.get("bar_t"),
                       "wake_reason": task.get("wake_reason")}
                outcome = self.assessor(asdict(opp), ctx)
                self._log("assessment", task.get("bar_t"),
                          opportunity_id=opp.opportunity_id,
                          outcome={k: outcome.get(k) for k in
                                   ("conditions", "cancel_hit",
                                    "plan_valid")})
                apply_assessment(
                    opp, outcome.get("conditions") or {},
                    revision=opp.revision,
                    cancel_hit=bool(outcome.get("cancel_hit")),
                    plan_valid=outcome.get("plan_valid", True))
                self.store.complete_task(task["request_key"], "assessed")
                done += 1
                plan = outcome.get("plan")
                if opp.state == "READY" and plan:
                    self._decide(opp, plan, task.get("bar_t"))
                self.store.upsert(opp)
        return done

    def _decide(self, opp, plan, bar_t):
        pack = self.pack_provider(asdict(opp), {"bar_t": bar_t}) \
            if self.pack_provider else {}
        result = assess_candidate(DecisionRequest(
            snapshot_id=opp.opportunity_id, candidate={"plan": plan},
            feature_pack=pack, bars_left=LIFECYCLE,
            strategy_version=self.strategy_version,
            ledger=self.ledger, mode="annotation"))
        self._log("decision", bar_t, opportunity_id=opp.opportunity_id,
                  status=result.status, reason_code=result.reason_code,
                  rule_hits=result.rule_hits)
        if result.status == "eligible":
            for ev in ("risk_reserved", "order_accepted", "filled"):
                transition(opp, {"kind": ev})
            self.tracked[opp.opportunity_id] = {"plan": plan, "opportunity_id": opp.opportunity_id,
                                    "entry_bar_t": bar_t,
                                    "state": "open_simulated"}
            self._log("position_opened", bar_t, opportunity_id=opp.opportunity_id,
                      plan={k: plan.get(k) for k in
                            ("side", "setup", "entry", "stop", "targets")})
        elif result.status == "rejected":
            opp.state = "CANCELLED"
            opp.reason_code = "GATE_REJECTED"
            opp.revision += 1
        # waiting/invalid_input：机会留在 READY 等下一次复核补计划，
        # 不终结（invalid_input 是调用方契约问题，审计已留痕）

    def audit_kinds(self):
        return [r["kind"] for r in self.audit]
