"""存量订单语义审计（2026-10-31，设计 v2.2 P0 配套）。

背景：旧 replay 对 order_type=market 的计划从决策后第一根起按计划
entry 无条件成交。本脚本普查各实验账本里已解析的 plan 型交易，按
order_type 分类；market 型逐笔用决策时点数据复核语义：
- entry ≈ 决策收盘 → 真市价（旧结果近似可用，新口径按次根开盘重算对照）；
- entry 在触发侧（多头在上/空头在下）→ 旧 stop 语义误标 market，
  按 stop_market 重算：未触发 = 未触发误成交；触发 = 给出修正 R；
- entry 在逆触发侧 → LEGACY_ORDER_AMBIGUOUS（语义不明，附 limit
  口径重算参考），不得跨界比对。

输出 eval/reports/order-semantics-audit-2026-10-31.{json,md}。
只读审计：不改任何既有结果文件。
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from replay import simulate_plan  # noqa: E402

EVAL = os.path.dirname(os.path.abspath(__file__))
WINDOW = 300


def load_json(path):
    with open(path) as f:
        return json.load(f)


def qualified_plan(judgment):
    for c in judgment.get("candidates") or []:
        if c.get("qualified") and c.get("plan"):
            return c["plan"]
    return None


def seg_bars(dataset, segment):
    d = load_json(os.path.join(EVAL, "datasets", dataset, segment + ".json"))
    return d["bars"] if isinstance(d, dict) else d


def audit_market_trade(store, event, plan, decision_bar, bars_after):
    """分类以决策根极值为准（离收盘近不等于市价：entry 恰在信号根
    高点外 1 tick 是标准 stop 触发，哪怕只差 0.03%）。"""
    side = plan["side"] if "side" in plan else None
    entry = plan["entry"]
    if side is None:
        side = "long" if entry else None
    decision_close = decision_bar["c"]
    rel = (entry - decision_close) / decision_close if decision_close else 0.0
    row = {"store": store, "event": event, "side": side, "entry": entry,
           "decision_close": decision_close, "rel_dev": round(rel, 5),
           "recorded_r": None}
    if side == "long":
        trigger_side = entry > decision_bar["h"]
        opposite_side = entry < decision_bar["l"]
    else:
        trigger_side = entry < decision_bar["l"]
        opposite_side = entry > decision_bar["h"]
    near = abs(rel) <= 0.0005 and not trigger_side and not opposite_side
    if near:
        row["class"] = "true_market"
        new_plan = dict(plan, order_type="market")
        t = simulate_plan(bars_after, new_plan, side, window=WINDOW)
        row["new_r"] = t.get("r")
        row["new_filled"] = t.get("filled")
    elif trigger_side:
        row["class"] = "legacy_stop_semantics"
        new_plan = dict(plan, order_type="stop_market")
        t = simulate_plan(bars_after, new_plan, side, window=WINDOW)
        row["new_filled"] = t.get("filled")
        row["new_r"] = t.get("r")
        row["new_exit_reason"] = t.get("exit_reason")
        if not t.get("filled"):
            row["class"] = "untriggered_misfill"
    else:
        row["class"] = "legacy_ambiguous"
        lim_plan = dict(plan, order_type="limit")
        t = simulate_plan(bars_after, lim_plan, side, window=WINDOW)
        row["as_limit_filled"] = t.get("filled")
        row["as_limit_r"] = t.get("r")
        row["as_limit_exit"] = t.get("exit_reason")
        stop_plan = dict(plan, order_type="stop_market")
        t = simulate_plan(bars_after, stop_plan, side, window=WINDOW)
        row["as_stop_filled"] = t.get("filled")
        row["as_stop_r"] = t.get("r")
        row["as_stop_exit"] = t.get("exit_reason")
    return row


def main():
    rows = []
    counts = {}

    def note(store, cls):
        counts.setdefault(store, {})
        counts[store][cls] = counts[store].get(cls, 0) + 1

    # ---- branch-ab ----
    score = load_json(os.path.join(EVAL, "branch-ab", "score.json"))
    pop = {e["eid"]: e for e in load_json(os.path.join(EVAL, "branch-ab", "population.json"))}
    for tr in score.get("trades", []):
        eid, ot = tr["event"], tr.get("order_type")
        if ot == "limit":
            note("branch-ab", "unaffected_limit"); continue
        ev = pop[eid]
        snap = load_json(ev["snapshot"])
        bars = snap["bars"]
        dt = ev["decision_t"]
        upto = [b for b in bars if b["t"] <= dt]
        after = [b for b in bars if b["t"] > dt]
        plan = qualified_plan(load_json(os.path.join(EVAL, "branch-ab", "judgments2", eid + ".json")))
        plan = dict(plan, side=tr["side"])
        if not after:  # 快照只到决策点：生命周期 bars 按 score 原路拉取
            import forward_shadow as fs
            fetched = fs.fetch_bars(ev["symbol"], ev["interval"], limit=1000)
            after = [b for b in fetched if b["t"] > dt][:WINDOW]
        r = audit_market_trade("branch-ab", eid, plan, upto[-1], after)
        r["recorded_r"] = tr["r"]; r["setup"] = tr["setup"]
        rows.append(r); note("branch-ab", r["class"])

    # ---- touch-ab ----
    score = load_json(os.path.join(EVAL, "touch-ab", "score.json"))
    for tr in score.get("trades", []):
        if tr.get("order_type") == "limit":
            note("touch-ab", "unaffected_limit")

    # ---- event-ab（四臂）----
    res = load_json(os.path.join(EVAL, "event-ab", "result.json"))
    events = {e["eid"]: e for e in load_json(os.path.join(EVAL, "event-ab", "events.json"))}
    arm_jdir = {"auto": "judgments-auto", "camp": "judgments-camp",
                "hybrid": "judgments-hybrid", "evmap": "judgments-evmap"}
    for arm in arm_jdir:
        for tr in res.get(arm, {}).get("trades", []):
            eid, ot = tr["event"], tr.get("order_type")
            store = f"event-ab/{arm}"
            if ot == "limit":
                note(store, "unaffected_limit"); continue
            ev = events[eid]
            bars = seg_bars(ev["dataset"], ev["segment"])
            di = ev["bar"]
            plan = qualified_plan(load_json(os.path.join(
                EVAL, "event-ab", arm_jdir[arm], eid + ".json")))
            plan = dict(plan, side=tr["side"])
            r = audit_market_trade(store, eid, plan, bars[di], bars[di + 1:])
            r["recorded_r"] = tr["r"]; r["setup"] = tr["setup"]
            rows.append(r); note(store, r["class"])

    # ---- camp-vs-auto（随机段版，两臂均 0 成交，仍登记）----
    res = load_json(os.path.join(EVAL, "camp-vs-auto", "result.json"))
    for arm, v in res.items():
        for tr in (v or {}).get("trades", []):
            note(f"camp-vs-auto/{arm}", "unaffected_limit"
                 if tr.get("order_type") == "limit" else "market_other")

    # ---- forward ledger（已成交 2 笔，order_type 查判读原文）----
    for line in open(os.path.join(EVAL, "forward", "ledger.jsonl")):
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("outcome") != "traded":
            continue
        jpath = os.path.join(EVAL, "forward", "judgments", rec["event"] + ".json")
        plan = qualified_plan(load_json(jpath)) if os.path.exists(jpath) else None
        ot = (plan or {}).get("order_type")
        note("forward-ledger", "unaffected_limit" if ot == "limit" else f"ot={ot}")

    # ---- 未解析 tracked 的 order_type（重跑 score 时是否受影响）----
    unresolved = []
    traded_ids = {t["event"] for t in load_json(os.path.join(EVAL, "branch-ab", "score.json")).get("trades", [])}
    for jf in glob.glob(os.path.join(EVAL, "branch-ab", "judgments2", "*.json")):
        eid = os.path.basename(jf)[:-5]
        plan = qualified_plan(load_json(jf))
        if plan and eid not in traded_ids:
            unresolved.append({"store": "branch-ab", "event": eid,
                               "order_type": plan.get("order_type")})

    out = {"counts": counts, "market_rows": rows, "unresolved_tracked": unresolved}
    rdir = os.path.join(EVAL, "reports")
    with open(os.path.join(rdir, "order-semantics-audit-2026-10-31.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
