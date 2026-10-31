"""预演式（CAMP）两遍提示词：战役地图 + 到达核对（2026-10-31 对比实验）。

与现行单点判读（AUTO = prompt_builder.build_prompt）配对比较，见
eval/reports/camp-vs-auto-prereg-2026-10-31.md。知识上下文与 AUTO
同源（core + router + 路由卡 + 数字附件 + K 线表），只换任务与输出。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from judge.prompt_builder import _read, route_cards, bars_table, KB, priors_section  # noqa: E402

MAP_TASK = """## 任务：画战役地图（预演制第一遍，本遍不下单）
你站在第 90 根收盘处。只输出一个 JSON 对象（不要解释、不要围栏），字段：
{
 "context": "上升|下降|震荡",
 "trend_maturity": "MM已达|MM未达|无从投影（一句话依据写进 uncertainty）",
 "points": [{"id": "P1", "lo": 数字, "hi": 数字, "kind": "支撑|阻力",
             "rating": "要塞|据点", "anchors": ["锚的种类，如 波段高点/缺口锚/前波段低点"]}],
 "rejected_anchors": [{"ref": "被拒绝的附件点位（价位或带，一句话描述）",
             "reason": "拒绝纳入决胜点的一句话理由"}],
 "hypotheses": [
   {"id": "H1", "statement": "主假设一句话", "holds_if": "...", "void_if": "...",
    "takeover_if": "什么事实出现时备假设接管", "menu": ["setup 代号"]},
   {"id": "H2", "statement": "备假设一句话", "holds_if": "...", "void_if": "...",
    "takeover_if": "...", "menu": []}],
 "branches": [{"point_id": "P1", "setup": "B3|A1|A2|B1|B2|C1|G1", "side": "long|short",
               "trigger": "到达该点时什么行为出现才执行（一句话，可核对）",
               "entry_style": "limit|stop|market",
               "void": "该分支的价格失效位一句话"}],
 "campaign_void_if": "什么战役事件出现时整张地图作废（起点失效/MM到达/定性翻面）",
 "uncertainty": "最大的不确定一句话"
}
纪律：决胜点来源两类——已存在的结构（摆动极值、缺口锚、要塞带）与
算出来的投影位（当前腿 MM 投影、通道对侧投影）；没画出的位置不存在。
每点必须有双向意识：涨考上方阻力、跌考下方支撑。
branches 每点至多 2 条。点数 2–7 个。数字用附件与 K 线表的精确价位。
点位对齐条款（硬性）：数字附件 fortress.bands 的要塞带与 gaps.open 的
敞开缺口锚，必须逐一处置——纳入 points（同址可合并，anchors 写明
来源），或写入 rejected_anchors 逐个给出拒绝理由（如锚数不足、已被
踩踏、与更强同址点重复）；不许默默丢弃。
投影条款（硬性）：当前战役腿的 MM 投影位必须作为一个 point 出现
（在现价上方记阻力、下方记支撑，lo=hi=投影价，anchors 写「MM投影」
并注明投影所用腿）；附件 mm.candidates 只作参考，战役腿投影须按图
自行核算。trend_maturity 判「无从投影」时免此条，但须在 uncertainty
写明为何无从投影。"""

ARRIVAL_TASK = """## 任务：到达核对（预演制第二遍）
上方附了第 90 根冻结的战役地图。你站在第 180 根收盘处，**不许重画地图**。
只输出标准判断 JSON（顶层字段与平常完全一致：context/primary/hypotheses/
candidates/no_trade_reason/pending_conditions/uncertainty）。
动作只许三种：
1. 地图上某个决胜点正在被测试（当前价进入该点 [lo,hi] ±0.25×段均幅）
   且其分支 trigger 已成立 → 按分支写 candidate，candidate 必须带
   "point_id" 字段指明是哪张地图的哪个点；入场/止损/目标按分支与
   当前精确价位定价，其余契约（conditions、countercase、RR）照常。
2. campaign_void_if 已发生 → candidates 留空，no_trade_reason 用
   「位置不对」，uncertainty 写明哪条战役事件作废了地图。
3. 无点被测试，或点被测试但 trigger 未成立 → candidates 留空，
   用 pending_conditions 记下在等哪个点的什么触发。
点外造单（写了地图上没有的位置）= 违规，会被单独计数。
hypotheses 直接沿用地图的主备假设（可按 takeover_if 更新 primary）。
plan 契约与单点判读完全一致：结构化 void 必备（只写文字版判格式
不合格）；首目标毛 RR 取不到 2:1 时必须带 cap_reason 点名封顶结构。"""


def _context_parts(pack, bars):
    parts = [_read(os.path.join(KB, "core.md")),
             _read(os.path.join(KB, "router.md"))]
    cards, reasons = route_cards(pack)
    for c in cards:
        parts.append(_read(os.path.join(KB, "setups", c + ".md")))
    if (pack.get("gaps") or {}).get("open"):
        parts.append(_read(os.path.join(KB, "setups", "G1-confluence-gap.md")))
    pri = priors_section(cards)
    if pri:
        parts.append(pri)
    parts.append("## 本次路由依据\n" + "; ".join(reasons))
    parts.append("## 数字附件（特征包；语境与形态以图读为准）\n```json\n"
                 + json.dumps(pack, ensure_ascii=False) + "\n```")
    parts.append("## 最近 K 线（OHLC 数值表）\n```\n"
                 + bars_table(bars[-120:]) + "\n```")
    return parts


def build_map_prompt(pack, bars):
    return "\n\n".join(_context_parts(pack, bars) + [MAP_TASK])


def build_arrival_prompt(map_obj, pack, bars):
    parts = _context_parts(pack, bars)
    parts.append("## 冻结战役地图（第 90 根画定，不许改）\n```json\n"
                 + json.dumps(map_obj, ensure_ascii=False) + "\n```")
    parts.append(ARRIVAL_TASK)
    return "\n\n".join(parts)
