"""在 dev 集上跑两条基线，输出报告 JSON（阶段 4 验收物之一）。"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from baselines import random_baseline, simple_baseline  # noqa: E402
from replay import simulate_trade, summarize  # noqa: E402

DS = os.path.join(os.path.dirname(__file__), "datasets", "dev")
OUT = os.path.join(os.path.dirname(__file__), "reports", "baselines-dev-v0.1.json")


def load_segments():
    segs = []
    for name in sorted(os.listdir(DS)):
        if name.endswith(".json"):
            segs.append(json.load(open(os.path.join(DS, name))))
    return segs


def main():
    segs = load_segments()
    report = {"split": "dev", "segments": len(segs), "baselines": {}}
    for name, fn in (("simple", simple_baseline), ("random", random_baseline)):
        trades, trades_fee2 = [], []
        for seg in segs:
            for t in fn(seg):
                trades.append(t)
                r2 = simulate_trade(
                    seg["bars"][t["entry_bar"] + 1 :], t["side"],
                    t["entry"], t["stop"], t["target"], fee_mult=2.0,
                )
                if r2:
                    trades_fee2.append(r2)
        s = summarize(trades)
        s["fee_x2"] = summarize(trades_fee2)
        report["baselines"][name] = s
        print(name, s)
    with open(OUT, "w") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print("written:", OUT)


if __name__ == "__main__":
    main()
