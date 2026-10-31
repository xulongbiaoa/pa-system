"""地形提供器（W03 / 方案 §6.2）。

位置必须先存在才谈动作。首版位置来源：
- manual：审定的人工样板锚（外部注册）；
- swing：确认摆动点——确认需要右侧 K 线，confirmed_at = 确认根的 close_time，
  绝不把极值发生时间当确认时间；确认前该位置不存在，不得回溯制造前向事件；
- gap_anchor / target：由账本与目标注册产生（见 reducers / queries 注册口）；
- model_proposed：AI 提案经程序核验来源后注册，标记保留，不与规则位置同级混用。

观察带政策：watch = [lo - band, hi + band]，band 随 Level 冻结；
本版默认 band = 0.5 * 尺度（注册时刻的段尺度由调用方给出），更改边界生成新版本。
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Sequence

from .contracts import Bar, D, Level, Target

DEFAULT_SWING_RIGHT = 2
DEFAULT_SWING_LEFT = 2


def make_level(level_id, lo, hi, *, kind, source, available_at, confirmed_at,
               band: Decimal, version=1, direction_hint=None) -> Level:
    lo, hi = D(lo), D(hi)
    if lo > hi:
        lo, hi = hi, lo
    return Level(level_id=level_id, version=version, kind=kind, lo=lo, hi=hi,
                 watch_lo=lo - band, watch_hi=hi + band, source=source,
                 source_available_at=int(available_at), confirmed_at=int(confirmed_at),
                 direction_hint=direction_hint)


class SwingDetector:
    """流式确认摆动点：极值在右侧 right 根收盘后才确认。

    返回新确认的 Level 列表（锚 = 影线极值价，单线）。
    同一极值只确认一次；确认时刻 = 第 right 根右侧 bar 的 close_time。
    """

    def __init__(self, left=DEFAULT_SWING_LEFT, right=DEFAULT_SWING_RIGHT, band_fn=None):
        self.left = left
        self.right = right
        self.bars: List[Bar] = []
        self._confirmed_idx = set()
        self._seq = 0
        self.band_fn = band_fn or (lambda scale: Decimal("0.5") * scale if scale else Decimal("0"))

    def on_bar(self, bar: Bar, scale: Optional[Decimal]) -> List[Level]:
        self.bars.append(bar)
        out: List[Level] = []
        i = len(self.bars) - 1 - self.right  # 刚被右侧根数满足的候选极值下标
        if i < self.left or i in self._confirmed_idx:
            return out
        cand = self.bars[i]
        lefts = self.bars[i - self.left:i]
        rights = self.bars[i + 1:]
        band = self.band_fn(scale)
        if all(cand.high > b.high for b in lefts + rights):
            self._confirmed_idx.add(i)
            self._seq += 1
            out.append(make_level(f"SW-H-{self._seq}", cand.high, cand.high, kind="swing",
                                  source=f"swing_high left={self.left} right={self.right}",
                                  available_at=bar.close_time, confirmed_at=bar.close_time,
                                  band=band, direction_hint="down"))
        elif all(cand.low < b.low for b in lefts + rights):
            self._confirmed_idx.add(i)
            self._seq += 1
            out.append(make_level(f"SW-L-{self._seq}", cand.low, cand.low, kind="swing",
                                  source=f"swing_low left={self.left} right={self.right}",
                                  available_at=bar.close_time, confirmed_at=bar.close_time,
                                  band=band, direction_hint="up"))
        return out


def make_target(target_id, price, *, formula, anchor_refs, created_at, available_at) -> Target:
    return Target(target_id=target_id, price=D(price), formula=formula,
                  anchor_refs=tuple(anchor_refs), created_at=int(created_at),
                  available_at=int(available_at))
