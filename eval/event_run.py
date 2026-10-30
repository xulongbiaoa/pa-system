"""消融 v0.2 事件 runner：事件判断 → 校验 → 裁决 → 回放 → 维度分层。

与 pilot_run 的区别：决策点是事件根（非固定 180），生命周期为事件后
300 根；分层按维度机械近似（L1 账本维 / L2 +位置维 / L3 = G1 申报）。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from gate.risk_rules import adjudicate  # noqa: E402
from gate.flags import build_flags  # noqa: E402
from judge.validate import validate_judgment  # noqa: E402
from perception.features import load_config  # noqa: E402
from replay import simulate_plan, summarize  # noqa: E402
from build_events import pack_at  # noqa: E402
from pilot_run import load_ledger  # noqa: E402

ROOT = os.path.dirname(__file__)
EV = os.path.join(ROOT, "ablation-events")
DS = os.path.join(ROOT, "datasets", "fresh")
LIFECYCLE = 300
TOL_MULT = 0.25


def layer_of(trade, pack):
    """维度分层（机械近似，口径同 g1-ablation-v0.1 报告）。"""
    side = trade["side"]
    tol = TOL_MULT * pack["seg_avg_range"]
    aligned = [g for g in pack["gaps"]["open"]
               if (side == "long" and g["trapped"] == "short")
               or (side == "short" and g["trapped"] == "long")]
    if not aligned:
        return 0
    entry = trade["entry"]
    near = [g for g in aligned if abs(entry - g["price"]) <= tol]
    if not near:
        return 1
    g0 = near[0]
    second = False
    for m in pack.get("mm", {}).get("candidates", []):
        if abs(m.get("target", 1e18) - entry) <= tol:
            second = True
    for b in pack["fortress"]["bands"]:
        if b["lo"] - tol <= entry <= b["hi"] + tol:
            second = True
    for s in pack["swings"]["major"]:
        # 与缺口锚同址的摆动点是同源（缺口多由它打开），不算第二锚
        if abs(s["anchor"] - entry) <= tol and abs(s["anchor"] - g0["price"]) > tol:
            second = True
    if not second:
        return 1
    return 3 if trade["setup"] == "G1" else 2


def run(judgments_dir=None, ev_dir=None):
    cfg = load_config()
    ledger = load_ledger()
    ev_dir = ev_dir or EV
    manifest = json.load(open(os.path.join(ev_dir, "events.json")))
    jd = judgments_dir or os.path.join(ev_dir, "judgments")
    rep = {"events": len(manifest), "judged": 0, "format_fail": 0,
           "with_candidate": 0, "qualified": 0, "no_trade": 0,
           "gate_reject": 0, "gate_reject_rules": {}, "unfilled": 0,
           "structured_pending": 0, "trades": []}
    for ev in manifest:
        eid = ev["event"]
        path = os.path.join(jd, eid + ".json")
        if not os.path.exists(path):
            continue
        rep["judged"] += 1
        j = json.load(open(path))
        if validate_judgment(j):
            rep["format_fail"] += 1
            continue
        pcs = j.get("pending_conditions") or []
        if pcs and all(isinstance(x, dict) for x in pcs):
            rep["structured_pending"] += 1
        cands = [c for c in j.get("candidates", []) if isinstance(c, dict)]
        if cands:
            rep["with_candidate"] += 1
        qual = [c for c in cands if c.get("qualified")]
        if not qual:
            rep["no_trade"] += 1
            continue
        rep["qualified"] += 1
        c = qual[0]
        seg = json.load(open(os.path.join(DS, ev["segment"] + ".json")))
        bar = ev["bar"]  # 1-based 决策根
        pack = pack_at(seg["bars"][:bar], cfg)
        plan = dict(c["plan"])
        plan.update({"side": c["side"], "setup": c["setup"],
                     "context": pack["trend"]["label"]})
        verdict = adjudicate(plan, pack, bars_left=LIFECYCLE,
                             feature_refs=c.get("feature_refs", []),
                             flags=build_flags(plan, pack),
                             ledger=ledger, mode="annotation")
        if verdict["verdict"] == "reject":
            rep["gate_reject"] += 1
            for h in verdict["hard_hits"]:
                rep["gate_reject_rules"][h["rule"]] = \
                    rep["gate_reject_rules"].get(h["rule"], 0) + 1
            continue
        future = seg["bars"][bar:bar + LIFECYCLE]
        t = simulate_plan(future, plan, c["side"], window=LIFECYCLE)
        if not t.get("filled", True):
            rep["unfilled"] += 1
            continue
        t.update({"event": eid, "segment": ev["segment"], "bar": bar,
                  "setup": c["setup"], "side": c["side"],
                  "entry": plan["entry"]})
        t["layer"] = layer_of(t, pack)
        rep["trades"].append(t)
    layers = {}
    for lv in (0, 1, 2, 3):
        sub = rep["trades"] if lv == 0 else \
            [t for t in rep["trades"] if t["layer"] >= lv]
        layers[f"L{lv}"] = summarize(sub)
    rep["layers"] = layers
    rep["summary"] = summarize(rep["trades"])
    return rep


def main():
    ev_dir = sys.argv[1] if len(sys.argv) > 1 else None
    rep = run(ev_dir=ev_dir)
    name = sys.argv[2] if len(sys.argv) > 2 else "ablation-events-v0.2.json"
    out = os.path.join(ROOT, "reports", name)
    with open(out, "w") as f:
        json.dump(rep, f, indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in rep.items() if k != "trades"},
                     ensure_ascii=False)[:1200])
    print("trades:", len(rep["trades"]), "written:", out)


if __name__ == "__main__":
    main()
