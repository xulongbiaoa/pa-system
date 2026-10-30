"""A 档粘贴式：把 core + router + 特征包 + 命中卡片 + 召回样本 + K 线表
拼成一段文本，供任何聊天 AI 返回判断 JSON。

路由（与 router.md 同口径的机器版）：趋势确定 → A1/A2 + B1；
震荡 → B3；其余只带 B3。每类至多 3 张卡。样本召回：同语境草稿优先，
candidate 与 no_trade 各至少 1 段。
"""

import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
KB = os.path.join(ROOT, "knowledge")


def _read(p):
    with open(p) as f:
        return f.read()


def route_cards(pack):
    trend = pack["trend"]["label"]
    if trend == "上升":
        return ["A1-m2b", "B1-trend-breakout", "B3-failed-breakout"]
    if trend == "下降":
        return ["A2-m2s", "B1-trend-breakout", "B3-failed-breakout"]
    return ["B3-failed-breakout"]


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
    cards = route_cards(pack)
    for c in cards:
        parts.append(_read(os.path.join(KB, "setups", c + ".md")))
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
