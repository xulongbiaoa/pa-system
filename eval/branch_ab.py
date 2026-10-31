"""分支预写 A/B 验证（预注册 eval/reports/branch-ab-prereg-2026-10-31.md）。

总体复用 eval/touch-ab/population.json 的 55 个事件。三段：
  prepmaps     按现行 MAP 任务（已含分支预写三条款）生成重画地图提示
               与触发根图（map_bar 取 forward state 中原记录）。
  preparrivals 地图落盘后生成到达提示：正文与 touch B 臂逐字相同
               （分轨认定备忘 + 覆盖块），地图换成 maps2；决策图复用
               eval/touch-ab/charts-touch/。
  score        与 touch_ab.score 同源裁决（触及执法），另加操作检查：
               maps2 与同事件旧图的 trigger 文本统计对照（跟进出现率、
               条件叠加分布），以及被测位 ∈ maps2 点位比例。

用法：
  python3 eval/branch_ab.py prepmaps [outdir]
  python3 eval/branch_ab.py preparrivals [outdir]
  python3 eval/branch_ab.py score [outdir]
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "eval"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_events  # noqa: E402
import forward_shadow as fs  # noqa: E402
import touch_ab as tab  # noqa: E402
from gate.flags import build_flags  # noqa: E402
from gate.risk_rules import adjudicate  # noqa: E402
from judge.campaign_prompt import build_map_prompt  # noqa: E402
from judge.prompt_builder import build_prompt  # noqa: E402
from judge.validate import validate_judgment  # noqa: E402
from perception.features import load_config  # noqa: E402
from render_fast import render_bars  # noqa: E402

CFG = load_config()
DEFAULT_OUT = os.path.join(ROOT, "eval", "branch-ab")
POP_PATH = os.path.join(ROOT, "eval", "touch-ab", "population.json")
TOUCH_CHARTS = os.path.join(ROOT, "eval", "touch-ab", "charts-touch")

REQ = {
    "收盘越界": r"收盘|收回|站上|站稳",
    "跟进确认": r"跟进",
    "成色门槛": r"实体|CLV|强阳|强阴|大阳|大阴|成色|饱满",
    "腿数结构": r"第二腿|两腿|二腿|回踩|回调",
    "不创新极值": r"不创|未创|不破|未破|不越",
    "区间触及": r"触及|摸到|刺穿|影线",
}


def _trigger_stats(map_paths):
    n_br = 0
    req_n = {}
    stack = {}
    for p in map_paths:
        m = json.load(open(p))
        for b in m.get("branches") or []:
            n_br += 1
            hits = {k for k, pat in REQ.items()
                    if re.search(pat, b.get("trigger") or "")}
            for h in hits:
                req_n[h] = req_n.get(h, 0) + 1
            stack[len(hits)] = stack.get(len(hits), 0) + 1
    return {"branches": n_br, "req_counts": req_n, "stack_dist": stack}


def _pop():
    return json.load(open(POP_PATH))


def prepmaps(outdir):
    st = fs.load_state()
    pop = _pop()
    pdir = os.path.join(outdir, "prompts-map2")
    cdir = os.path.join(outdir, "charts-map2")
    os.makedirs(pdir, exist_ok=True)
    os.makedirs(cdir, exist_ok=True)
    missing = []
    for ev in pop:
        eid = ev["eid"]
        meta = st["queued"].get(eid) or {}
        seg = json.load(open(ev["snapshot"]))
        map_bar = meta.get("map_bar")
        if not map_bar:
            trig = fs.compute_trigger(seg["bars"], len(seg["bars"]), CFG)
            map_bar = trig["map_bar"] if trig else None
        if not map_bar:
            missing.append(eid)
            continue
        bars = seg["bars"][:map_bar]
        pack = build_events.pack_at(bars, CFG)
        text = build_map_prompt(pack, bars)
        text = text.replace("第 90 根", f"第 {map_bar} 根")
        open(os.path.join(pdir, eid + ".md"), "w").write(text)
        render_bars(bars, os.path.join(cdir, eid + ".png"))
        ev["map_bar"] = map_bar
    json.dump(pop, open(os.path.join(outdir, "population.json"), "w"),
              ensure_ascii=False, indent=1)
    print(json.dumps({"prepared": len(pop) - len(missing),
                      "trigger_missing": missing}, ensure_ascii=False))


def preparrivals(outdir):
    pop = json.load(open(os.path.join(outdir, "population.json")))
    pdir = os.path.join(outdir, "prompts-arr2")
    os.makedirs(pdir, exist_ok=True)
    missing = []
    for ev in pop:
        eid = ev["eid"]
        mp = os.path.join(outdir, "maps2", eid + ".json")
        if not os.path.exists(mp):
            missing.append(eid)
            continue
        seg = json.load(open(ev["snapshot"]))
        map_obj = json.load(open(mp))
        pack = fs.pack_at(seg["bars"], CFG)
        text = build_prompt(pack, seg["bars"], segment=eid,
                            symbol=ev["symbol"])
        memo = (
            "\n\n## 战役备忘（冻结地图附件，本事件开始前画定，不许重画、不许改点）\n\n"
            "下面是本事件的战役地图（决胜点、主/备假设及其 holds_if / takeover_if / void_if 条款）：\n\n"
            "```json\n" + json.dumps(map_obj, ensure_ascii=False, indent=1)
            + "\n```\n\n使用规则（硬纪律）：\n" + tab.RULE1_B
            + "2. 地图假设的 void_if 或战役作废条件已经发生时（例如价格已越过地图标注的 "
              "MM 投影且该假设的顺势分支按其条款关闭、或趋势自起点腿的投影已达），"
              "对应方向的候选不许标 qualified。\n"
            + "3. 地图只供位置与战役状态（决胜点在哪、本腿走到哪一步、哪条分支还活着）；"
              "形态、触发、成色仍以你对图的判读为准；位置与图读冲突时，位置以地图为准。\n")
        open(os.path.join(pdir, eid + ".md"), "w").write(
            text + memo + tab.OVERRIDE)
    print(json.dumps({"prepared": len(pop) - len(missing),
                      "map_missing": missing}, ensure_ascii=False))


def score(outdir):
    pop = json.load(open(os.path.join(outdir, "population.json")))
    jdir = os.path.join(outdir, "judgments2")
    rep = {"population": len(pop), "judged": 0, "format_errors": 0,
           "candidates": 0, "qualified": 0, "qualified_by_setup": {},
           "violations": [], "gate_reject": {}, "tracked": 0,
           "unresolved": 0, "trades": [], "point_coverage_maps2": [0, 0]}
    for ev in pop:
        eid = ev["eid"]
        seg = json.load(open(ev["snapshot"]))
        pack = fs.pack_at(seg["bars"], CFG)
        map2_path = os.path.join(outdir, "maps2", eid + ".json")
        if os.path.exists(map2_path):
            levels = tab._touched_levels(pack, seg["bars"][-1])
            pts = (json.load(open(map2_path)).get("points") or [])
            rep["point_coverage_maps2"][1] += 1
            if any(p["lo"] <= lv["hi"] and lv["lo"] <= p["hi"]
                   for lv in levels for p in pts):
                rep["point_coverage_maps2"][0] += 1
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
        plan = dict(c["plan"])
        fs.merge_candidate_terms(plan, c)
        plan.update({"side": c["side"], "setup": c.get("setup"),
                     "context": pack["trend"]["label"]})
        map_obj = json.load(open(map2_path))
        reason = tab._b_point_check(c, plan, map_obj, pack, seg["bars"][-1])
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
               "entry": plan.get("entry"),
               "order_type": plan.get("order_type")}
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
    rep["resolved_events"] = len(done)
    rep["sum_r"] = round(sum(t["r"] for t in done), 4)
    rep["per_opportunity_r"] = (round(rep["sum_r"] / len(done), 4)
                                if done else None)
    old_paths = [ev["map"] for ev in pop]
    new_paths = [os.path.join(outdir, "maps2", ev["eid"] + ".json")
                 for ev in pop]
    rep["trigger_stats_old"] = _trigger_stats(
        [p for p in old_paths if os.path.exists(p)])
    rep["trigger_stats_new"] = _trigger_stats(
        [p for p in new_paths if os.path.exists(p)])
    json.dump(rep, open(os.path.join(outdir, "score.json"), "w"),
              ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prepmaps"
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    {"prepmaps": prepmaps, "preparrivals": preparrivals,
     "score": score}[cmd](out)
