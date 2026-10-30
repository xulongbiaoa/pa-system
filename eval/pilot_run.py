"""阶段 5 试点 runner：判断 JSON → 校验 → 裁决 → 回放 → 报告。

判断以决策点（bar 180）一次性给出：入场价按计划 entry 在第 180 根起
的未来段上回放，第一目标出场。裁决用 mode="annotation"（决策点即「当下」，
core 红线 4 定版口径），H4 截止不参与；回放窗口固定 300 根（生命周期口径）。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from gate.risk_rules import adjudicate  # noqa: E402
from judge.validate import validate_judgment  # noqa: E402
from perception.features import build_feature_pack, load_config  # noqa: E402
from replay import simulate_plan, summarize  # noqa: E402

DS = os.path.join(os.path.dirname(__file__), "datasets", "dev")
JD = os.path.join(os.path.dirname(__file__), "pilot", "judgments")
DECISION = 180
LIFECYCLE = 300  # core 生命周期口径：决策点后 300 根，到期按第 300 根收盘出场
LEDGER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "knowledge", "ledger", "mode_stats.json"
)


def load_ledger(path=LEDGER_PATH):
    """模式台账：落盘格式 {setup: {语境: {n, wins}}}，转成 (setup, 语境) 键。

    文件不存在时返回空台账——裁决结果里 H6 会显式标「未生效」，不静默跳过。
    """
    if not os.path.exists(path):
        return {}
    raw = json.load(open(path))
    out = {}
    for setup, by_ctx in raw.items():
        for ctx, st in by_ctx.items():
            out[(setup, ctx)] = {"n": st.get("n", 0), "wins": st.get("wins", 0)}
    return out


def load_segment(seg_id):
    path = os.path.join(DS, seg_id + ".json")
    return json.load(open(path)) if os.path.exists(path) else None


def run(judgments_dir=JD):
    cfg = load_config()
    ledger = load_ledger()
    report = {
        "judged": 0,
        "format_fail": 0,
        "no_trade": 0,
        "gate_reject": 0,
        "gate_reject_rules": {},
        "gate_notes": {},
        "h6_active": bool(ledger),
        "unfilled": 0,
        "unfilled_segments": [],
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
        # context 必须是语境枚举（上升/下降/震荡），取自感知层趋势标签；
        # 原先把假设 statement 的自由文本塞进来，H6 的 (setup, 语境) 台账键
        # 永远查不中，停牌规则等于没接线（2026-10-30 修正）。
        plan.update({"side": c["side"], "setup": c["setup"],
                     "context": pack["trend"]["label"]})
        verdict = adjudicate(
            plan, pack, bars_left=LIFECYCLE,
            feature_refs=c.get("feature_refs", []),
            ledger=ledger, mode="annotation",
        )
        for note in verdict.get("notes", []):
            report["gate_notes"][note] = report["gate_notes"].get(note, 0) + 1
        if verdict["verdict"] == "reject":
            report["gate_reject"] += 1
            for h in verdict["hard_hits"]:
                report["gate_reject_rules"][h["rule"]] = (
                    report["gate_reject_rules"].get(h["rule"], 0) + 1
                )
            continue
        # 生命周期锚在决策点：只取决策点后 300 根，到期按第 300 根收盘出场
        future = seg["bars"][DECISION:DECISION + LIFECYCLE]
        # 按计划的 order_type 分派：限价单必须穿越才成交、未成交留档
        t = simulate_plan(future, plan, c["side"], window=LIFECYCLE)
        if not t.get("filled", True):
            report["unfilled"] += 1
            report["unfilled_segments"].append(seg_id)
            continue
        t.update({"segment": seg_id, "setup": c["setup"],
                  "bars_after": len(future)})
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
