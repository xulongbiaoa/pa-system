"""预演式（CAMP）两遍提示词：战役地图 + 到达核对（2026-10-31 对比实验）。

与现行单点判读（AUTO = prompt_builder.build_prompt）配对比较，见
eval/reports/camp-vs-auto-prereg-2026-10-31.md。知识上下文与 AUTO
同源（core + router + 路由卡 + 数字附件 + K 线表），只换任务与输出。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from judge.prompt_builder import _read, route_cards, bars_table, KB  # noqa: E402

MAP_TASK = """## 任务：画战役地图（预演制第一遍，本遍不下单）
你站在第 90 根收盘处。只输出一个 JSON 对象（不要解释、不要围栏），字段：
{
 "context": "上升|下降|震荡",
 "trend_maturity": "MM已达|MM未达|无从投影（一句话依据写进 uncertainty）",
 "points": [{"id": "P1", "lo": 数字, "hi": 数字, "kind": "支撑|阻力",
             "rating": "要塞|据点", "anchors": ["锚的种类，如 波段高点/缺口锚/前波段低点"]}],
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
纪律：决胜点只许来自图上已存在的结构（摆动极值、缺口锚、要塞带）；
没画出的位置不存在。每点必须有双向意识：涨考上方阻力、跌考下方支撑。
branches 每点至多 2 条。点数 2–5 个。数字用附件与 K 线表的精确价位。"""

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
hypotheses 直接沿用地图的主备假设（可按 takeover_if 更新 primary）。"""


def _context_parts(pack, bars):
    parts = [_read(os.path.join(KB, "core.md")),
             _read(os.path.join(KB, "router.md"))]
    cards, reasons = route_cards(pack)
    for c in cards:
        parts.append(_read(os.path.join(KB, "setups", c + ".md")))
    if (pack.get("gaps") or {}).get("open"):
        parts.append(_read(os.path.join(KB, "setups", "G1-confluence-gap.md")))
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
