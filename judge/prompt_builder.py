"""A 档粘贴式：把 core + router + 特征包 + 命中卡片 + 召回样本 + K 线表
拼成一段文本，供任何聊天 AI 返回判断 JSON。

路由（与 router.md 四类语境对齐的机器版，2026-10-30 重写）：
趋势确定 → 顺势卡 + B1 突破事件 + B2 突破回踩；
趋势失势（账本与标签冲突 / 标签置信边界）→ C1 反转卡升权 + B3 + 顺势卡；
震荡 → B3 翻面 + C1（区间边缘反转与突破失败共用同一套证据）；
其余 → 只带 B3。每类至多 3 张卡。

router.md 里还有两条条件路由不能代判：「MM 已达（趋势成熟）」——MM
候选投影已进 pack（pack.mm），但「已达」是认定不是字段；「两腿衰竭 /
腿数足」的 trend_age.legs 恒为 1（主级别摆动交替，同向腿不可能相邻，
见 2026-10-30 复核），故腿数与 MM 到达一律留给判断层自己认定。

原册讲义召回（2026-10-30 接入）：按路由卡片 + 语境标签从原册案例库
（knowledge/brooks-cases）拉 2 页 Brooks 本人讲义进提示，见
judge/brooks_recall.py。只召回不裁决，出处随页附上。
"""

import json
import os

from judge.brooks_recall import recall_cases

ROOT = os.path.join(os.path.dirname(__file__), "..")
KB = os.path.join(ROOT, "knowledge")

# 召回池只开 dev：val/test 的答案不得进入任何提示（2026-10-30 复核后修）。
# 开发集样本自己也从 dev 池取，靠 segment/时间区间排除自身。
POOL_SPLIT = "dev"

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
    # 2026-10-31 审计修复：趋势轨原带 B1（顺势突破）——但本地规则下突破
    # 当根入场已禁用，B1 作为入场卡基本惰性；B3（突破失败翻面）是五轮
    # 消融的候选主力，却只在冲突轨才进菜单。换 B3 进来，B1 的强突破判据
    # 由《眼睛检查清单》与 B2/B3 卡内引用承载。
    return [follow, "B2-breakout-pullback", "B3-failed-breakout"], reasons


def _bar_range(bars):
    ts = [b["t"] for b in bars if isinstance(b, dict) and "t" in b]
    return (min(ts), max(ts)) if ts else None


def _overlap(a, b):
    return bool(a and b and not (a[1] < b[0] or b[1] < a[0]))


def recall_examples(pack, k=3, *, segment=None, symbol=None, bars=None,
                    pool_split=POOL_SPLIT):
    """召回参考样本。三条硬约束（2026-10-30 复核后修）：

    1. **不许召回自己**：按 segment/id 排除当前样本；
    2. **不许召回归属重叠的窗口**：同标的且 K 线时间区间相交的样本一并排除
       （只按文件名排除挡不住「同一段行情的另一份切片」）；
    3. **只从允许的池召回**：默认只从 dev 池取，val/test 样本的提示里不得出现
       验证/测试集的答案。

    原实现只按趋势标签把「每类第一条」拼起来，实测任何样本都只返回
    ex-APT + ex-ARB 两条，且这三条都不设防——APT/ARB/AVAX 三段会在自己的
    提示里读到自己的 draft_verdict。改动后按 (语境, 草稿结论) 分桶轮转，
    同语境优先，保证 k 条尽量不同桶。
    """
    exdir = os.path.join(KB, "examples")
    if not os.path.isdir(exdir):
        return []
    cur_range = _bar_range(bars or [])
    pool = []
    for name in sorted(os.listdir(exdir)):
        if not name.endswith(".json"):
            continue
        e = json.load(open(os.path.join(exdir, name)))
        if pool_split and e.get("split") != pool_split:
            continue
        if segment and (e.get("segment") == segment
                        or e.get("id") == "ex-" + segment):
            continue
        if symbol and e.get("symbol") == symbol and _overlap(
                cur_range, _bar_range(e.get("bars") or [])):
            continue
        pool.append(e)

    trend = pack["trend"]["label"]
    buckets = {}
    for e in pool:
        key = (e["annotation"].get("context"),
               e["annotation"].get("draft_verdict"))
        buckets.setdefault(key, []).append(e)
    # 同语境优先，其余按 (语境, 结论) 字典序——确定性，不靠文件系统顺序
    order = sorted(buckets, key=lambda kk: (kk[0] != trend, str(kk[0]), str(kk[1])))
    picked = []
    while len(picked) < k:
        progressed = False
        for key in order:
            if len(picked) >= k:
                break
            if buckets[key]:
                picked.append(buckets[key].pop(0))
                progressed = True
        if not progressed:
            break
    return picked[:k]


def bars_table(bars):
    lines = ["idx,o,h,l,c"]
    for i, b in enumerate(bars):
        lines.append(f"{i},{b['o']},{b['h']},{b['l']},{b['c']}")
    return "\n".join(lines)


def build_prompt(pack, bars, prev_hypotheses=None, *, segment=None, symbol=None):
    parts = []
    parts.append(_read(os.path.join(KB, "core.md")))
    parts.append(_read(os.path.join(KB, "router.md")))
    cards, reasons = route_cards(pack)
    for c in cards:
        parts.append(_read(os.path.join(KB, "setups", c + ".md")))
    # G1 证据组合卡（研究级）：账本有敞开缺口才附加，不占 3 张菜单名额；
    # 无敞开缺口时 R1 无从谈起，加载只会诱导硬凑（2026-10-30 接线）。
    if (pack.get("gaps") or {}).get("open"):
        parts.append(_read(os.path.join(KB, "setups", "G1-confluence-gap.md")))
        cards = cards + ["G1-confluence-gap"]
        reasons.append("账本有敞开缺口 → 附加 G1 证据组合卡（研究级）")
    parts.append("## 本次路由依据（机器按特征包判定，卡已按此装载）\n"
                 + "；".join(reasons)
                 + "\n卡内门槛（三件套、MM、腿数）感知层未算，须你自行认定；"
                   "认定不了就写进 uncertainty 并空仓。")
    parts.append("## 数字附件（特征包：精确价位、缺口账本与数字证据；语境与形态以图读为准——附件 trend 是机器摆动标签，与图读冲突时以图为准）\n```json\n"
                 + json.dumps(pack, ensure_ascii=False) + "\n```")
    exs = recall_examples(pack, segment=segment, symbol=symbol, bars=bars)
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
    cases = recall_cases(pack, cards)
    if cases:
        blocks = []
        for cs in cases:
            blocks.append(f"### [{cs['book']} {cs['title']} · slide {cs['slide']}]"
                          f"（标签：{','.join(cs['tags'])}）\n{cs['text']}")
        parts.append("## 阿布原册讲义（案例召回，出处可溯）\n"
                     "以下为 Brooks 本人课件原文，与本段无关的页请忽略；"
                     "引用他的结论时注明出处页。\n\n" + "\n\n".join(blocks))
    if prev_hypotheses:
        parts.append("## 上一根假设账本\n```json\n"
                     + json.dumps(prev_hypotheses, ensure_ascii=False) + "\n```")
    parts.append("## 最近 K 线（OHLC 数值表）\n```\n" + bars_table(bars[-120:]) + "\n```")
    parts.append(
        "## 任务（输出格式是硬契约，先看骨架再判断）\n"
        "判读顺序：先看图（若随附图表）定语境、形态与 setup，再用数字附件的"
        "精确价位定价、核对账本与红线；附件 trend 标签与图读冲突时以图为准。\n"
        "入场方式分工（2026-10-31 定版）：顺势延续类（A1/A2/B2）的入场是 "
        "stop 触发——入场价写信号 K 极值外侧、order_type 写 market（按触发 "
        "价计）；限价（order_type=limit）只用于翻面类（B3/G1）与区间边缘，"
        "因为那里的限价位本身就是决胜点。出场方式：targets≥2 的计划 exit_mode 写 scale（分批：首目标出 1/2、次目标出 1/4、余 1/4 跟末目标，共用止损）；单目标写 full。\n"
        "顺势计划写限价回踩单的，必须在 "
        "strongest_countercase 里说明为何不用 stop 触发。\n"
        "只输出一个 JSON 对象，不要任何解释文字、不要代码围栏。顶层只许 "
        "context / primary / hypotheses / candidates / no_trade_reason / "
        "pending_conditions / uncertainty 七个字段，多一个键即作废。骨架：\n"
        "```json\n"
        "{\"context\": \"上升|下降|震荡\", \"primary\": \"H1\",\n"
        " \"hypotheses\": [\n"
        "  {\"id\": \"H1\", \"statement\": \"主假设一句话\", \"holds_if\": \"...\", "
        "\"void_if\": \"...\", \"takeover_if\": \"...\", \"menu\": [\"A1\"]},\n"
        "  {\"id\": \"H2\", \"statement\": \"备选一句话\", \"holds_if\": \"...\", "
        "\"void_if\": \"...\", \"takeover_if\": \"...\", \"menu\": []}],\n"
        " \"candidates\": [], \"no_trade_reason\": \"无命中\", \"uncertainty\": [\"...\"]}\n"
        "```\n"
        "硬规则：hypotheses 必须是数组（不是 {main, backup} 对象）；primary 必填且"
        "等于主假设的 id；hypothesis 六字段（id/statement/holds_if/void_if/"
        "takeover_if/menu）一个不许少，menu 是 setup 数组；假设不许带数字权重。"
        "有合格候选时 candidates 每项含 setup/side/qualified/reason/feature_refs 与 "
        "plan（entry/stop/targets/void_if/risk_frac 必备，可加 order_type/void/"
        "second_bar_confirmed；void 若写必须是结构化对象 "
        "{\"level\": 数字, \"side\": \"above\" 或 \"below\"}，不许写成散句）。若随附 G1 卡且引用 G1：该候选必须另带 "
        "conditions 条件矩阵（R1/R2/R3 必需、V1/V2/V3 否决、E1/E2 增强，"
        "逐项写 rule_id/role/status/dimension/evidence_refs/groups（role 只能是 "
        "required / enhancing / veto 三个英文词，E 类增强项写 enhancing 不许写 "
        "enhancement；维度由 rule_id 固定映射：R1 账本/R2 位置/R3 触发，不许改），声明 met 必带证据"
        "引用，同源证据只算一组）与 strongest_countercase（最强反证一句）；"
        "G1 证据不齐只能挂起（pending_conditions）或空仓，不许降标准凑齐。"
        "职责分工（硬性）：语境、形态与 setup 成色认定归你；数字执法归裁决层"
        "（gate）——净 RR、止损位置合法性、风险比例与条文红线由 gate 计算并"
        "拒绝。setup 卡上的条件（语境/位置/成色/腿数）齐了，就写成候选并 "
        "qualified=true，哪怕你粗算 RR 在边缘：替 gate 毙单是越权，gate 拒掉"
        "的单会留痕、比不写更有信息；卡条件不齐不要写候选凑数，写进 "
        "pending_conditions。pending_conditions 每项写成对象 {\"setup\": "
        "\"B3\", \"missing\": [\"缺哪项\", \"...\"], \"watch\": \"等什么价位/"
        "到达行为\"}，不许写散文字符串。"
        "无合格候选时 candidates=[] 且 no_trade_reason 必填"
        "枚举（无命中/位置不对/成色不合格/背景不明/感知未定）。空仓是合法输出。"
    )
    return "\n\n".join(parts)
