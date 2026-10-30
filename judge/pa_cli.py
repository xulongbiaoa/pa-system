"""工具式接入（阶段 6 入口）：把管线能力做成 CLI，供任何 agent/脚本调用。

子命令：
  features <segment.json> [decision_bar]   输出特征包 JSON
  prompt   <segment.json> [decision_bar]   输出判断提示（粘贴式同款）
  gate     <judgment.json> <segment.json>  对判断的首个合格候选跑裁决，输出结论
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "eval"))

from gate.risk_rules import adjudicate  # noqa: E402
from gate.flags import build_flags  # noqa: E402
from judge.prompt_builder import build_prompt  # noqa: E402
from judge.validate import validate_judgment  # noqa: E402
from perception.features import build_feature_pack, load_config  # noqa: E402

CFG = load_config()


def pack_at(seg, decision):
    bars = seg["bars"][:decision]
    pack0 = build_feature_pack(bars, [], CFG)
    anchors = [
        {"price": s["anchor"], "source": "swing-major"}
        for s in pack0["swings"]["major"]
    ]
    return build_feature_pack(bars, anchors, CFG), bars


def main():
    cmd = sys.argv[1]
    if cmd in ("features", "prompt"):
        seg = json.load(open(sys.argv[2]))
        decision = int(sys.argv[3]) if len(sys.argv) > 3 else 180
        pack, bars = pack_at(seg, decision)
        if cmd == "features":
            print(json.dumps(pack, ensure_ascii=False, indent=1))
        else:
            print(build_prompt(pack, bars))
    elif cmd == "gate":
        j = json.load(open(sys.argv[2]))
        seg = json.load(open(sys.argv[3]))
        errs = validate_judgment(j)
        if errs:
            print(json.dumps({"format_errors": errs}, ensure_ascii=False))
            return
        cands = [c for c in j.get("candidates", []) if c.get("qualified")]
        if not cands:
            print(json.dumps({"verdict": "no_trade"}, ensure_ascii=False))
            return
        c = cands[0]
        pack, bars = pack_at(seg, 180)
        plan = dict(c["plan"])
        plan.update({"side": c["side"], "setup": c["setup"]})
        verdict = adjudicate(
            plan, pack, bars_left=len(seg["bars"]) - 180,
            feature_refs=c.get("feature_refs", []),
            flags=build_flags(plan, pack),
        )
        print(json.dumps(verdict, ensure_ascii=False, indent=1))
    else:
        print("unknown command:", cmd)
        sys.exit(2)


if __name__ == "__main__":
    main()
