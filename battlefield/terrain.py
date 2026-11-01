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

    def __init__(self, left=DEFAULT_SWING_LEFT, right=DEFAULT_SWING_RIGHT, band_fn=None,
                 kind="swing", name_prefix="SW"):
        self.left = left
        self.right = right
        self.bars: List[Bar] = []
        self._confirmed_idx = set()
        self._seq = 0
        self.kind = kind
        self.name_prefix = name_prefix
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
            out.append(make_level(f"{self.name_prefix}-H-{self._seq}", cand.high, cand.high,
                                  kind=self.kind,
                                  source=f"swing_high left={self.left} right={self.right}",
                                  available_at=bar.close_time, confirmed_at=bar.close_time,
                                  band=band, direction_hint="down"))
        elif all(cand.low < b.low for b in lefts + rights):
            self._confirmed_idx.add(i)
            self._seq += 1
            out.append(make_level(f"{self.name_prefix}-L-{self._seq}", cand.low, cand.low,
                                  kind=self.kind,
                                  source=f"swing_low left={self.left} right={self.right}",
                                  available_at=bar.close_time, confirmed_at=bar.close_time,
                                  band=band, direction_hint="up"))
        return out


class CloseZigzagDetector:
    """收盘折线拐点（定版 v0.2 波段点认法，2026-11-01 对齐线索C《缺口篇 上》）。

    只盯收盘价折线：跟踪运行极值（最高/最低收盘），收盘自极值反向回撤
    >= reversal * 尺度才确认拐点——一段波段只有一个拐点，相邻小折腾
    不成点（影线分形在相近价位多顶几次就多确认几个点，是旧口径的病）。
    拐点 K = 极值收盘所在根，锚价取其影线极值；确认时刻 = 回撤达标
    那根的收盘（因果，禁止回溯）。reversal=3.0 是工程代理：把视频里
    肉眼认的「一段波段」量化为至少 3 根典型波幅（尺度）的腿——实测
    1.0 时 1,088 根里出 169 个拐点（每 6 根一个，仍是噪音），3.0 时
    43 个，腿的尺度才与视频里逐段标的波段相当。
    """

    def __init__(self, reversal=Decimal("3.0"), band_fn=None,
                 kind="zigzag", name_prefix="ZG"):
        self.reversal = D(reversal)
        self.band_fn = band_fn or (lambda scale: Decimal("0.5") * scale if scale else Decimal("0"))
        self.kind = kind
        self.name_prefix = name_prefix
        self._seq = 0
        self._dir: Optional[str] = None
        self._ext_close: Optional[Decimal] = None
        self._ext_bar: Optional[Bar] = None

    def _confirm(self, which: str, bar: Bar, scale: Optional[Decimal]) -> Level:
        self._seq += 1
        pb = self._ext_bar
        band = self.band_fn(scale)
        if which == "H":
            return make_level(f"{self.name_prefix}-H-{self._seq}", pb.high, pb.high,
                              kind=self.kind,
                              source=f"close_zigzag pivot high rev={self.reversal}",
                              available_at=bar.close_time, confirmed_at=bar.close_time,
                              band=band, direction_hint="down")
        return make_level(f"{self.name_prefix}-L-{self._seq}", pb.low, pb.low,
                          kind=self.kind,
                          source=f"close_zigzag pivot low rev={self.reversal}",
                          available_at=bar.close_time, confirmed_at=bar.close_time,
                          band=band, direction_hint="up")

    def on_bar(self, bar: Bar, scale: Optional[Decimal]) -> List[Level]:
        out: List[Level] = []
        if self._ext_bar is None:
            self._ext_close, self._ext_bar = bar.close, bar
            return out
        if self._dir != "down" and bar.close > self._ext_close:
            self._ext_close, self._ext_bar = bar.close, bar
            if self._dir is None:
                self._dir = "up"
            return out
        if self._dir != "up" and bar.close < self._ext_close:
            self._ext_close, self._ext_bar = bar.close, bar
            if self._dir is None:
                self._dir = "down"
            return out
        if scale:
            if self._dir == "up" and self._ext_close - bar.close >= self.reversal * scale:
                out.append(self._confirm("H", bar, scale))
                self._dir = "down"
                self._ext_close, self._ext_bar = bar.close, bar
            elif self._dir == "down" and bar.close - self._ext_close >= self.reversal * scale:
                out.append(self._confirm("L", bar, scale))
                self._dir = "up"
                self._ext_close, self._ext_bar = bar.close, bar
        return out


def make_target(target_id, price, *, formula, anchor_refs, created_at, available_at) -> Target:
    return Target(target_id=target_id, price=D(price), formula=formula,
                  anchor_refs=tuple(anchor_refs), created_at=int(created_at),
                  available_at=int(available_at))
