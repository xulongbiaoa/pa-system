"""生成跨 AI 盲审包：每段一个 md，可直接粘贴给任何聊天 AI。

盲审纪律（写进包内）：
- 只给决策点之前的数据（特征包 + 决策点前 120 根 OHLC），无未来、无结果；
- 不给机器草稿结论（防锚定），评审者独立判断；
- 输出固定为 judge/annotation_schema.json 的 JSON，存回
  knowledge/reviews/<segment>.json 后由 eval/review_diff.py 对账。
"""

import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
KB = os.path.join(ROOT, "knowledge")
OUT = os.path.join(ROOT, "review-packs")

HEADER = """# 盲审任务（价格行为学样本标注复核）

你是一名独立评审者。规则：
1. 你只能使用本包内的数据：决策点（第 180 根）之前的 K 线与特征包。没有未来数据，不许假设之后发生了什么。
2. 按下方「常驻核心 / 路由卡 / setup 卡片」的口径判断，不许自创规则。
3. 只输出一个 JSON 对象（格式见文末），不要输出解释文字。
4. 空仓是合法且常见的结论；拿不准就输出 no_trade 并给出原因枚举。
5. 假设用一句话陈述，不许给数字权重/概率。

"""


def bars_table(bars, start_idx):
    lines = ["idx,o,h,l,c"]
    for i, b in enumerate(bars):
        lines.append(f"{start_idx + i},{b['o']},{b['h']},{b['l']},{b['c']}")
    return "\n".join(lines)


def main():
    os.makedirs(OUT, exist_ok=True)
    core = open(os.path.join(KB, "core.md")).read()
    router = open(os.path.join(KB, "router.md")).read()
    schema = open(os.path.join(os.path.dirname(__file__), "annotation_schema.json")).read()
    cards = ""
    setups_dir = os.path.join(KB, "setups")
    for name in sorted(os.listdir(setups_dir)):
        cards += open(os.path.join(setups_dir, name)).read() + "\n"
    exdir = os.path.join(KB, "examples")
    made = 0
    for name in sorted(os.listdir(exdir)):
        if not name.endswith(".json"):
            continue
        ex = json.load(open(os.path.join(exdir, name)))
        decision = ex["decision_bar"]
        bars = ex["bars"]  # 只含决策点之前的 120 根
        pack = ex["features"]
        parts = [
            HEADER,
            core,
            router,
            "## setup 卡片（全部 6 张，供路由命中时查）\n" + cards,
            f"## 样本 {ex['segment']}（{ex['symbol']} {ex['interval']}，决策点 = 第 {decision} 根收盘后）",
            "## 特征包（感知层代码输出）\n```json\n"
            + json.dumps(pack, ensure_ascii=False)
            + "\n```",
            f"## K 线（第 {decision - len(bars)}–{decision - 1} 根）\n```\n"
            + bars_table(bars, decision - len(bars))
            + "\n```",
            '## 输出格式（只输出此 JSON；segment 填 "' + ex["segment"] + '"）\n```json\n' + schema + "\n```",
        ]
        with open(os.path.join(OUT, ex["segment"] + ".md"), "w") as f:
            f.write("\n\n".join(parts))
        made += 1
    print("review packs:", made)


if __name__ == "__main__":
    main()
