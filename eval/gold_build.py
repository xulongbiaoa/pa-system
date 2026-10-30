"""金标准判断层重跑：给 30 段冻结集出决策点提示（粘贴式）。

INDEX.md 的纪律是「任何知识/提示/感知改动须全量重跑本集，通过率不得下降」。
确定性回归（test_gold_regression.py）只能锁住裁决与回放，锁不住 no_trade
判断——28/30 段是空仓，那部分只有重跑判断层才能验。

产出 eval/gold/prompts/<segment>.md，把判断 JSON 存回
eval/gold/judgments/<segment>.json，再跑 eval/gold_run.py 打分。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from judge.prompt_builder import build_prompt  # noqa: E402
from perception.features import build_feature_pack, load_config  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
GOLD = os.path.join(ROOT, "knowledge", "gold")
OUT = os.path.join(os.path.dirname(__file__), "gold", "prompts")
SPLITS = ("dev", "val", "test")
DECISION = 180


def gold_segments():
    out = []
    for name in sorted(os.listdir(GOLD)):
        if name.endswith(".json"):
            out.append(json.load(open(os.path.join(GOLD, name))))
    return out


def bars_of(seg_id):
    for split in SPLITS:
        p = os.path.join(ROOT, "eval", "datasets", split, seg_id + ".json")
        if os.path.exists(p):
            return json.load(open(p))["bars"]
    return None


def pack_at_decision(bars, cfg):
    """与 pilot_run / 试点同构：先取大级别摆动当锚，再重建特征包。"""
    bars = bars[:DECISION]
    p0 = build_feature_pack(bars, [], cfg)
    anchors = [{"price": s["anchor"], "source": "swing-major"}
               for s in p0["swings"]["major"]]
    return build_feature_pack(bars, anchors, cfg)


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), "gold", "judgments"),
                exist_ok=True)
    cfg = load_config()
    n = 0
    for g in gold_segments():
        bars = bars_of(g["segment"])
        if bars is None:
            print("缺 K 线，跳过:", g["segment"])
            continue
        text = build_prompt(pack_at_decision(bars, cfg), bars[:DECISION])
        with open(os.path.join(OUT, g["segment"] + ".md"), "w") as f:
            f.write(text)
        n += 1
        print("prompt:", g["segment"], len(text), "chars")
    print("total:", n)


if __name__ == "__main__":
    main()
