"""确定性状态内核（W04 / 方案 §7/§8）。

逐根更新：validate -> facts -> detect -> reduce -> commit（repository 负责落盘）。
检测函数不修改输入状态；同根事件是部分有序集合，盘中先后不可知时标
intrabar_order_unknown。取消类/关账类事件优先：旧缺口同根被补又反弹，先记已补。

测试计数口径（方案 §6.6）：回补测试按“完整靠近—离开—返回”划分，
不按连续几根 near bar 计数；两次模型调用不等于二测。
“整根离开观察带即确认拒绝”是具名工程代理政策 TEST_REJECTION_PROXY，
不自动等同专家定义，只记为代理结果，判读层仍可质疑。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

from .actions import Segment, fully_outside_band, inside_band, separated_above, separated_below, touched
from .contracts import Bar, Event, Level, Target
from .facts import BarFacts, compute_facts
from .terrain import SwingDetector

TEST_REJECTION_PROXY = "full_bar_leave_band"

# 只有这些来源的位置有资格开缺口账（缺口定义 v0.2 入账范围：据点/要塞上下沿的
# 波段点 + 人工审定锚）。minor 摆动只作地形，不立账——否则账本被小摆动淹没。
GAP_ELIGIBLE_KINDS = ("manual", "gap_anchor", "swing_major")


@dataclass
class LevelRuntime:
    level: Level
    attempt_dir: Optional[str] = None
    attempt_segment: Optional[str] = None
    separated: bool = False               # 本次 attempt 是否已整根分离
    gap_id: Optional[str] = None          # 当前开放缺口
    test_open: bool = False
    test_id: Optional[str] = None
    test_from_side: Optional[str] = None
    band_side: Optional[str] = None       # 最近一次整根离开带的方向（up/down）
    dirs_seen: set = field(default_factory=set)
    event_refs: dict = field(default_factory=lambda: {"up": [], "down": []})


@dataclass
class GapRecord:
    gap_id: str
    level_key: str
    direction: str                        # up gap = 向上突破后留在锚上方
    anchor: Decimal
    opened_bar: str
    status: str = "open"                  # open | closed
    closed_bar: Optional[str] = None
    test_count: int = 0
    tests: List[dict] = field(default_factory=list)


class Battlefield:
    """单标的、单周期、已收盘 K 线的翻译内核。不调用模型。"""

    def __init__(self, symbol: str, timeframe: str, timeframe_ms: int,
                 enable_swings: bool = False, swing_specs=None):
        """swing_specs: [(left, right, kind, name_prefix), ...]；enable_swings=True
        且未给 specs 时只装 minor (2,2) 摆动（兼容旧测试）。"""
        self.symbol = symbol
        self.timeframe = timeframe
        self.timeframe_ms = int(timeframe_ms)
        self.revision = 0
        self.cursor: Optional[int] = None        # 已处理到的 close_time
        self.data_revision = 1
        self.bars: List[Bar] = []
        self.bars_by_id: Dict[str, Bar] = {}
        self.facts_by_id: Dict[str, BarFacts] = {}
        self.levels: Dict[str, LevelRuntime] = {}
        self.gaps: Dict[str, GapRecord] = {}
        self.targets: Dict[str, Target] = {}
        self.segments: Dict[str, Segment] = {}
        self.events: List[Event] = []
        self.unresolved: List[dict] = []
        self.data_health: dict = {"missing_bars": 0, "continuity_broken": False,
                                  "revision_conflicts": 0, "late_bars": 0}
        self.hypotheses: List[dict] = []         # 与事实分区：只存提案，见 queries/proposals
        self.watch_plans: List[dict] = []
        self.candidate_proposals: List[dict] = []  # 候选提案分区：不是事实，也不等于订单
        self._seq = 0
        self._seg_seq = 0
        self._gap_seq = 0
        self._test_seq = 0
        self._prev_close: Optional[Decimal] = None
        self._last_scale: Optional[Decimal] = None
        if swing_specs:
            self._swings = [SwingDetector(left=l, right=r, kind=k, name_prefix=p)
                            for (l, r, k, p) in swing_specs]
        elif enable_swings:
            self._swings = [SwingDetector()]
        else:
            self._swings = []

    # ---------- 注册 ----------
    def register_level(self, level: Level) -> None:
        self.levels[level.key()] = LevelRuntime(level=level)

    def register_target(self, target: Target) -> None:
        self.targets[target.target_id] = target

    # ---------- 事件 ----------
    def _emit(self, type_, bar, *, level_key=None, direction=None, payload=None) -> Event:
        self._seq += 1
        ev = Event(event_id=f"ev-{self._seq}", type=type_, bar_id=bar.id,
                   event_time=bar.close_time, confirmed_at=bar.close_time,
                   observed_at=bar.received_at or bar.close_time,
                   sequence=self._seq, level_key=level_key,
                   direction=direction, payload=payload or {})
        self.events.append(ev)
        if level_key and level_key in self.levels and direction in ("up", "down"):
            self.levels[level_key].event_refs[direction].append(ev.event_id)
        return ev

    # ---------- 逐根推进 ----------
    def process_bar(self, bar: Bar) -> List[Event]:
        bar.validate()
        if self.bars and bar.open_time <= self.bars[-1].open_time:
            raise ValueError(f"bar 时序错误（迟到/重复应由 repository 分流）: {bar.id}")
        out: List[Event] = []
        # 缺根：不跨缺口认定连续性
        if self.bars and self.timeframe_ms > 0:
            expected = self.bars[-1].open_time + self.timeframe_ms
            if bar.open_time > expected:
                missing = (bar.open_time - expected) // self.timeframe_ms
                self.data_health["missing_bars"] += int(missing)
                self.data_health["continuity_broken"] = True
                self.unresolved.append({"kind": "missing_bars", "count": int(missing),
                                        "before_bar": bar.id})
                out.append(self._emit("DATA_GAP", bar, payload={"missing": int(missing)}))
        facts = compute_facts(self.bars, bar)
        self.facts_by_id[bar.id] = facts
        self._last_scale = facts.scale
        # 摆动地形（确认时刻纪律在 SwingDetector 内）
        for det in self._swings:
            for lv in det.on_bar(bar, facts.scale):
                self.register_level(lv)
                out.append(self._emit("LEVEL_CONFIRMED", bar, level_key=lv.key(),
                                      direction=lv.direction_hint,
                                      payload={"source": lv.source, "anchor": str(lv.anchor)}))
        self.bars.append(bar)
        self.bars_by_id[bar.id] = bar
        # 各位置状态机
        for key, rt in self.levels.items():
            if bar.close_time < rt.level.source_available_at:
                continue
            out.extend(self._advance_level(rt, bar, facts))
        # 目标触及
        for t in self.targets.values():
            if not t.touched and bar.close_time >= t.available_at and bar.low <= t.price <= bar.high:
                t.touched = True
                t.touched_bar = bar.id
                out.append(self._emit("TARGET_TOUCHED", bar,
                                      payload={"target_id": t.target_id, "price": str(t.price)}))
        # 手工段
        for seg in self.segments.values():
            if seg.open and seg.level_key is None:
                seg.bar_ids.append(bar.id)
        self._prev_close = bar.close
        self.cursor = bar.close_time
        self.revision += 1
        return out

    # ---------- 单位置状态机 ----------
    def _advance_level(self, rt: LevelRuntime, bar: Bar, facts: BarFacts) -> List[Event]:
        lv = rt.level
        key = lv.key()
        out: List[Event] = []
        prev_close = self._prev_close
        anchor = lv.anchor
        both_sides = bar.low < lv.watch_lo and bar.high > lv.watch_hi
        extra = {"intrabar_order_unknown": True} if both_sides else {}

        # 1) 缺口关账优先（方案 §8：先记已补，不能为保留假设继续 open）
        gap = self.gaps.get(rt.gap_id) if rt.gap_id else None
        if gap is not None and gap.status == "open" and touched(bar, anchor, anchor):
            gap.status = "closed"
            gap.closed_bar = bar.id
            out.append(self._emit("GAP_CLOSED", bar, level_key=key,
                                  direction=gap.direction,
                                  payload={"gap_id": gap.gap_id, "anchor": str(anchor), **extra}))
            if rt.test_open:
                self._end_test(rt, gap, bar, outcome="anchor_touched")
            rt.gap_id = None
            rt.separated = False

        # 2) 触锚/触带
        if touched(bar, lv.lo, lv.hi):
            out.append(self._emit("LEVEL_TOUCHED", bar, level_key=key, payload={**extra}))
        in_band = inside_band(bar, lv.watch_lo, lv.watch_hi)
        side_now = None
        if fully_outside_band(bar, lv.watch_lo, lv.watch_hi, "up"):
            side_now = "up"
        elif fully_outside_band(bar, lv.watch_lo, lv.watch_hi, "down"):
            side_now = "down"

        # 3) Attempt 开始/收回（以收盘为准）
        if prev_close is not None:
            if rt.attempt_dir is None:
                if prev_close <= lv.hi and bar.close > lv.hi:
                    self._start_attempt(rt, bar, "up", out, extra)
                elif prev_close >= lv.lo and bar.close < lv.lo:
                    self._start_attempt(rt, bar, "down", out, extra)
            elif rt.attempt_dir == "up" and bar.close <= lv.hi:
                ev = self._emit("RECLAIMED", bar, level_key=key, direction="up",
                                payload={"attempt_segment": rt.attempt_segment, **extra})
                out.append(ev)
                # 收回是对方在该位置的反制成果：争夺自此成立
                rt.dirs_seen.add("down")
                rt.event_refs["down"].append(ev.event_id)
                self._close_segment(rt)
                rt.attempt_dir = None
                rt.separated = False
            elif rt.attempt_dir == "down" and bar.close >= lv.lo:
                ev = self._emit("RECLAIMED", bar, level_key=key, direction="down",
                                payload={"attempt_segment": rt.attempt_segment, **extra})
                out.append(ev)
                rt.dirs_seen.add("up")
                rt.event_refs["up"].append(ev.event_id)
                self._close_segment(rt)
                rt.attempt_dir = None
                rt.separated = False
        if rt.attempt_dir is not None and rt.attempt_segment:
            seg = self.segments[rt.attempt_segment]
            if bar.id not in seg.bar_ids:
                seg.bar_ids.append(bar.id)

        # 4) 分离 -> 缺口立账（anchor_separation：整根位于锚外且此前收盘已在锚外）
        gap = self.gaps.get(rt.gap_id) if rt.gap_id else None
        if rt.attempt_dir == "up" and not rt.separated and prev_close is not None \
                and prev_close > anchor and separated_above(bar, anchor):
            rt.separated = True
            out.append(self._emit("SEPARATED", bar, level_key=key, direction="up", payload={**extra}))
            if gap is None and lv.kind in GAP_ELIGIBLE_KINDS:
                self._gap_seq += 1
                gid = f"GAP-{lv.level_id}-{self._gap_seq}"
                self.gaps[gid] = GapRecord(gap_id=gid, level_key=key, direction="up",
                                           anchor=anchor, opened_bar=bar.id)
                rt.gap_id = gid
                out.append(self._emit("GAP_OPENED", bar, level_key=key, direction="up",
                                      payload={"gap_id": gid, "anchor": str(anchor)}))
        elif rt.attempt_dir == "down" and not rt.separated and prev_close is not None \
                and prev_close < anchor and separated_below(bar, anchor):
            rt.separated = True
            out.append(self._emit("SEPARATED", bar, level_key=key, direction="down", payload={**extra}))
            if gap is None and lv.kind in GAP_ELIGIBLE_KINDS:
                self._gap_seq += 1
                gid = f"GAP-{lv.level_id}-{self._gap_seq}"
                self.gaps[gid] = GapRecord(gap_id=gid, level_key=key, direction="down",
                                           anchor=anchor, opened_bar=bar.id)
                rt.gap_id = gid
                out.append(self._emit("GAP_OPENED", bar, level_key=key, direction="down",
                                      payload={"gap_id": gid, "anchor": str(anchor)}))

        # 5) 回补测试：从缺口侧整根在带外 -> 进入带内 = 一次测试开始；
        #    整根离开带回到缺口侧 = 该次测试结束（代理：拒绝确认）。
        gap = self.gaps.get(rt.gap_id) if rt.gap_id else None
        if gap is not None and gap.status == "open":
            gap_side = "up" if gap.direction == "up" else "down"
            if not rt.test_open and rt.band_side == gap_side and in_band:
                self._test_seq += 1
                rt.test_open = True
                rt.test_id = f"T{self._test_seq}"
                rt.test_from_side = gap_side
                gap.test_count += 1
                rec = {"test_id": rt.test_id, "gap_id": gap.gap_id, "started_bar": bar.id,
                       "outcome": "open", "proxy": None}
                gap.tests.append(rec)
                out.append(self._emit("TEST_STARTED", bar, level_key=key,
                                      direction=gap.direction,
                                      payload={"gap_id": gap.gap_id, "test_id": rt.test_id,
                                               "test_index": gap.test_count}))
            elif rt.test_open and side_now == gap_side:
                self._end_test(rt, gap, bar, outcome="rejected_proxy")
                out.append(self._emit("TEST_ENDED", bar, level_key=key,
                                      direction=gap.direction,
                                      payload={"gap_id": gap.gap_id, "test_id": rt.test_id,
                                               "outcome": "rejected_proxy",
                                               "proxy": TEST_REJECTION_PROXY}))
        if side_now is not None:
            if rt.band_side != side_now:
                name = "LEFT_BAND_UP" if side_now == "up" else "LEFT_BAND_DOWN"
                out.append(self._emit(name, bar, level_key=key, direction=side_now, payload={**extra}))
            rt.band_side = side_now
        elif in_band:
            if rt.band_side is not None:
                out.append(self._emit("RETURN_TO_BAND", bar, level_key=key, payload={**extra}))
            rt.band_side = None
        return out

    def _start_attempt(self, rt: LevelRuntime, bar: Bar, direction: str,
                       out: List[Event], extra: dict) -> None:
        rt.attempt_dir = direction
        rt.dirs_seen.add(direction)
        self._seg_seq += 1
        seg_id = f"SEG-{self._seg_seq}"
        seg = Segment(segment_id=seg_id, direction=direction, start_bar_id=bar.id,
                      p0=self._prev_close, s0=self._last_scale,
                      bar_ids=[bar.id], level_key=rt.level.key(), open=True)
        self.segments[seg_id] = seg
        rt.attempt_segment = seg_id
        out.append(self._emit("ATTEMPT_STARTED", bar, level_key=rt.level.key(),
                              direction=direction,
                              payload={"segment_id": seg_id, **extra}))

    def _close_segment(self, rt: LevelRuntime) -> None:
        if rt.attempt_segment and rt.attempt_segment in self.segments:
            self.segments[rt.attempt_segment].open = False
        rt.attempt_segment = None

    def _end_test(self, rt: LevelRuntime, gap: GapRecord, bar: Bar, *, outcome: str) -> None:
        for rec in gap.tests:
            if rec["test_id"] == rt.test_id and rec["outcome"] == "open":
                rec["outcome"] = outcome
                rec["ended_bar"] = bar.id
                if outcome == "rejected_proxy":
                    rec["proxy"] = TEST_REJECTION_PROXY
        rt.test_open = False
        rt.test_id = None
        rt.test_from_side = None

    # ---------- 手工段（对照/解释层用） ----------
    def open_segment(self, direction: str) -> str:
        self._seg_seq += 1
        seg_id = f"SEG-{self._seg_seq}"
        self.segments[seg_id] = Segment(segment_id=seg_id, direction=direction,
                                        start_bar_id=self.bars[-1].id if self.bars else "",
                                        p0=self._prev_close, s0=self._last_scale,
                                        bar_ids=[], level_key=None, open=True)
        return seg_id

    def close_segment_by_id(self, segment_id: str) -> None:
        self.segments[segment_id].open = False

    # ---------- 状态投影 ----------
    def state_dict(self) -> dict:
        levels = []
        for key, rt in self.levels.items():
            lv = rt.level
            levels.append({"level_key": key, "kind": lv.kind, "lo": str(lv.lo), "hi": str(lv.hi),
                           "watch_lo": str(lv.watch_lo), "watch_hi": str(lv.watch_hi),
                           "source": lv.source, "confirmed_at": lv.confirmed_at,
                           "attempt_dir": rt.attempt_dir, "open_gap": rt.gap_id,
                           "test_open": rt.test_open})
        gaps = [{"gap_id": g.gap_id, "level_key": g.level_key, "direction": g.direction,
                 "anchor": str(g.anchor), "opened_bar": g.opened_bar, "status": g.status,
                 "closed_bar": g.closed_bar, "test_count": g.test_count,
                 "tests": copy.deepcopy(g.tests)} for g in self.gaps.values()]
        targets = [{"target_id": t.target_id, "price": str(t.price), "formula": t.formula,
                    "anchor_refs": list(t.anchor_refs), "available_at": t.available_at,
                    "touched": t.touched, "touched_bar": t.touched_bar}
                   for t in self.targets.values()]
        contests = []
        for key, rt in self.levels.items():
            if rt.dirs_seen == {"up", "down"}:
                contests.append({"level_key": key,
                                 "up_events": list(rt.event_refs["up"]),
                                 "down_events": list(rt.event_refs["down"])})
        directional = {"up": [s.segment_id for s in self.segments.values() if s.direction == "up"],
                       "down": [s.segment_id for s in self.segments.values() if s.direction == "down"]}
        return {"symbol": self.symbol, "timeframe": self.timeframe,
                "revision": self.revision, "cursor": self.cursor,
                "data_revision": self.data_revision,
                "levels": levels, "gaps": gaps, "targets": targets,
                "segments": [{"segment_id": s.segment_id, "direction": s.direction,
                              "start_bar_id": s.start_bar_id, "level_key": s.level_key,
                              "open": s.open, "bar_ids": list(s.bar_ids)}
                             for s in self.segments.values()],
                "directional_activity": directional, "contests": contests,
                "active_hypotheses": copy.deepcopy(self.hypotheses),
                "watch_plans": copy.deepcopy(self.watch_plans),
                "candidate_proposals": copy.deepcopy(self.candidate_proposals),
                "unresolved": copy.deepcopy(self.unresolved),
                "data_health": dict(self.data_health)}
