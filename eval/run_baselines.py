"""在 dev 集上跑两条基线，输出报告 JSON（阶段 4 验收物之一）。

2026-10-30 修：入场窗收到决策点（180）、结局窗固定 300 根、加漏斗计数，
并给出 min_attempts=1 的放宽档作敏感性对照（A1 的两腿结构允许「更高的
第二腿低点」，而 attempts 计数器要求先做出**新低**才计第二次尝试，两者
不是一回事——原基线只触发 2/31 段，原因就在这一环）。

2026-10-30 晚 v0.2：简单基线的计量已按上段诊断换成结构腿数
（count_pullback_legs），min_attempts 现语义 = 腿数下限；本报告取代
baselines-dev-v0.1.json（v0.1 的 simple n=2 是错计量下的产物，只作存档）。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from baselines import (  # noqa: E402
    DECISION, LIFECYCLE, funnel_stats, random_baseline, simple_baseline,
)
from replay import simulate_trade, summarize  # noqa: E402

DS = os.path.join(os.path.dirname(__file__), "datasets", "dev")
OUT = os.path.join(os.path.dirname(__file__), "reports", "baselines-dev-v0.2.json")


def load_segments():
    segs = []
    for name in sorted(os.listdir(DS)):
        if name.endswith(".json"):
            segs.append(json.load(open(os.path.join(DS, name))))
    return segs


def _run(segs, fn, **kw):
    trades, trades_fee2 = [], []
    for seg in segs:
        for t in fn(seg, **kw):
            trades.append(t)
            r2 = simulate_trade(
                seg["bars"][t["entry_bar"] + 1 : t["entry_bar"] + 1 + LIFECYCLE],
                t["side"], t["entry"], t["stop"], t["target"], fee_mult=2.0,
            )
            if r2:
                trades_fee2.append(r2)
    s = summarize(trades)
    s["fee_x2"] = summarize(trades_fee2)
    return s


def main():
    segs = load_segments()
    report = {"split": "dev", "segments": len(segs),
              "protocol": {"entry_window": [30, DECISION], "lifecycle_bars": LIFECYCLE},
              "baselines": {}}
    variants = (
        ("simple", simple_baseline, {"min_attempts": 2}),
        ("simple_loose", simple_baseline, {"min_attempts": 1}),
        ("random", random_baseline, {}),
    )
    for name, fn, kw in variants:
        s = _run(segs, fn, **kw)
        if name.startswith("simple"):
            s["funnel"] = funnel_stats(segs, min_attempts=kw["min_attempts"])
        report["baselines"][name] = s
        print(name, s)
    with open(OUT, "w") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print("written:", OUT)


if __name__ == "__main__":
    main()
