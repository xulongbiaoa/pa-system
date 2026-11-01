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

from .actions import Segment, fully_outside_band, inside_band, touched
from .contracts import Bar, Event, Level, Target
from .facts import BarFacts, compute_facts
from .terrain import CloseZigzagDetector, SwingDetector

TEST_REJECTION_PROXY = "full_bar_leave_band"

# 只有这些来源的位置有资格开缺口账（定版 v0.2，2026-11-01 对齐线索C
# 《缺口篇 上》）：波段点 = 收盘折线拐点（zigzag）、强突破的起点
# （origin，挂在起点拐点 level 上）、人工审定锚。影线分形（swing /
# 旧 swing_major）只作地形，不立账——分形在相近价位多顶几次就多
# 确认几个点、每个被破各立一座，是旧账本相邻簇与陈年堆积的病根。
GAP_ELIGIBLE_KINDS = ("manual", "gap_anchor", "zigzag", "origin")


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
    origin: bool = False                  # True = 强突破起点缺口（定版 v0.2 第二种锚）


class Battlefield:
    """单标的、单周期、已收盘 K 线的翻译内核。不调用模型。"""

    def __init__(self, symbol: str, timeframe: str, timeframe_ms: int,
                 enable_swings: bool = False, swing_specs=None, zigzag: bool = False,
                 zigzag_reversal=None):
        """swing_specs: [(left, right, kind, name_prefix), ...]；enable_swings=True
        且未给 specs 时只装 minor (2,2) 摆动（兼容旧测试）。
        zigzag=True 时装收盘折线拐点检测器（定版 v0.2 的波段点来源）；
        zigzag_reversal 覆盖拐点确认的回撤门槛（尺度倍数，默认 3.0）。"""
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
        self._zigzag = (CloseZigzagDetector(reversal=zigzag_reversal)
                        if zigzag and zigzag_reversal is not None
                        else CloseZigzagDetector() if zigzag else None)
        self._pivots: List[dict] = []        # 已确认拐点序列（交替 H/L）
        self._pivot_index: Dict[str, int] = {}   # level_key -> 拐点序号（入账窗口判定）
        self._origin_done: set = set()       # 已立过起点账的起点 level_key

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
        # 收盘折线拐点（定版 v0.2 波段点；拐点序列同时定义腿与起点）
        if self._zigzag is not None:
            for lv in self._zigzag.on_bar(bar, facts.scale):
                self.register_level(lv)
                self._pivot_index[lv.key()] = len(self._pivots)
                self._pivots.append({"which": "H" if "-H-" in lv.level_id else "L",
                                     "level_key": lv.key(), "anchor": lv.anchor})
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
        # 起点缺口（定版 v0.2）：当前腿收盘破掉前一反向拐点 = 强突破，
        # 在该腿起点拐点的背向极值处同时开账（上破取起点 K 低点、
        # 下破取起点 K 高点——即起点拐点 level 自身的锚）
        if len(self._pivots) >= 2:
            origin, opposing = self._pivots[-1], self._pivots[-2]
            okey = origin["level_key"]
            if okey not in self._origin_done:
                if origin["which"] == "L" and bar.close > opposing["anchor"]:
                    self._book_origin(origin, bar, "up", out)
                elif origin["which"] == "H" and bar.close < opposing["anchor"]:
                    self._book_origin(origin, bar, "down", out)
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
        closed_this_bar = False
        gap = self.gaps.get(rt.gap_id) if rt.gap_id else None
        if gap is not None and gap.status == "open" and touched(bar, anchor, anchor):
            gap.status = "closed"
            gap.closed_bar = bar.id
            closed_this_bar = True
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

        # 4) 收盘破锚 -> 缺口立账（定版 v0.2「破掉即开账」：attempt 已由
        #    收盘穿越启动，本根收盘仍在锚外即开账；取代旧「整根分离」代理。
        #    假突破随后碰回锚线即销账——活了几根的短命缺口，定版认可。）
        gap = self.gaps.get(rt.gap_id) if rt.gap_id else None
        if gap is None and not closed_this_bar and lv.kind in GAP_ELIGIBLE_KINDS \
                and self._in_booking_window(lv):
            if rt.attempt_dir == "up" and bar.close > anchor:
                self._book_gap(rt, bar, "up", out, extra)
            elif rt.attempt_dir == "down" and bar.close < anchor:
                self._book_gap(rt, bar, "down", out, extra)

        # 5) 回补测试：从缺口侧整根在带外 -> 进入带内 = 一次测试开始；
        #    整根离开带回到缺口侧 = 该次测试结束（代理：拒绝确认）。
        gap = self.gaps.get(rt.gap_id) if rt.gap_id else None
        if gap is not None and gap.status == "open":
            gap_side = "up" if gap.direction == "up" else "down"
            if not rt.test_open and rt.band_side == gap_side and in_band:
                self._test_seq += 1
                rt.test_open = True
                # 全场流水仅作内部身份：禁止 T 前缀——单缺口测试编号只有
                # test_index 一套（1..test_count），两套 T 编号并存曾让判读员
                # 照抄流水号写错简报（2026-10-31 拒收事件）。
                rt.test_id = f"X{self._test_seq}"
                rt.test_from_side = gap_side
                gap.test_count += 1
                rec = {"test_id": rt.test_id, "test_index": gap.test_count,
                       "gap_id": gap.gap_id, "started_bar": bar.id,
                       "outcome": "open", "proxy": None}
                gap.tests.append(rec)
                out.append(self._emit("TEST_STARTED", bar, level_key=key,
                                      direction=gap.direction,
                                      payload={"gap_id": gap.gap_id, "test_id": rt.test_id,
                                               "test_index": gap.test_count}))
            elif rt.test_open and side_now == gap_side:
                ended_id = rt.test_id
                self._end_test(rt, gap, bar, outcome="rejected_proxy")
                out.append(self._emit("TEST_ENDED", bar, level_key=key,
                                      direction=gap.direction,
                                      payload={"gap_id": gap.gap_id, "test_id": ended_id,
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

    def _in_booking_window(self, lv: Level) -> bool:
        """入账窗口（定版 v0.2 入账门槛的机械化）：只有当前波段结构内的
        拐点能立新账——即最近 3 个已确认拐点；更早的拐点线只作地形，
        其已开的账继续追踪到销账为止，但不再因反复穿越重复立账。
        人工/审定锚不受窗口限制。"""
        idx = self._pivot_index.get(lv.key())
        if idx is None:
            return True
        return idx >= len(self._pivots) - 3

    def _book_gap(self, rt: LevelRuntime, bar: Bar, direction: str,
                  out: List[Event], extra: dict, *, origin: bool = False) -> str:
        lv = rt.level
        # 一条锚线只有一座账（定版：一条缺口 = 一条锚线）：同价（或
        # 0.25 尺度内）已有开放缺口时不重复立账——同一道城墙在不同
        # 时段被重新顶到同价，是同一批被套者的位置，不是两座缺口
        eps = (self._last_scale or Decimal("0")) * Decimal("0.25")
        for g in self.gaps.values():
            if g.status == "open" and abs(g.anchor - lv.anchor) <= eps:
                return g.gap_id
        self._gap_seq += 1
        gid = f"GAP-{lv.level_id}-{self._gap_seq}"
        self.gaps[gid] = GapRecord(gap_id=gid, level_key=lv.key(), direction=direction,
                                   anchor=lv.anchor, opened_bar=bar.id, origin=origin)
        rt.gap_id = gid
        rt.separated = True
        out.append(self._emit("SEPARATED", bar, level_key=lv.key(), direction=direction,
                              payload={**extra}))
        payload = {"gap_id": gid, "anchor": str(lv.anchor)}
        if origin:
            payload["origin"] = True
        out.append(self._emit("GAP_OPENED", bar, level_key=lv.key(), direction=direction,
                              payload=payload))
        return gid

    def _book_origin(self, origin: dict, bar: Bar, direction: str,
                     out: List[Event]) -> None:
        okey = origin["level_key"]
        self._origin_done.add(okey)
        rt = self.levels.get(okey)
        if rt is None or rt.gap_id is not None:
            return
        self._book_gap(rt, bar, direction, out, {}, origin=True)

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
                 "next_test_index": g.test_count + 1, "origin": g.origin,
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
