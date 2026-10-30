"""flags 生产者：把感知层要塞带状态翻成 adjudicate 的软规则 flags。

背景（2026-10-30）：adjudicate 的 flags 参数长期没有任何生产者——三个
生产调用点（pa_cli / gold_run / pilot_run）全都不传，S1/S2/S3 在真实回放
里从未触发，与当初 H6 台账没接线是同一类故障。本模块补上 S2/S3 的接线；
阈值不新设：decaying（测 ≥4）/ trampled（收盘穿越 ≥3）由 fortress.py
按既有定版口径算好，这里只做「计划 ↔ 要塞带」的映射。

映射口径（保守）：一条带与本计划相关，当且仅当
  - 入场价落入带内，或
  - 止损穿越该带：入场到止损的价格区间覆盖整条带且止损落在带外远侧
    （即这笔单的风险区要穿过这条带才到止损）。
不相关的带（价格够不着）不升格。多个相关带取并集（任一 trampled /
decaying 即置位）。

second_bar_confirmed 不是感知量：它是判断层选定的入场方式，由 plan
声明（judge/schema.json 的 plan.second_bar_confirmed），这里只转手。

parabolic（S1）**未启用**（2026-10-31 审计标注：账面状态与
S2/S3 分开记——S2/S3 已接线，S1 判据不存在）：判据（连续根数 / 实体 / 总幅倍数）需要新
常数，无样本与原册依据前不设——见 review-out/README 待办，接线审计
测试里以 PENDING 登记，判据定版后从 PENDING 移除并在此补生产者。
"""


def band_relevant(band, entry, stop):
    lo, hi = band["lo"], band["hi"]
    if lo <= entry <= hi:
        return True
    seg_lo, seg_hi = min(entry, stop), max(entry, stop)
    # 止损穿越：区间覆盖整带且止损严格落在带外
    return seg_lo <= lo and seg_hi >= hi and not (lo <= stop <= hi)


def build_flags(plan, pack):
    """返回 adjudicate 的 flags dict（parabolic 暂不生产，见模块头）。"""
    flags = {"second_bar_confirmed": bool(plan.get("second_bar_confirmed"))}
    bands = (pack.get("fortress") or {}).get("bands") or []
    entry, stop = plan.get("entry"), plan.get("stop")
    if entry is None or stop is None:
        return flags
    rel = [b for b in bands if band_relevant(b, entry, stop)]
    if any(b.get("trampled") for b in rel):
        flags["trample"] = True
    if any(b.get("decaying") for b in rel):
        flags["decaying"] = True
    return flags
