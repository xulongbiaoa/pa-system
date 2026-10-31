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
               "watch_behavior": "等待行为：价格测试该点时要出现的反应（一句话，必须指向具体价位与K线形态）",
               "trigger": "入场触发：setup 要求的决定性证据成立（一句话，可核对）；成立时再核对剩余空间",
               "entry_style": "limit|stop|market",
               "cancel_if": "取消条件：什么价格事件出现则本分支作废（如突破被接受站稳于位外、触发时空间不足）",
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
写明为何无从投影。
分支预写三条款（硬性）：
1. 跟进锚定：trigger 不许出现无锚的跟进要求。跟进必须写成已锚定的
序列——信号 K 出现在触发根之后、跟进根为决策根或其前一根，到达时
当根可核对完；成立必须等决策根之后再跟进的分支，trigger 只写截至
决策根可核对的部分，不许把未来的跟进写进 trigger。
2. 叠加上限：每条 trigger 至多 2 个可核对条件，且至少 1 个是价格
事件（触及点位带 / 收盘越界 / 收盘落带内）；成色（实体、CLV、强弱）
只许作辅条件，不许作主条件或单独成条。
3. 引用价锚定：trigger 引用的收回 / 越界 / 突破价必须落在该分支
点位 [lo, hi] 内或带沿 ±0.5×段均幅内；超出范围的价位属邻点辖区，
改挂到对应点位的分支，不许在本分支引用。
候选四段链（硬性，每条分支按此写）：观察位置（point_id 的点位带）
→ 等待行为（watch_behavior）→ 入场触发（trigger）→ 取消条件
（cancel_if）。等的是某个位置出现某种行为，不是等下一根 K 线——
下一根只是新信息到来的时间，不是入场理由。
- 等待行为必须写成能指向具体价位与 K 线的条件：「未站稳」须拆成
  如「盘中进入带内、收盘回到带下沿之下」；「跟进」须按三条款 1
  锚定到已走完的序列；「再次测试」须写明第几次测试、与上次间隔
  的结构。不许用一组模糊词替换另一组模糊词。
- 入场触发只写 setup 卡上必须项里的决定性证据；行为已在接近
  序列里发生过的，触发当根即可核对成立，不许再要求多等一根；
  行为没发生的，根数走过多少都不自动成立。
- 取消条件写价格事件（被接受 = 收盘站稳于位外并回踩不破，按
  本系统既有口径）或空间事件（触发时首目标剩余空间不足），
  不写时间到了。"""

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
不合格）；首目标毛 RR 取不到 2:1 时必须带 cap_reason 点名封顶结构。
order_type 与分支 entry_style 对齐：stop → stop_market（entry 写触发价，
回放触及才成交）；limit → limit；market → market（决策点立即入场）。
依据引用（硬性）：pending_conditions 的每条 missing 必须是对象
{"condition": "缺哪条必要条件", "evidence": "对应哪根K线/哪个价位",
"basis": {"type": ..., "ref": ...}}。出处只有四类：冻结分支 trigger
未成立的部分 basis={branch, 点位号}；卡片必须项缺失 basis={card,
条目号 如 B3-N3}；骨架硬条 basis={skeleton, 条款名}；冻结文本与
卡片之外的任何要求 basis 一律标 {extra, 理由一句话}。extra 不许
单独构成不写候选的理由：分支 trigger 与卡上必须项都已成立时必须
按分支写候选，extra 只作复核标记随判读落账。
核对顺序（四段链）：先核等待行为是否已在接近序列里发生（可以在
决策根之前的几根里完成，不限于决策根当根）→ 发生了才核入场触发
→ 触发成立立即按分支写候选，不许以「再等一根确认」推迟；等待
行为未发生的，pending 写明还缺哪个行为、在哪个点位带、取消条件
是什么，basis 引 branch。假设只许因新的反证调整，调整时在
uncertainty 写明反证是什么；不许无声移动入场标准。
B3 收回认定三问（2026-10-31 R1）：分支 trigger 以「收回」主张 B3 翻面成立时同样逐问作答——① 此前哪一根收盘站在翻面位之外（根号+收盘价；从无任何一根收盘在位外，就不存在收回，盘中刺入不算）；② 收回根是哪一根；③ 收回根是否即本决策根（B3-N3：收回根也是入场决策根，前移认定或决策根只作到达/成交 = trigger 未成立）。任一问不过：不写候选，pending 的 missing 引 card B3-N1 或 B3-N3、evidence 写明卡在哪一问；全过写候选时把三问答案写进 candidate 的 reason。"""


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
