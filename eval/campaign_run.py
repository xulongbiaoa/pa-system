"""预演制 vs 自动线对比 runner（预注册 camp-vs-auto-prereg-2026-10-31）。

用法：
  prep    <outdir>            生成 20 段的 AUTO 提示、MAP 提示与两张图
  arrival <outdir>            读 maps/*.json 生成 ARRIVAL 提示
  score   <outdir>            两臂 judgment 齐后：validate→gate→回放，配对报告

目录形状（outdir）：
  segments.json               本轮 20 段清单
  prompts-auto/<seg>.md       AUTO 提示（决策根 180，标准 build_prompt）
  prompts-map/<seg>.md        CAMP 第一遍提示（bar 90）
  prompts-arrival/<seg>.md    CAMP 第二遍提示（bar 180 + 冻结地图）
  charts/<seg>-90.png / -180.png
  maps/<seg>.json             第一遍产出（冻结地图）
  judgments-auto/<seg>.json   AUTO 判读
  judgments-camp/<seg>.json   CAMP 第二遍判读
  result.json                 score 产出
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

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
DATASET = os.path.join(ROOT, "eval", "datasets", "fresh3")
DECISION = 180
MAP_AT = 90
LIFECYCLE = 300
SYMBOLS_USE = ["ICPUSDT", "DASHUSDT", "ZECUSDT", "NEOUSDT", "QTUMUSDT",
               "IOTAUSDT", "ENJUSDT", "SUSHIUSDT", "COMPUSDT", "YFIUSDT"]


def pick_segments():
    idx = json.load(open(os.path.join(DATASET, "INDEX.json")))
    all_segs = idx["splits"]["fresh"] if "splits" in idx else idx["segments"]
    segs = [s for s in all_segs if s["symbol"] in SYMBOLS_USE]
    return sorted(segs, key=lambda s: s["id"])


def load_seg(sid):
    return json.load(open(os.path.join(DATASET, sid + ".json")))


def prep(outdir):
    os.makedirs(outdir, exist_ok=True)
    for sub in ("prompts-auto", "prompts-map", "charts", "maps",
                "judgments-auto", "judgments-camp", "prompts-arrival"):
        os.makedirs(os.path.join(outdir, sub), exist_ok=True)
    segs = pick_segments()
    json.dump([s["id"] for s in segs],
              open(os.path.join(outdir, "segments.json"), "w"))
    for s in segs:
        seg = load_seg(s["id"])
        seg_meta = dict(seg, id=s["id"], symbol=s["symbol"])
        pack180, bars180 = pack_at(seg_meta, DECISION)
        pack90, bars90 = pack_at(seg_meta, MAP_AT)
        open(os.path.join(outdir, "prompts-auto", s["id"] + ".md"), "w").write(
            build_prompt(pack180, bars180, segment=s["id"], symbol=s["symbol"]))
        open(os.path.join(outdir, "prompts-map", s["id"] + ".md"), "w").write(
            build_map_prompt(pack90, bars90))
        render_bars(bars180, os.path.join(outdir, "charts", s["id"] + "-180.png"))
        render_bars(bars90, os.path.join(outdir, "charts", s["id"] + "-90.png"))
    print(f"prep done: {len(segs)} segments -> {outdir}")


def arrival(outdir):
    ids = json.load(open(os.path.join(outdir, "segments.json")))
    made, missing = 0, []
    for sid in ids:
        mp = os.path.join(outdir, "maps", sid + ".json")
        if not os.path.exists(mp):
            missing.append(sid)
            continue
        seg = load_seg(sid)
        seg_meta = dict(seg, id=sid, symbol=seg.get("symbol"))
        pack180, bars180 = pack_at(seg_meta, DECISION)
        map_obj = json.load(open(mp))
        open(os.path.join(outdir, "prompts-arrival", sid + ".md"), "w").write(
            build_arrival_prompt(map_obj, pack180, bars180))
        made += 1
    print(f"arrival prompts: {made}, missing maps: {missing}")


def validate_map(m):
    errs = []
    if not isinstance(m, dict):
        return ["地图必须是对象"]
    for k in ("context", "points", "branches"):
        if k not in m:
            errs.append(f"地图缺字段 {k}")
    ids = set()
    for p in m.get("points") or []:
        if not p.get("id") or p.get("lo") is None or p.get("hi") is None:
            errs.append("决胜点缺 id/lo/hi")
        ids.add(p.get("id"))
    for b in m.get("branches") or []:
        if b.get("point_id") not in ids:
            errs.append(f"分支引用不存在的点 {b.get('point_id')}")
    return errs


def run_arm(outdir, arm):
    ids = json.load(open(os.path.join(outdir, "segments.json")))
    jdir = os.path.join(outdir, f"judgments-{arm}")
    rep = {"arm": arm, "judged": 0, "format_errors": 0, "candidates": 0,
           "gate_reject": 0, "gate_reject_rules": {}, "unfilled": 0,
           "trades": [], "violations": 0}
    for sid in ids:
        jp = os.path.join(jdir, sid + ".json")
        if not os.path.exists(jp):
            continue
        rep["judged"] += 1
        seg = load_seg(sid)
        seg_meta = dict(seg, id=sid, symbol=seg.get("symbol"))
        pack, _bars = pack_at(seg_meta, DECISION)
        try:
            j = json.load(open(jp))
        except Exception:
            rep["format_errors"] += 1
            continue
        if validate_judgment(j):
            rep["format_errors"] += 1
            continue
        map_pts = {}
        if arm == "camp":
            mp = os.path.join(outdir, "maps", sid + ".json")
            if os.path.exists(mp):
                m = json.load(open(mp))
                map_pts = {p["id"]: p for p in m.get("points") or []}
        for c in j.get("candidates", []):
            if not c.get("qualified"):
                continue
            rep["candidates"] += 1
            plan = dict(c["plan"])
            # 与 pilot_run/event_run 同口径：adjudicate 从 plan 读 side/setup，
            # context 取感知层趋势标签（H6 台账键）；漏并会 KeyError（2026-10-31 计分时实测）。
            plan.update({"side": c["side"], "setup": c["setup"],
                         "context": pack["trend"]["label"]})
            merge_candidate_terms(plan, c)
            if arm == "camp":
                pid = c.get("point_id")
                pt = map_pts.get(pid)
                seg_avg = pack.get("seg_avg_range") or 0
                close = seg["bars"][DECISION - 1]["c"]
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
                for h in verdict["hard_hits"]:
                    rep["gate_reject_rules"][h["rule"]] = \
                        rep["gate_reject_rules"].get(h["rule"], 0) + 1
                continue
            future = seg["bars"][DECISION:DECISION + LIFECYCLE]
            t = simulate_plan(future, plan, c["side"], window=LIFECYCLE)
            if not t.get("filled", True):
                rep["unfilled"] += 1
                continue
            t.update({"segment": sid, "setup": c["setup"], "side": c["side"],
                      "entry": plan["entry"]})
            rep["trades"].append(t)
    rep["summary"] = summarize(rep["trades"])
    return rep


def score(outdir):
    rep = {arm: run_arm(outdir, arm) for arm in ("auto", "camp")}
    json.dump(rep, open(os.path.join(outdir, "result.json"), "w"),
              ensure_ascii=False, indent=1)
    for arm, r in rep.items():
        s = r["summary"]
        print(f"{arm}: judged {r['judged']} fmt_err {r['format_errors']} "
              f"cand {r['candidates']} gate_rej {r['gate_reject']} "
              f"unfilled {r['unfilled']} trades {s['n']} "
              f"meanR {s.get('mean_r')} violations {r['violations']}")


if __name__ == "__main__":
    cmd, outdir = sys.argv[1], sys.argv[2]
    {"prep": prep, "arrival": arrival, "score": score}[cmd](outdir)
