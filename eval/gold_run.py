"""金标准判断层打分：判断 JSON → 校验 → 裁决 → 回放 → 与冻结标注对账。

两轴分开记（core 判单双轴）：
- **一致性轴**（逻辑与纪律）：结论（candidate / no_trade）、空仓理由、setup、
  方向是否与冻结标注一致；
- **盈亏轴**：AI 自己的计划过裁决后按 300 根生命周期回放得到的 R。

两轴不许互相折算：判断一致但亏钱是正常的（n 小、方差大），判断不一致却
赚钱更要在报告里单独点出来——那是运气，不是本事。

用法：判断存 eval/gold/judgments/<segment>.json，然后跑本脚本。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gate.risk_rules import adjudicate  # noqa: E402
from gold_build import DECISION, bars_of, gold_segments, pack_at_decision  # noqa: E402
from judge.validate import validate_judgment  # noqa: E402
from perception.features import load_config  # noqa: E402
from replay import simulate_plan, summarize  # noqa: E402

LIFECYCLE = 300
JD = os.path.join(os.path.dirname(__file__), "gold", "judgments")
OUT = os.path.join(os.path.dirname(__file__), "reports", "gold-judgment-v0.1.json")


def _ai_verdict(j):
    cands = [c for c in j.get("candidates", []) if c.get("qualified")]
    return "candidate" if cands else "no_trade", cands


def score(judgments_dir=JD, gold=None, cfg=None):
    """返回报告 dict。judgments_dir 里没有对应段的判断就计入未判，不算失败。"""
    cfg = cfg or load_config()
    gold = gold or gold_segments()
    rep = {
        "n_gold": len(gold), "n_judged": 0, "format_fail": 0,
        "verdict_agree": 0, "reason_agree": 0, "reason_compared": 0,
        "setup_agree": 0, "setup_compared": 0, "side_agree": 0,
        "gate_reject": 0, "gate_reject_rules": {}, "gate_notes": {},
        "unfilled": 0, "unfilled_segments": [],
        "trades": [], "mismatches": [],
    }
    for g in gold:
        path = os.path.join(judgments_dir, g["segment"] + ".json")
        if not os.path.exists(path):
            continue
        j = json.load(open(path))
        errs = validate_judgment(j)
        if errs:
            rep["format_fail"] += 1
            rep["mismatches"].append({"segment": g["segment"], "kind": "format",
                                      "detail": errs})
            continue
        rep["n_judged"] += 1
        ai_v, cands = _ai_verdict(j)
        if ai_v == g["verdict"]:
            rep["verdict_agree"] += 1
        else:
            rep["mismatches"].append({
                "segment": g["segment"], "kind": "verdict",
                "gold": f"{g['verdict']}/{g['no_trade_reason'] or g['setup']}",
                "ai": f"{ai_v}/{cands[0]['setup'] if cands else j.get('no_trade_reason')}",
            })
        if ai_v == "no_trade" and g["verdict"] == "no_trade":
            rep["reason_compared"] += 1
            if j.get("no_trade_reason") == g["no_trade_reason"]:
                rep["reason_agree"] += 1
        if ai_v != "candidate":
            continue
        c = cands[0]
        if g["verdict"] == "candidate":
            rep["setup_compared"] += 1
            if c["setup"] == g["setup"]:
                rep["setup_agree"] += 1
            if c["side"] == g["side"]:
                rep["side_agree"] += 1
        bars = bars_of(g["segment"])
        pack = pack_at_decision(bars, cfg)
        plan = dict(c["plan"])
        plan.update({"side": c["side"], "setup": c["setup"],
                     "context": pack["trend"]["label"]})
        v = adjudicate(plan, pack, bars_left=LIFECYCLE,
                       feature_refs=c.get("feature_refs", []), mode="annotation")
        for note in v.get("notes", []):
            rep["gate_notes"][note] = rep["gate_notes"].get(note, 0) + 1
        if v["verdict"] == "reject":
            rep["gate_reject"] += 1
            for h in v["hard_hits"]:
                rep["gate_reject_rules"][h["rule"]] = (
                    rep["gate_reject_rules"].get(h["rule"], 0) + 1)
            continue
        t = simulate_plan(bars[DECISION:DECISION + LIFECYCLE], plan, c["side"],
                          window=LIFECYCLE)
        if not t.get("filled", True):
            # 限价未成交必须留档：未成交率本身就是样本选择偏差的度量
            rep["unfilled"] += 1
            rep["unfilled_segments"].append(g["segment"])
            continue
        t.update({"segment": g["segment"], "setup": c["setup"]})
        rep["trades"].append(t)
    rep["verdict_agree_rate"] = (
        round(rep["verdict_agree"] / rep["n_judged"], 4) if rep["n_judged"] else None)
    rep["reason_agree_rate"] = (
        round(rep["reason_agree"] / rep["reason_compared"], 4)
        if rep["reason_compared"] else None)
    rep["summary"] = summarize(rep["trades"])
    rep["no_trade_rate_ai"] = (
        round(1 - len(rep["trades"]) / rep["n_judged"], 4) if rep["n_judged"] else None)
    return rep


def main():
    rep = score()
    with open(OUT, "w") as f:
        json.dump(rep, f, indent=1, ensure_ascii=False)
    print(json.dumps({k: rep[k] for k in
                      ("n_gold", "n_judged", "verdict_agree", "verdict_agree_rate",
                       "reason_agree_rate", "setup_agree", "side_agree",
                       "gate_reject", "gate_reject_rules")},
                     ensure_ascii=False))
    print("written:", OUT)


if __name__ == "__main__":
    main()
