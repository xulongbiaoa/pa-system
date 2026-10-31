"""触及口径 A/B 回判实验（预注册 eval/reports/touch-ab-prereg-2026-10-31.md）。

prep：按预注册机械规则从 eval/forward 已落账判读中冻结总体（fortress、
judged_no_trade、决策根触及被测点位但收盘在地图点位执法带外），生成
B 臂到达提示（原 evmaprompt 全文，唯一改动 = 备忘规则 1 换分轨认定 +
文末实验口径覆盖块），决策图重渲到持久目录。

score：对 judgments-touch/ 逐份按与 forward_shadow.record 同源的口径
裁决（只换位置执法：limit 按触及、market 按收盘），过门者用决策点后
300 根 simulate_plan 解析，汇总 A/B 对照。

用法：
  python3 eval/touch_ab.py prep [outdir]
  python3 eval/touch_ab.py score [outdir]
"""

import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "eval"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_events  # noqa: E402
import forward_shadow as fs  # noqa: E402
from gate.flags import build_flags  # noqa: E402
from gate.risk_rules import adjudicate  # noqa: E402
from judge.prompt_builder import build_prompt  # noqa: E402
from judge.validate import validate_judgment  # noqa: E402
from perception.features import load_config  # noqa: E402
from render_fast import render_bars  # noqa: E402

CFG = load_config()
DEFAULT_OUT = os.path.join(ROOT, "eval", "touch-ab")

RULE1_B = (
    "1. 每个候选必须在 candidate 中写 point_id，点名上面地图中的一个决胜点；"
    "到达认定分两轨：候选 plan 的 order_type 为 limit 时，决策根 K 线区间"
    "与该点 [lo, hi] 相交（最高 ≥ lo 且最低 ≤ hi）即算到达，可标 qualified；"
    "order_type 为 market 时，仍须决策根收盘价在该点 [lo, hi] ±0.25×段均幅"
    "（附件数字中的段均幅）内才可标 qualified，未达者只许写进 "
    "pending_conditions。\n")

OVERRIDE = (
    "\n\n## 实验口径覆盖（本判读专用，优先级最高）\n\n"
    "本判读是触及口径 A/B 实验的 B 臂：上方备忘规则 1 已按实验口径改写；"
    "正文候选纪律中凡与上述分轨到达认定冲突的位置表述，一律以分轨认定"
    "为准。其余一切纪律（冻结分支触发条件、成色、腿数、RR 定价、void "
    "双件、禁候选降格）一字不变。\n")


def _touched_levels(pack, dec):
    avg = pack["seg_avg_range"]
    tol = 0.25 * avg
    return [lv for lv in build_events.levels_of(pack)
            if dec["l"] <= lv["hi"] + tol and dec["h"] >= lv["lo"] - tol]


def _close_in_band(pack, dec_close, points):
    avg = pack["seg_avg_range"]
    tol = 0.25 * avg
    return any(p["lo"] - tol <= dec_close <= p["hi"] + tol for p in points)


def select_population():
    st = fs.load_state()
    pop = []
    for eid, m in sorted(st["queued"].items()):
        if m.get("kind") != "fortress" or m.get("status") != "judged_no_trade":
            continue
        mp = os.path.join(fs.MAPS_DIR, eid + ".json")
        sp = m.get("snapshot")
        if not (os.path.exists(mp) and sp and os.path.exists(sp)):
            continue
        seg = json.load(open(sp))
        bars = seg["bars"]
        pack = fs.pack_at(bars, CFG)
        dec = bars[-1]
        if not _touched_levels(pack, dec):
            continue
        points = (json.load(open(mp)).get("points") or [])
        if _close_in_band(pack, dec["c"], points):
            continue
        pop.append({"eid": eid, "symbol": m["symbol"],
                    "interval": m["interval"], "decision_t": m["decision_t"],
                    "snapshot": sp, "map": mp})
    return pop


def prep(outdir):
    pop = select_population()
    pdir = os.path.join(outdir, "prompts-touch")
    cdir = os.path.join(outdir, "charts-touch")
    os.makedirs(pdir, exist_ok=True)
    os.makedirs(cdir, exist_ok=True)
    for ev in pop:
        eid = ev["eid"]
        seg = json.load(open(ev["snapshot"]))
        map_obj = json.load(open(ev["map"]))
        pack = fs.pack_at(seg["bars"], CFG)
        text = build_prompt(pack, seg["bars"], segment=eid,
                            symbol=ev["symbol"])
        memo = (
            "\n\n## 战役备忘（冻结地图附件，本事件开始前画定，不许重画、不许改点）\n\n"
            "下面是本事件的战役地图（决胜点、主/备假设及其 holds_if / takeover_if / void_if 条款）：\n\n"
            "```json\n" + json.dumps(map_obj, ensure_ascii=False, indent=1)
            + "\n```\n\n使用规则（硬纪律）：\n" + RULE1_B
            + "2. 地图假设的 void_if 或战役作废条件已经发生时（例如价格已越过地图标注的 "
              "MM 投影且该假设的顺势分支按其条款关闭、或趋势自起点腿的投影已达），"
              "对应方向的候选不许标 qualified。\n"
            + "3. 地图只供位置与战役状态（决胜点在哪、本腿走到哪一步、哪条分支还活着）；"
              "形态、触发、成色仍以你对图的判读为准；位置与图读冲突时，位置以地图为准。\n")
        open(os.path.join(pdir, eid + ".md"), "w").write(text + memo + OVERRIDE)
        render_bars(seg["bars"], os.path.join(cdir, eid + ".png"))
    json.dump(pop, open(os.path.join(outdir, "population.json"), "w"),
              ensure_ascii=False, indent=1)
    print(json.dumps({"population": len(pop),
                      "ids": [e["eid"] for e in pop]}, ensure_ascii=False))


def _b_point_check(c, plan, map_obj, pack, dec):
    pts = {p["id"]: p for p in map_obj.get("points") or []}
    pid = c.get("point_id")
    if not pid:
        return "qualified 候选缺 point_id"
    if pid not in pts:
        return f"point_id {pid} 不在地图决胜点中"
    pt = pts[pid]
    if (plan.get("order_type") or "").lower() == "limit":
        if not (dec["l"] <= pt["hi"] and dec["h"] >= pt["lo"]):
            return (f"限价触及未成立：决策根区间 [{dec['l']}, {dec['h']}] "
                    f"与点 {pid} [{pt['lo']}, {pt['hi']}] 不相交")
        return None
    avg = pack.get("seg_avg_range") or 0
    tol = 0.25 * avg
    if not (pt["lo"] - tol <= dec["c"] <= pt["hi"] + tol):
        return (f"市价收盘 {dec['c']} 不在点 {pid} "
                f"[{pt['lo']}, {pt['hi']}] ±0.25×段均幅({avg}) 内")
    return None


def score(outdir):
    pop = json.load(open(os.path.join(outdir, "population.json")))
    jdir = os.path.join(outdir, "judgments-touch")
    rep = {"population": len(pop), "judged": 0, "format_errors": 0,
           "candidates": 0, "qualified": 0, "qualified_by_setup": {},
           "violations": [], "gate_reject": {}, "tracked": 0,
           "unresolved": 0, "trades": []}
    for ev in pop:
        eid = ev["eid"]
        jp = os.path.join(jdir, eid + ".json")
        if not os.path.exists(jp):
            continue
        rep["judged"] += 1
        try:
            j = json.load(open(jp))
        except Exception:
            rep["format_errors"] += 1
            continue
        if validate_judgment(j):
            rep["format_errors"] += 1
            continue
        rep["candidates"] += len(j.get("candidates") or [])
        cands = [c for c in j.get("candidates", []) if c.get("qualified")]
        if not cands:
            continue
        c = cands[0]
        rep["qualified"] += 1
        rep["qualified_by_setup"][c.get("setup")] = \
            rep["qualified_by_setup"].get(c.get("setup"), 0) + 1
        seg = json.load(open(ev["snapshot"]))
        pack = fs.pack_at(seg["bars"], CFG)
        plan = dict(c["plan"])
        fs.merge_candidate_terms(plan, c)
        plan.update({"side": c["side"], "setup": c.get("setup"),
                     "context": pack["trend"]["label"]})
        map_obj = json.load(open(ev["map"]))
        reason = _b_point_check(c, plan, map_obj, pack, seg["bars"][-1])
        if reason:
            rep["violations"].append({"event": eid, "reason": reason})
            continue
        verdict = adjudicate(plan, pack, bars_left=fs.LIFECYCLE,
                             feature_refs=c.get("feature_refs", []),
                             flags=build_flags(plan, pack),
                             ledger=None, mode="annotation")
        if verdict["verdict"] == "reject":
            for h in verdict["hard_hits"]:
                rep["gate_reject"][h] = rep["gate_reject"].get(h, 0) + 1
            continue
        rep["tracked"] += 1
        bars = fs.fetch_bars(ev["symbol"], ev["interval"], limit=400,
                             start_ms=ev["decision_t"])
        future = [b for b in bars if b["t"] > ev["decision_t"]][:fs.LIFECYCLE]
        t = fs.simulate_plan(future, plan, c["side"], window=fs.LIFECYCLE)
        row = {"event": eid, "setup": c.get("setup"), "side": c["side"],
               "entry": plan.get("entry"), "order_type": plan.get("order_type")}
        if not t.get("filled", True):
            if len(future) >= fs.LIFECYCLE:
                row.update({"outcome": "unfilled", "r": 0.0})
                rep["trades"].append(row)
            else:
                rep["unresolved"] += 1
            continue
        if t["exit_reason"] == "window_end" and len(future) < fs.LIFECYCLE:
            rep["unresolved"] += 1
            continue
        row.update({"outcome": "traded", "r": t["r"],
                    "exit_reason": t["exit_reason"],
                    "exit_bar": t["exit_bar"]})
        rep["trades"].append(row)
    done = rep["trades"]
    denom = len(done)
    sum_r = sum(t["r"] for t in done)
    rep["resolved_events"] = denom
    rep["sum_r"] = round(sum_r, 4)
    rep["per_opportunity_r"] = round(sum_r / denom, 4) if denom else None
    if denom:
        rng = random.Random(20261031)
        vals = [t["r"] for t in done]
        means = sorted(sum(rng.choice(vals) for _ in range(denom)) / denom
                       for _ in range(2000))
        rep["per_opp_ci95"] = [round(means[50], 4), round(means[1949], 4)]
    json.dump(rep, open(os.path.join(outdir, "score.json"), "w"),
              ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prep"
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    {"prep": prep, "score": score}[cmd](out)
