"""阶段 5 试点：为 dev 集前 10 段生成决策点判断提示（粘贴式）。

决策点 = 第 180 根收盘后（30 预热 + 150 决策窗），与标注样本同口径。
判断者（任何 AI）把判断 JSON 存回 eval/pilot/judgments/<segment>.json，
再跑 eval/pilot_run.py 完成校验 → 裁决 → 回放 → 报告。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from judge.prompt_builder import build_prompt  # noqa: E402
from perception.features import build_feature_pack, load_config  # noqa: E402

DS = os.path.join(os.path.dirname(__file__), "datasets", "dev")
OUT = os.path.join(os.path.dirname(__file__), "pilot", "prompts")
DECISION = 180
N = 10


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), "pilot", "judgments"), exist_ok=True)
    cfg = load_config()
    names = sorted(n for n in os.listdir(DS) if n.endswith(".json"))[:N]
    for name in names:
        seg = json.load(open(os.path.join(DS, name)))
        bars = seg["bars"][:DECISION]
        pack0 = build_feature_pack(bars, [], cfg)
        anchors = [
            {"price": s["anchor"], "source": "swing-major"}
            for s in pack0["swings"]["major"]
        ]
        pack = build_feature_pack(bars, anchors, cfg)
        text = build_prompt(pack, bars)
        with open(os.path.join(OUT, seg["id"] + ".md"), "w") as f:
            f.write(text)
        print("prompt:", seg["id"], len(text), "chars")
    print("total:", len(names))


if __name__ == "__main__":
    main()
