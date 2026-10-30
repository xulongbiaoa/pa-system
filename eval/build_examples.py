"""阶段1：标注样本首批（机器草稿，状态 DRAFT，必须经用户复核才进金标准）。

每段取决策点 = 决策窗末根（bar 180），特征包只用决策点之前的数据；
地图锚 = 大级别摆动锚价。草稿结论规则（只作初筛，不是标注结论）：
趋势确定（上升/下降）且有敞开缺口 → candidate；其余 → no_trade。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from perception.features import build_feature_pack, load_config  # noqa: E402

DS = os.path.join(os.path.dirname(__file__), "datasets")
OUT = os.path.join(os.path.dirname(__file__), "..", "knowledge", "examples")
DECISION = 180  # 30 预热 + 150 决策窗


def main():
    cfg = load_config()
    stats = {"candidate": 0, "no_trade": 0}
    made = []
    for split in ("dev", "val"):
        d = os.path.join(DS, split)
        for name in sorted(os.listdir(d)):
            if not name.endswith(".json"):
                continue
            seg = json.load(open(os.path.join(d, name)))
            bars = seg["bars"][:DECISION]
            pack0 = build_feature_pack(bars, [], cfg)
            anchors = [
                {"price": s["anchor"], "source": "swing-major"}
                for s in pack0["swings"]["major"]
            ]
            pack = build_feature_pack(bars, anchors, cfg)
            trend = pack["trend"]["label"]
            open_gaps = len(pack["gaps"]["open"])
            verdict = (
                "candidate"
                if trend in ("上升", "下降") and open_gaps >= 1
                else "no_trade"
            )
            stats[verdict] += 1
            ex = {
                "id": f"ex-{seg['id']}",
                "segment": seg["id"],
                "split": split,
                "symbol": seg["symbol"],
                "interval": seg["interval"],
                "decision_bar": DECISION,
                "bars": seg["bars"][DECISION - 120 : DECISION],
                "features": pack,
                "annotation": {
                    "status": "DRAFT-待用户复核",
                    "context": trend,
                    "draft_verdict": verdict,
                    "setup": None,
                    "qualified": None,
                    "entry": None,
                    "stop": None,
                    "targets": None,
                    "note": "机器草稿：语境与敞开缺口数来自感知层；setup/成色/价位待人工标注",
                },
            }
            with open(os.path.join(OUT, f"ex-{seg['id']}.json"), "w") as f:
                json.dump(ex, f, ensure_ascii=False)
            made.append(ex["id"])
    print("examples:", len(made), stats)


if __name__ == "__main__":
    main()
