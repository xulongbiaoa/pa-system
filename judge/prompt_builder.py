"""A 档粘贴式：把 core + router + 特征包 + 命中卡片 + 召回样本 + K 线表
拼成一段文本，供任何聊天 AI 返回判断 JSON。

路由（与 router.md 四类语境对齐的机器版，2026-10-30 重写）：
趋势确定 → 顺势卡 + B1 突破事件 + B2 突破回踩；
趋势失势（账本与标签冲突 / 标签置信边界）→ C1 反转卡升权 + B3 + 顺势卡；
震荡 → B3 翻面 + C1（区间边缘反转与突破失败共用同一套证据）；
其余 → 只带 B3。每类至多 3 张卡。

router.md 里还有两条条件**感知层没有对应字段**，不能硬凑成路由条件：
「MM 已达（趋势成熟）」无 MM 投影字段；「两腿衰竭 / 腿数足」的
trend_age.legs 恒为 1（主级别摆动交替，同向腿不可能相邻，见 2026-10-30
复核），故腿数与 MM 一律留给判断层自己认定，路由不代判。
"""

import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
KB = os.path.join(ROOT, "knowledge")

TREND_CARD = {"上升": "A1-m2b", "下降": "A2-m2s"}


def _read(p):
    with open(p) as f:
        return f.read()


def route_cards(pack):
    """返回 (卡片文件名列表, 路由依据)。依据进提示，便于事后追责与改规。"""
    trend = pack["trend"]
    label, conf = trend["label"], trend["confidence"]
    verdict = (trend.get("gap_consistency") or {}).get("verdict")
    reasons = [f"trend={label}/{conf}", f"账本一致性={verdict}"]
    if label not in TREND_CARD:
        # 震荡 / 未定：突破默认假，先审失败面；区间边缘反转同审
        return ["B3-failed-breakout", "C1-mtr"], reasons
    follow = TREND_CARD[label]
    if verdict == "冲突" or conf == "边界":
        # 标签可能过期：MTR 升权，同时保留翻面与顺势（接管条件在判断层写）
        reasons.append("标签与账本冲突/置信边界 → 反转候选")
        return ["C1-mtr", "B3-failed-breakout", follow], reasons
    reasons.append("趋势确定且账本同向 → 顺势菜单")
    return [follow, "B1-trend-breakout", "B2-breakout-pullback"], reasons


def recall_examples(pack, k=3):
    exdir = os.path.join(KB, "examples")
    pool = []
    if os.path.isdir(exdir):
        for name in sorted(os.listdir(exdir)):
            if name.endswith(".json"):
                pool.append(json.load(open(os.path.join(exdir, name))))
    trend = pack["trend"]["label"]
    same = [e for e in pool if e["annotation"]["context"] == trend]
    rest = [e for e in pool if e["annotation"]["context"] != trend]
    picked = []
    for e in same + rest:
        v = e["annotation"]["draft_verdict"]
        if v == "no_trade" and not any(
            p["annotation"]["draft_verdict"] == "no_trade" for p in picked
        ):
            picked.append(e)
        elif v == "candidate" and not any(
            p["annotation"]["draft_verdict"] == "candidate" for p in picked
        ):
            picked.append(e)
        if len(picked) >= k:
            break
    return picked[:k]


def bars_table(bars):
    lines = ["idx,o,h,l,c"]
    for i, b in enumerate(bars):
        lines.append(f"{i},{b['o']},{b['h']},{b['l']},{b['c']}")
    return "\n".join(lines)


def build_prompt(pack, bars, prev_hypotheses=None):
    parts = []
    parts.append(_read(os.path.join(KB, "core.md")))
    parts.append(_read(os.path.join(KB, "router.md")))
    cards, reasons = route_cards(pack)
    for c in cards:
        parts.append(_read(os.path.join(KB, "setups", c + ".md")))
    parts.append("## 本次路由依据（机器按特征包判定，卡已按此装载）\n"
                 + "；".join(reasons)
                 + "\n卡内门槛（三件套、MM、腿数）感知层未算，须你自行认定；"
                   "认定不了就写进 uncertainty 并空仓。")
    parts.append("## 特征包（感知层输出，只许引用其中的字段）\n```json\n"
                 + json.dumps(pack, ensure_ascii=False) + "\n```")
    exs = recall_examples(pack)
    if exs:
        brief = [
            {
                "id": e["id"],
                "context": e["annotation"]["context"],
                "draft_verdict": e["annotation"]["draft_verdict"],
                "trend": e["features"]["trend"],
                "open_gaps": len(e["features"]["gaps"]["open"]),
            }
            for e in exs
        ]
        parts.append("## 参考样本（草稿标注，只作语境类比）\n```json\n"
                     + json.dumps(brief, ensure_ascii=False) + "\n```")
    if prev_hypotheses:
        parts.append("## 上一根假设账本\n```json\n"
                     + json.dumps(prev_hypotheses, ensure_ascii=False) + "\n```")
    parts.append("## 最近 K 线（OHLC 数值表）\n```\n" + bars_table(bars[-120:]) + "\n```")
    parts.append(
        "## 任务\n按 judge/schema.json 输出判断 JSON（只输出 JSON，不要解释文字）。"
        "假设用主/备 + 接管条件，不许给数字权重。无合格候选时 candidates 为空数组、"
        "no_trade_reason 必填枚举。空仓是合法输出。"
    )
    return "\n\n".join(parts)
