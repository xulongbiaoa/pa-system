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

from judge.service import DecisionRequest, assess_candidate  # noqa: E402
from gate.flags import build_flags  # noqa: E402
from judge.prompt_builder import build_prompt  # noqa: E402
from judge.validate import validate_judgment  # noqa: E402
from perception.features import build_feature_pack, load_config  # noqa: E402
import ledger as ledger_store  # noqa: E402
from ledger import gate_view  # noqa: E402

CFG = load_config()
DECISION = 180
LEDGER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "knowledge", "ledger", "mode_stats.json"
)


def load_ledger(path=LEDGER_PATH):
    """台账视图：文件不存在时返回空台账，H6 会在 notes 里显式写「无该格样本」，
    不再静默跳过（2026-10-30 复核：传 {} 看起来像接好了，实际 H6 从未生效）。"""
    return gate_view(ledger_store.load(path))


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
        decision = int(sys.argv[3]) if len(sys.argv) > 3 else DECISION
        pack, bars = pack_at(seg, decision)
        if cmd == "features":
            print(json.dumps(pack, ensure_ascii=False, indent=1))
        else:
            # 传 segment/symbol：召回要能排除当前样本与同标的重叠窗口，
            # 否则提示里会出现自己的草稿答案（2026-10-30 复核）。
            print(build_prompt(pack, bars, segment=seg.get("id"),
                               symbol=seg.get("symbol")))
    elif cmd == "gate":
        j = json.load(open(sys.argv[2]))
        seg = json.load(open(sys.argv[3]))
        decision = int(sys.argv[4]) if len(sys.argv) > 4 else DECISION
        errs = validate_judgment(j)
        if errs:
            print(json.dumps({"format_errors": errs}, ensure_ascii=False))
            return
        cands = [c for c in j.get("candidates", []) if c.get("qualified")]
        if not cands:
            print(json.dumps({"verdict": "no_trade"}, ensure_ascii=False))
            return
        c = cands[0]
        pack, bars = pack_at(seg, decision)
        plan = dict(c["plan"])
        # 条件矩阵透传（契约 v2）：H7 要看到 candidate 的 conditions 与
        # 最强反证，只传 plan 本体则 G1 恒因「缺矩阵」被拒、规则假死。
        plan.update({"conditions": c.get("conditions"),
                     "strongest_countercase": c.get("strongest_countercase")})
        # context 取自感知层趋势标签：H6 的台账键是 (setup, 语境枚举)，
        # 不传 context 则 H6 恒不生效（原实现漏了这一步，2026-10-30 复核）。
        plan.update({"side": c["side"], "setup": c["setup"],
                     "context": pack["trend"]["label"]})
        verdict = assess_candidate(DecisionRequest(
            snapshot_id=seg.get("id", ""), candidate={"plan": plan},
            feature_pack=pack, bars_left=len(seg["bars"]) - decision,
            feature_refs=tuple(c.get("feature_refs", [])),
            flags=build_flags(plan, pack),
            ledger=load_ledger())).gate
        print(json.dumps(verdict, ensure_ascii=False, indent=1))
    else:
        print("unknown command:", cmd)
        sys.exit(2)


if __name__ == "__main__":
    main()
