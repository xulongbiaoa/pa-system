"""单根事实计算（W02 / 方案 §6.1）。

只算可复算的量，不在这一层生成强/弱 K 标签。
归一化尺度 = 该根之前最多 20 根已收盘 range 的中位数（因果，禁止用全窗波动率回评早期）。
不足 20 根标 warmup；尺度为零或本根零振幅时相关比率为 None，不填零伪装。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Sequence

from .contracts import Bar

SCALE_WINDOW = 20


@dataclass(frozen=True)
class BarFacts:
    bar_id: str
    range: Decimal
    signed_body: Decimal                 # close - open（带符号）
    body_ratio: Optional[Decimal]        # |body| / range；零振幅 -> None
    close_location: Optional[Decimal]    # (close-low)/range；零振幅 -> None
    upper_wick: Decimal
    lower_wick: Decimal
    overlap_prev: Optional[Decimal]      # 与前根价格区间的重叠长度（绝对价）
    close_change: Optional[Decimal]      # close - prev_close
    scale: Optional[Decimal]             # 归一化尺度（此前 range 中位数）
    warmup: bool

    def rel(self, value: Optional[Decimal]) -> Optional[Decimal]:
        """相对尺度值；尺度缺失/为零返回 None。"""
        if value is None or self.scale is None or self.scale == 0:
            return None
        return value / self.scale


def compute_facts(prev_bars: Sequence[Bar], bar: Bar) -> BarFacts:
    rng = bar.high - bar.low
    body = bar.close - bar.open
    upper = bar.high - max(bar.open, bar.close)
    lower = min(bar.open, bar.close) - bar.low
    if rng == 0:
        body_ratio = None
        close_loc = None
    else:
        body_ratio = abs(body) / rng
        close_loc = (bar.close - bar.low) / rng
    if prev_bars:
        prev = prev_bars[-1]
        overlap = max(Decimal(0), min(bar.high, prev.high) - max(bar.low, prev.low))
        close_change = bar.close - prev.close
    else:
        overlap = None
        close_change = None
    window = [b.high - b.low for b in prev_bars[-SCALE_WINDOW:]]
    if window:
        scale = D_median(window)
        warmup = len(window) < SCALE_WINDOW
    else:
        scale = None
        warmup = True
    return BarFacts(bar_id=bar.id, range=rng, signed_body=body,
                    body_ratio=body_ratio, close_location=close_loc,
                    upper_wick=upper, lower_wick=lower,
                    overlap_prev=overlap, close_change=close_change,
                    scale=scale, warmup=warmup)


def D_median(values) -> Decimal:
    """Decimal 中位数（偶数个取中间两数均值）。"""
    vals = sorted(values)
    n = len(vals)
    mid = n // 2
    if n % 2 == 1:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2
