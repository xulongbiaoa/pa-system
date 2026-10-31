"""行动与结果向量（W03 / 方案 §6.3–§6.5）。

行动先相对位置、再关联过程。每个区间以固定起点 p0（起始 bar 前一根 close）、
起始尺度 s0（起点冻结）、方向 d 计算结果向量；只记录向量，不汇总成力量分。
“推进更快”只是单位根数位移更大；“谁更强”属于解释层，不在本层出现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional, Sequence

from .contracts import Bar
from .facts import compute_facts


@dataclass
class Segment:
    """一段已发生的行动（区间）。追加当前结果，不重写先前查询的结果。"""
    segment_id: str
    direction: str                    # up | down
    start_bar_id: str
    p0: Optional[Decimal]             # 起始 bar 前一根 close；缺前根为 None（计算标不足）
    s0: Optional[Decimal]             # 起点冻结尺度
    bar_ids: List[str] = field(default_factory=list)
    level_key: Optional[str] = None   # 关联位置（Attempt 派生段）
    open: bool = True

    def result(self, bars_by_id) -> dict:
        return compute_result(self, bars_by_id)


def compute_result(seg: Segment, bars_by_id) -> dict:
    bars = [bars_by_id[bid] for bid in seg.bar_ids]
    d = Decimal(1) if seg.direction == "up" else Decimal(-1)
    if seg.p0 is None or not bars:
        return {"segment_id": seg.segment_id, "sufficient": False,
                "reason": "缺前根 close 或区间为空，结果标不足"}
    closes_out = 0
    overlaps = []
    fav = Decimal(0)
    adv = Decimal(0)
    prev = None
    for i, b in enumerate(bars):
        extreme = b.high if d == 1 else b.low
        adverse = b.low if d == 1 else b.high
        fav = max(fav, d * (extreme - seg.p0))
        adv = max(adv, -d * (adverse - seg.p0))
        if prev is not None:
            f = compute_facts([prev], b)
            if f.overlap_prev is not None:
                overlaps.append(f.overlap_prev)
        prev = b
    last = bars[-1]
    net = d * (last.close - seg.p0)
    giveback = fav - net                     # 可大于最大推进，不截断
    giveback_ratio = (giveback / fav) if fav != 0 else None
    avg_overlap = (sum(overlaps) / len(overlaps)) if overlaps else None
    return {
        "segment_id": seg.segment_id, "sufficient": True,
        "direction": seg.direction, "elapsed_bars": len(bars),
        "net_progress": net, "favorable_excursion": fav, "adverse_excursion": adv,
        "giveback": giveback, "giveback_ratio": giveback_ratio,
        "avg_overlap": avg_overlap, "p0": seg.p0, "s0": seg.s0,
        "rel_net": (net / seg.s0) if seg.s0 else None,
        "rel_favorable": (fav / seg.s0) if seg.s0 else None,
    }


def compare_actions(a: Segment, b: Segment, bars_by_id, *,
                    same_timeframe=True, same_level=True) -> dict:
    """对照：只并列相同参照下的向量；参照不一致显式警告，不直接排强弱。"""
    warnings = []
    if not same_timeframe:
        warnings.append("不同周期，不可直接比较")
    if not same_level:
        warnings.append("不同位置，参照不一致")
    if (a.s0 is None) != (b.s0 is None):
        warnings.append("尺度定义不一致（一侧缺尺度）")
    return {"a": a.result(bars_by_id), "b": b.result(bars_by_id),
            "comparable": not warnings, "warnings": warnings}


# ---- 价格相对位置的纯关系（事件检测共用，方案 §6.3 词汇） ----

def touched(bar: Bar, lo: Decimal, hi: Decimal) -> bool:
    return bar.low <= hi and bar.high >= lo


def separated_above(bar: Bar, price: Decimal) -> bool:
    """整根位于某价上方。"""
    return bar.low > price


def separated_below(bar: Bar, price: Decimal) -> bool:
    """整根位于某价下方。"""
    return bar.high < price


def fully_outside_band(bar: Bar, watch_lo: Decimal, watch_hi: Decimal, side: str) -> bool:
    if side == "up":
        return bar.low > watch_hi
    return bar.high < watch_lo


def inside_band(bar: Bar, watch_lo: Decimal, watch_hi: Decimal) -> bool:
    return bar.low <= watch_hi and bar.high >= watch_lo
