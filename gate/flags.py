"""flags 生产者：把感知层要塞带状态翻成 adjudicate 的软规则 flags。

背景（2026-10-30）：adjudicate 的 flags 参数长期没有任何生产者——三个
生产调用点（pa_cli / gold_run / pilot_run）全都不传，S2/S3 在真实回放
里从未触发，与当初 H6 台账没接线是同一类故障。本模块补上 S2/S3 的接线；
阈值不新设：decaying / trampled 由 fortress.py 按既有口径算好，这里只做
「计划 ↔ 要塞带」的映射。

映射口径（保守）：一条带与本计划相关，当且仅当
  - 入场价落入带内，或
  - 止损穿越该带：入场到止损的价格区间覆盖整条带且止损落在带外远侧
    （即这笔单的风险区要穿过这条带才到止损）。
不相关的带（价格够不着）不升格。多个相关带取并集（任一 trampled /
decaying 即置位）。

2026-10-31 审计处置三项：
  - S1（parabolic）整体删除：判据自始不存在、生产者从未写过，留一个
    永远不会置位的 flag 等于假装有这层防护。按「剪掉不明的枝」先例
    （凯利同日删除）移除；日后要恢复，先拿出有原册锚点的判据 + 样本。
  - second_bar_confirmed 删除：它是判断层的自声明，却能豁免 S2 的
    踩踏减半——自己声明、自己免检，且感知层无从核对。删除后 S2 对
    踩踏相关带无条件减半；声明字段一并从 schema 移除。
  - S2 可达性已由语料复测澄清（140 段、规范计划）：trample 触发
    约 41–50%，此前生产零触发是候选稀缺（五轮消融总候选个位数），
    不是死代码。S2 保留。
  - S3（decaying 减半）删除：计数口径（tests/crosses 的各种组合）
    在 180 根尺度上触发率 63–88%，无区分力——衰减是「最近几次测试
    反应变弱」，计数聚合表达不了。fortress 的 decaying 字段降为
    描述量保留，gate 不再消费；逐测反应检测器另行立项。
"""


def band_relevant(band, entry, stop):
    lo, hi = band["lo"], band["hi"]
    if lo <= entry <= hi:
        return True
    seg_lo, seg_hi = min(entry, stop), max(entry, stop)
    # 止损穿越：区间覆盖整带且止损严格落在带外
    return seg_lo <= lo and seg_hi >= hi and not (lo <= stop <= hi)


def build_flags(plan, pack):
    """返回 adjudicate 的 flags dict（只剩 S2 的 trample 一项）。"""
    flags = {}
    bands = (pack.get("fortress") or {}).get("bands") or []
    entry, stop = plan.get("entry"), plan.get("stop")
    if entry is None or stop is None:
        return flags
    rel = [b for b in bands if band_relevant(b, entry, stop)]
    if any(b.get("trampled") for b in rel):
        flags["trample"] = True
    return flags
