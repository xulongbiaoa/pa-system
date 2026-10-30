"""阶段 5 试点 runner：判断 JSON → 校验 → 裁决 → 回放 → 报告。

判断以决策点（bar 180）一次性给出：入场价按计划 entry 在第 180 根起
的未来段上回放，第一目标出场。bars_left 按未来窗 300 根计，H4 截止在
本试点不触发（试点只验管线与单点判断，不验窗内择时）。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from gate.risk_rules import adjudicate  # noqa: E402
from judge.validate import validate_judgment  # noqa: E402
from perception.features import build_feature_pack, load_config  # noqa: E402
from replay import simulate_trade, summarize  # noqa: E402

DS = os.path.join(os.path.dirname(__file__), "datasets", "dev")
JD = os.path.join(os.path.dirname(__file__), "pilot", "judgments")
DECISION = 180


def load_segment(seg_id):
    path = os.path.join(DS, seg_id + ".json")
    return json.load(open(path)) if os.path.exists(path) else None


def run(judgments_dir=JD):
    cfg = load_config()
    report = {
        "judged": 0,
        "format_fail": 0,
        "no_trade": 0,
        "gate_reject": 0,
        "gate_reject_rules": {},
        "trades": [],
    }
    if not os.path.isdir(judgments_dir):
        return report
    for name in sorted(os.listdir(judgments_dir)):
        if not name.endswith(".json"):
            continue
        seg_id = name[:-5]
        seg = load_segment(seg_id)
        if seg is None:
            continue
        report["judged"] += 1
        j = json.load(open(os.path.join(judgments_dir, name)))
        errs = validate_judgment(j)
        if errs:
            report["format_fail"] += 1
            continue
        cands = [c for c in j.get("candidates", []) if c.get("qualified")]
        if not cands:
            report["no_trade"] += 1
            continue
        c = cands[0]
        bars = seg["bars"][:DECISION]
        pack0 = build_feature_pack(bars, [], cfg)
        anchors = [
            {"price": s["anchor"], "source": "swing-major"}
            for s in pack0["swings"]["major"]
        ]
        pack = build_feature_pack(bars, anchors, cfg)
        plan = dict(c["plan"])
        plan.update({"side": c["side"], "setup": c["setup"],
                     "context": (j["hypotheses"][0]["statement"] if j["hypotheses"] else "")})
        verdict = adjudicate(
            plan, pack, bars_left=len(seg["bars"]) - DECISION,
            feature_refs=c.get("feature_refs", []),
        )
        if verdict["verdict"] == "reject":
            report["gate_reject"] += 1
            for h in verdict["hard_hits"]:
                report["gate_reject_rules"][h["rule"]] = (
                    report["gate_reject_rules"].get(h["rule"], 0) + 1
                )
            continue
        t = simulate_trade(
            seg["bars"][DECISION:], c["side"], plan["entry"], plan["stop"],
            plan["targets"][0],
        )
        if t:
            t.update({"segment": seg_id, "setup": c["setup"]})
            report["trades"].append(t)
    report["summary"] = summarize(report["trades"])
    report["no_trade_rate"] = (
        round(report["no_trade"] / report["judged"], 4) if report["judged"] else None
    )
    return report


def main():
    report = run()
    out = os.path.join(
        os.path.dirname(__file__), "reports", "pilot-dev10-v0.1.json"
    )
    with open(out, "w") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print(json.dumps(report, ensure_ascii=False)[:800])
    print("written:", out)


if __name__ == "__main__":
    main()
