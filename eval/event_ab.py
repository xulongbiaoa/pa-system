"""AUTO vs CAMP 事件配对对比 runner。

预注册：eval/reports/camp-vs-auto-eventpaired-prereg-2026-10-31.md。
与 campaign_run.py 的区别：决策点不是固定 bar 180，而是检测器在
决策窗 [150, 180) 内机械挖出的事件点（决胜点被测试的时刻）；地图
遍在事件前 90 根。数据全用本地数据集，不等前向影子。

用法：
  mine    <outdir>   挖事件 + 生成 AUTO/MAP 提示与两张图
  arrival <outdir>   读 maps/*.json 生成 ARRIVAL 提示
  score   <outdir>   两臂判读齐后：validate→gate→回放，配对报告
"""

import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "eval"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_events          # noqa: E402
import build_confirm_events  # noqa: E402
from perception.features import load_config                    # noqa: E402
from judge.pa_cli import pack_at                               # noqa: E402
from judge.prompt_builder import build_prompt                  # noqa: E402
from judge.campaign_prompt import build_map_prompt, build_arrival_prompt  # noqa: E402
from judge.validate import validate_judgment                   # noqa: E402
from gate.risk_rules import adjudicate                         # noqa: E402
from gate.flags import build_flags                             # noqa: E402
from eval.replay import simulate_plan, summarize               # noqa: E402
from eval.pilot_run import merge_candidate_terms               # noqa: E402
from render_fast import render_bars                            # noqa: E402

CFG = load_config()
DATASETS_DIR = os.path.join(ROOT, "eval", "datasets")
SCAN_FROM, SCAN_TO = 150, 180
MAP_LAG = 90
LIFECYCLE = 300
TARGET_EVENTS = 20
MIN_EVENTS = 16
# 上轮 CAMP 对比用过的 fresh3 标的；本轮只取其余封存标的
CAMP_V1_USED = {"ICPUSDT", "DASHUSDT", "ZECUSDT", "NEOUSDT", "QTUMUSDT",
                "IOTAUSDT", "ENJUSDT", "SUSHIUSDT", "COMPUSDT", "YFIUSDT"}


def iter_segments():
    """(数据集名, 段 dict) 序列：fresh → fresh2 → fresh3 封存标的。"""
    out = []
    for ds in ("fresh", "fresh2", "fresh3"):
        idx = json.load(open(os.path.join(DATASETS_DIR, ds, "INDEX.json")))
        segs = idx["splits"]["fresh"] if "splits" in idx else idx["segments"]
        for s in sorted(segs, key=lambda x: x["id"]):
            if ds == "fresh3" and s["symbol"] in CAMP_V1_USED:
                continue
            out.append((ds, s))
    return out


def load_seg(ds, sid):
    seg = json.load(open(os.path.join(DATASETS_DIR, ds, sid + ".json")))
    seg["id"], seg["symbol"] = sid, seg.get("symbol")
    return seg


def mine_segment(seg):
    """两类检测器在决策窗内的事件（决策根及以前，因果）。"""
    bars = seg["bars"]
    found = []
    build_events.SCAN_FROM, build_events.SCAN_TO = SCAN_FROM, SCAN_TO - 1
    try:
        for ev in build_events.find_events(seg, CFG):
            found.append({"bar": ev["bar"], "kind": "fortress",
                          "levels": ev.get("levels")})
    finally:
        build_events.SCAN_FROM, build_events.SCAN_TO = 59, 179
    build_confirm_events.SCAN_FROM = SCAN_FROM
    build_confirm_events.SCAN_TO = SCAN_TO
    try:
        for ev in build_confirm_events.find_confirm_events(seg, CFG):
            found.append({"bar": ev["bar"], "kind": "gap-confirm",
                          "gap_price": ev.get("gap_price"),
                          "attempts": ev.get("attempts")})
    finally:
        build_confirm_events.SCAN_FROM, build_confirm_events.SCAN_TO = 60, 180
    found.sort(key=lambda e: e["bar"])
    # 两类 10 根内重叠取较早者
    dedup = []
    for ev in found:
        if dedup and ev["bar"] - dedup[-1]["bar"] < 10:
            continue
        dedup.append(ev)
    return dedup


def mine(outdir):
    for sub in ("prompts-auto", "prompts-map", "charts", "maps",
                "judgments-auto", "judgments-camp", "prompts-arrival"):
        os.makedirs(os.path.join(outdir, sub), exist_ok=True)
    per_ds = {}
    for ds, s in iter_segments():
        seg = load_seg(ds, s["id"])
        evs = mine_segment(seg)
        if evs:
            ev = evs[0]  # 每段至多 1 个：取最早
            per_ds.setdefault(ds, []).append({
                "dataset": ds, "segment": s["id"], "symbol": s["symbol"],
                "interval": s.get("interval"), "bar": ev["bar"],
                "kind": ev["kind"], "decision_t": seg["bars"][ev["bar"] - 1]["t"],
            })
        print(f"mined {ds}/{s['id']}: {len(evs)} events", flush=True)
    # 数据集轮转取样至 TARGET_EVENTS
    picked, pools = [], {k: list(v) for k, v in per_ds.items()}
    order = [d for d in ("fresh", "fresh2", "fresh3") if pools.get(d)]
    while len(picked) < TARGET_EVENTS and any(pools.values()):
        for d in order:
            if pools.get(d) and len(picked) < TARGET_EVENTS:
                picked.append(pools[d].pop(0))
    for i, ev in enumerate(picked, 1):
        ev["eid"] = f"ev{i:02d}"
        ev["map_bar"] = ev["bar"] - MAP_LAG
    json.dump(picked, open(os.path.join(outdir, "events.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"total events picked: {len(picked)} "
          f"(yield per ds: {{ {', '.join(f'{k}: {len(v)}' for k, v in per_ds.items())} }})")
    if len(picked) < MIN_EVENTS:
        print(f"WARNING: below MIN_EVENTS={MIN_EVENTS}")
    # prep 提示与图
    for ev in picked:
        seg = load_seg(ev["dataset"], ev["segment"])
        eid = ev["eid"]
        packB, barsB = pack_at(seg, ev["bar"])
        packM, barsM = pack_at(seg, ev["map_bar"])
        open(os.path.join(outdir, "prompts-auto", eid + ".md"), "w").write(
            build_prompt(packB, barsB, segment=eid, symbol=ev["symbol"]))
        mp = build_map_prompt(packM, barsM)
        mp = mp.replace("第 90 根", f"第 {ev['map_bar']} 根")
        open(os.path.join(outdir, "prompts-map", eid + ".md"), "w").write(mp)
        render_bars(barsB, os.path.join(outdir, "charts", eid + "-B.png"))
        render_bars(barsM, os.path.join(outdir, "charts", eid + "-M.png"))
    print("prep done")


def arrival(outdir):
    events = json.load(open(os.path.join(outdir, "events.json")))
    made, missing = 0, []
    for ev in events:
        eid = ev["eid"]
        mp = os.path.join(outdir, "maps", eid + ".json")
        if not os.path.exists(mp):
            missing.append(eid)
            continue
        seg = load_seg(ev["dataset"], ev["segment"])
        packB, barsB = pack_at(seg, ev["bar"])
        map_obj = json.load(open(mp))
        ap = build_arrival_prompt(map_obj, packB, barsB)
        ap = ap.replace("第 90 根", f"第 {ev['map_bar']} 根")
        ap = ap.replace("第 180 根", f"第 {ev['bar']} 根")
        open(os.path.join(outdir, "prompts-arrival", eid + ".md"), "w").write(ap)
        made += 1
    print(f"arrival prompts: {made}, missing maps: {missing}")


def hybridprep(outdir):
    """第三臂提示 = AUTO 原提示 + 文末「战役备忘」（冻结地图 JSON + 三条使用规则）。"""
    events = json.load(open(os.path.join(outdir, "events.json")))
    os.makedirs(os.path.join(outdir, "prompts-hybrid"), exist_ok=True)
    made, missing = 0, []
    for ev in events:
        eid = ev["eid"]
        mp = os.path.join(outdir, "maps", eid + ".json")
        ap = os.path.join(outdir, "prompts-auto", eid + ".md")
        if not (os.path.exists(mp) and os.path.exists(ap)):
            missing.append(eid)
            continue
        map_obj = json.load(open(mp))
        memo = (
            "\n\n## 战役备忘（冻结地图附件，本事件开始前画定，不许重画、不许改点）\n\n"
            "下面是本事件的战役地图（决胜点、主/备假设及其 holds_if / takeover_if / void_if 条款）：\n\n"
            "```json\n" + json.dumps(map_obj, ensure_ascii=False, indent=1) + "\n```\n\n"
            "使用规则（硬纪律）：\n"
            "1. 每个候选必须在 candidate 中写 point_id，点名上面地图中的一个决胜点；"
            "决策根收盘价不在该点 [lo, hi] ±0.25×段均幅（附件数字中的段均幅）内时，"
            "该机会只许写进 pending_conditions，不许标 qualified。\n"
            "2. 地图假设的 void_if 或战役作废条件已经发生时（例如价格已越过地图标注的 "
            "MM 投影且该假设的顺势分支按其条款关闭、或趋势自起点腿的投影已达），"
            "对应方向的候选不许标 qualified。\n"
            "3. 地图只供位置与战役状态（决胜点在哪、本腿走到哪一步、哪条分支还活着）；"
            "形态、触发、成色仍以你对图的判读为准；位置与图读冲突时，位置以地图为准。\n")
        open(os.path.join(outdir, "prompts-hybrid", eid + ".md"), "w").write(
            open(ap).read() + memo)
        made += 1
    print(f"hybrid prompts: {made}, missing: {missing}")


def _classify_camp_action(j):
    if any(c.get("qualified") for c in j.get("candidates", [])):
        return "执行"
    blob = json.dumps(j.get("uncertainty") or "", ensure_ascii=False) + json.dumps(
        j.get("pending_conditions") or [], ensure_ascii=False)
    if "作废" in blob:
        return "地图作废"
    return "无点测试"


def run_arm(outdir, arm, events):
    jdir = os.path.join(outdir, f"judgments-{arm}")
    rep = {"arm": arm, "judged": 0, "format_errors": 0, "candidates": 0,
           "gate_reject": 0, "gate_reject_rules": {}, "unfilled": 0,
           "trades": [], "violations": 0, "actions": {},
           "per_event": {}}
    for ev in events:
        eid = ev["eid"]
        jp = os.path.join(jdir, eid + ".json")
        if not os.path.exists(jp):
            rep["per_event"][eid] = {"r": 0.0, "status": "missing"}
            continue
        rep["judged"] += 1
        seg = load_seg(ev["dataset"], ev["segment"])
        pack, _ = pack_at(seg, ev["bar"])
        try:
            j = json.load(open(jp))
        except Exception:
            rep["format_errors"] += 1
            rep["per_event"][eid] = {"r": 0.0, "status": "bad_json"}
            continue
        if validate_judgment(j):
            rep["format_errors"] += 1
            rep["per_event"][eid] = {"r": 0.0, "status": "format_error"}
            continue
        if arm == "camp":
            act = _classify_camp_action(j)
            rep["actions"][act] = rep["actions"].get(act, 0) + 1
        map_pts = {}
        if arm in ("camp", "hybrid"):
            mp = os.path.join(outdir, "maps", eid + ".json")
            if os.path.exists(mp):
                m = json.load(open(mp))
                map_pts = {p["id"]: p for p in m.get("points") or []}
        status, r_val = "no_trade", 0.0
        for c in j.get("candidates", []):
            if not c.get("qualified"):
                continue
            rep["candidates"] += 1
            plan = dict(c["plan"])
            plan.update({"side": c["side"], "setup": c["setup"],
                         "context": pack["trend"]["label"]})
            merge_candidate_terms(plan, c)
            if arm in ("camp", "hybrid"):
                pt = map_pts.get(c.get("point_id"))
                seg_avg = pack.get("seg_avg_range") or 0
                close = seg["bars"][ev["bar"] - 1]["c"]
                tested = pt and (pt["lo"] - 0.25 * seg_avg <= close
                                 <= pt["hi"] + 0.25 * seg_avg)
                if not tested:
                    rep["violations"] += 1
            verdict = adjudicate(plan, pack, bars_left=LIFECYCLE,
                                 feature_refs=c.get("feature_refs", []),
                                 flags=build_flags(plan, pack),
                                 ledger=None, mode="annotation")
            if verdict["verdict"] == "reject":
                rep["gate_reject"] += 1
                status = "gate_reject"
                for h in verdict["hard_hits"]:
                    rep["gate_reject_rules"][h["rule"]] = \
                        rep["gate_reject_rules"].get(h["rule"], 0) + 1
                continue
            future = seg["bars"][ev["bar"]:ev["bar"] + LIFECYCLE]
            t = simulate_plan(future, plan, c["side"], window=LIFECYCLE)
            if not t.get("filled", True):
                rep["unfilled"] += 1
                status = "unfilled"
                continue
            t.update({"event": eid, "setup": c["setup"], "side": c["side"],
                      "entry": plan["entry"]})
            rep["trades"].append(t)
            status, r_val = "resolved", t["r"]
        rep["per_event"][eid] = {"r": r_val, "status": status}
    rep["summary"] = summarize(rep["trades"])
    rep["per_opp_r"] = round(
        sum(v["r"] for v in rep["per_event"].values()) / max(len(events), 1), 4)
    return rep


def _paired(rep, events, arm_hi, arm_lo, seed):
    diffs = [rep[arm_hi]["per_event"][ev["eid"]]["r"]
             - rep[arm_lo]["per_event"][ev["eid"]]["r"] for ev in events]
    rng = random.Random(seed)
    n = len(diffs)
    boots = []
    for _ in range(10000):
        boots.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    boots.sort()
    return {
        "n": n, "mean_diff": round(sum(diffs) / n, 4),
        "ci95": [round(boots[250], 4), round(boots[9749], 4)],
        f"events_{arm_hi}_better": sum(1 for d in diffs if d > 0),
        f"events_{arm_lo}_better": sum(1 for d in diffs if d < 0),
        "events_tied": sum(1 for d in diffs if d == 0),
    }


def score(outdir):
    events = json.load(open(os.path.join(outdir, "events.json")))
    rep = {arm: run_arm(outdir, arm, events) for arm in ("auto", "camp", "hybrid")}
    # 配对差与 bootstrap CI（主指标：每机会 R）
    p = _paired(rep, events, "camp", "auto", 20261031)
    rep["paired"] = {
        "n": p["n"], "mean_diff_camp_minus_auto": p["mean_diff"],
        "ci95": p["ci95"],
        "events_camp_better": p["events_camp_better"],
        "events_auto_better": p["events_auto_better"],
        "events_tied": p["events_tied"],
    }
    rep["paired_hybrid"] = _paired(rep, events, "hybrid", "auto", 20261031)
    json.dump(rep, open(os.path.join(outdir, "result.json"), "w"),
              ensure_ascii=False, indent=1)
    for arm, r in rep.items():
        if isinstance(r, dict) and "summary" in r:
            s = r["summary"]
            print(f"{arm}: judged {r['judged']} fmt_err {r['format_errors']} "
                  f"cand {r['candidates']} gate_rej {r['gate_reject']} "
                  f"unfilled {r['unfilled']} trades {s['n']} "
                  f"meanR {s.get('mean_r')} per_opp_R {r['per_opp_r']} "
                  f"violations {r['violations']} actions {r['actions']}")
    print("paired:", json.dumps(rep["paired"], ensure_ascii=False))
    print("paired_hybrid:", json.dumps(rep["paired_hybrid"], ensure_ascii=False))


if __name__ == "__main__":
    cmd, outdir = sys.argv[1], sys.argv[2]
    {"mine": mine, "arrival": arrival, "score": score,
     "hybridprep": hybridprep}[cmd](outdir)
