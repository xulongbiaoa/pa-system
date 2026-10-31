"""事件器 v1：追踪突破尝试及其后续结果（design/事件器设计-v1.md）。

纯函数 + 纯状态机：不读文件、不访问模型或交易所、不下任何买卖
结论。事件器只报事实（越界、收回、分离、回测），「突破是否有效」
「是否入场」归策略与 gate，本模块不改任何现行门槛。

口径要点（设计 §5/§6）：
- 越界/收回看原始边界 lo/hi；接近/测试/回测看观察带 watch_lo/hi；
  等于边界不算越界；检测不额外加隐含容差。
- 每个 level_version × direction 同时最多一个活跃尝试；attempt_id
  由位置版本、方向、首个越界 bar 确定性生成，重复投递不重复落账。
- 同根出现多个顺序敏感事件（开始/收回/回测）时统一标
  intrabar_order_unknown=True，不凭 OHLC 虚构先后（E02/E05/E08）。
- 冷启动不追认历史突破：没有前一根就不检测跨越；价格已在位外时
  只建立状态，后续整根回到带内再越界才算新尝试（E09）。
- away（整根位于观察带外侧）由 advance 按 bar 几何确定性重算；
  retest_sequence 只在「已分离且曾 away → 返回观察带」时递增，
  同次测试内连续触及不递增（E11）。模型复核计数不在本模块。

用法：每根新收盘 K 线先 detect_price_events(prev, cur, level,
tracker)，再 advance_attempt(tracker, events, bar=cur, level=level)
推进状态。advance 按 event_id 幂等（E10）。

与设计接口的偏差（有意、已登记）：设计写单尝试入参；实现用
AttemptTracker 同时持有上下两个方向，一次调用处理双向（E08 需要），
语义与逐方向调用等价。
"""

from dataclasses import dataclass, field

ZONE_TOUCHED = "ZONE_TOUCHED"
UPSIDE_ATTEMPT_STARTED = "UPSIDE_ATTEMPT_STARTED"
DOWNSIDE_ATTEMPT_STARTED = "DOWNSIDE_ATTEMPT_STARTED"
CLOSE_OUTSIDE_UP = "CLOSE_OUTSIDE_UP"
CLOSE_OUTSIDE_DOWN = "CLOSE_OUTSIDE_DOWN"
UPSIDE_RECLAIMED = "UPSIDE_RECLAIMED"
DOWNSIDE_RECLAIMED = "DOWNSIDE_RECLAIMED"
OUTSIDE_SEPARATED_UP = "OUTSIDE_SEPARATED_UP"
OUTSIDE_SEPARATED_DOWN = "OUTSIDE_SEPARATED_DOWN"
RETEST_STARTED = "RETEST_STARTED"

STARTED = "STARTED"
OUTSIDE_TRACKING = "OUTSIDE_TRACKING"
RETESTING = "RETESTING"
RECLAIMED = "RECLAIMED"
SUPERSEDED = "SUPERSEDED"
EXPIRED = "EXPIRED"
TERMINAL = (RECLAIMED, SUPERSEDED, EXPIRED)

_SEQ_TYPES = (UPSIDE_ATTEMPT_STARTED, DOWNSIDE_ATTEMPT_STARTED,
              UPSIDE_RECLAIMED, DOWNSIDE_RECLAIMED, RETEST_STARTED)
_START_TYPES = (UPSIDE_ATTEMPT_STARTED, DOWNSIDE_ATTEMPT_STARTED)
_RECLAIM_TYPES = (UPSIDE_RECLAIMED, DOWNSIDE_RECLAIMED)
_SEP_TYPES = (OUTSIDE_SEPARATED_UP, OUTSIDE_SEPARATED_DOWN)
_CLOSE_TYPES = (CLOSE_OUTSIDE_UP, CLOSE_OUTSIDE_DOWN)


@dataclass(frozen=True)
class WatchLevel:
    level_id: str
    level_version: int
    kind: str  # resistance | support | neutral
    lo: float
    hi: float
    watch_lo: float
    watch_hi: float
    source: str = "machine"  # machine | model | manual
    evidence_ids: tuple = ()
    source_cutoff_at: object = None
    available_at: object = None
    valid_until: object = None
    strategy_version: str = ""

    def __post_init__(self):
        if self.lo > self.hi:
            raise ValueError("lo 必须 <= hi")
        if self.watch_lo > self.lo or self.watch_hi < self.hi:
            raise ValueError("观察带必须覆盖原始位置 [lo, hi]")


@dataclass(frozen=True)
class PriceEvent:
    event_id: str
    level_id: str
    level_version: int
    attempt_id: object  # 无关联时 None（如 ZONE_TOUCHED）
    bar_id: object
    event_time: object
    observed_at: object
    snapshot_id: object
    direction: object  # up | down | None
    type: str
    intrabar_order_unknown: bool = False


@dataclass
class Attempt:
    attempt_id: str
    level_id: str
    level_version: int
    direction: str  # up | down
    state: str = STARTED
    started_bar_id: object = None
    previous_attempt_id: object = None
    retest_sequence: int = 0
    separated_once: bool = False
    away: bool = False
    reclaimed: bool = False


@dataclass
class AttemptTracker:
    """一个 level_version 的双向活跃尝试 + 已消费事件（幂等）。"""
    up: object = None
    down: object = None
    last_up_attempt_id: object = None
    last_down_attempt_id: object = None
    applied_event_ids: set = field(default_factory=set)

    def active(self, direction):
        a = self.up if direction == "up" else self.down
        return a if a is not None and a.state not in TERMINAL else None


def attempt_id_for(level, direction, bar_id):
    return f"{level.level_id}@v{level.level_version}:{direction}:{bar_id}"


def _fully_out(bar, level, direction):
    return bar["l"] > level.watch_hi if direction == "up" \
        else bar["h"] < level.watch_lo


def _event(level, bar, type_, direction, attempt_id, snapshot_id):
    bar_id = bar["t"]
    eid = f"{level.level_id}@v{level.level_version}:{bar_id}:{type_}:{direction or '-'}"
    return PriceEvent(event_id=eid, level_id=level.level_id,
                      level_version=level.level_version, attempt_id=attempt_id,
                      bar_id=bar_id, event_time=bar_id, observed_at=bar_id,
                      snapshot_id=snapshot_id, direction=direction, type=type_)


def _direction_events(prev, cur, level, tracker, direction, snapshot_id):
    """单方向事件检测（只读 tracker，状态迁移归 advance）。"""
    if direction == "up":
        edge, watch_edge = level.hi, level.watch_hi
        start_t, close_t, reclaim_t, sep_t = (
            UPSIDE_ATTEMPT_STARTED, CLOSE_OUTSIDE_UP,
            UPSIDE_RECLAIMED, OUTSIDE_SEPARATED_UP)
        crossed = cur["h"] > edge
        prev_inside = prev["c"] <= edge
        close_out = cur["c"] > edge
        close_in = cur["c"] <= edge
        touches_watch = cur["l"] <= watch_edge
    else:
        edge, watch_edge = level.lo, level.watch_lo
        start_t, close_t, reclaim_t, sep_t = (
            DOWNSIDE_ATTEMPT_STARTED, CLOSE_OUTSIDE_DOWN,
            DOWNSIDE_RECLAIMED, OUTSIDE_SEPARATED_DOWN)
        crossed = cur["l"] < edge
        prev_inside = prev["c"] >= edge
        close_out = cur["c"] < edge
        close_in = cur["c"] >= edge
        touches_watch = cur["h"] >= watch_edge
    fully_out = _fully_out(cur, level, direction)

    out = []
    active = tracker.active(direction)
    if active is None:
        if prev_inside and crossed:
            aid = attempt_id_for(level, direction, cur["t"])
            out.append(_event(level, cur, start_t, direction, aid, snapshot_id))
            if close_out:
                out.append(_event(level, cur, close_t, direction, aid, snapshot_id))
            if fully_out:
                out.append(_event(level, cur, sep_t, direction, aid, snapshot_id))
            if close_in:
                out.append(_event(level, cur, reclaim_t, direction, aid, snapshot_id))
        return out

    aid = active.attempt_id
    if active.separated_once and active.away and touches_watch \
            and active.state != RETESTING:
        out.append(_event(level, cur, RETEST_STARTED, direction, aid, snapshot_id))
    if close_out:
        out.append(_event(level, cur, close_t, direction, aid, snapshot_id))
    if fully_out and not active.separated_once:
        out.append(_event(level, cur, sep_t, direction, aid, snapshot_id))
    if close_in and not active.reclaimed:
        out.append(_event(level, cur, reclaim_t, direction, aid, snapshot_id))
    return out


def detect_price_events(previous_bar, current_bar, level, tracker,
                        snapshot_id=None):
    """对一根新收盘 K 线检测事实事件。previous_bar 为 None 时不检测
    跨越（冷启动不追认历史突破）。"""
    if previous_bar is None or current_bar is None:
        return ()
    events = []
    if current_bar["l"] <= level.watch_hi and current_bar["h"] >= level.watch_lo:
        events.append(_event(level, current_bar, ZONE_TOUCHED, None, None,
                             snapshot_id))
    for direction in ("up", "down"):
        events.extend(_direction_events(previous_bar, current_bar, level,
                                        tracker, direction, snapshot_id))
    seq = [e for e in events if e.type in _SEQ_TYPES]
    starts = [e for e in seq if e.type in _START_TYPES]
    unknown = len({e.type for e in seq}) > 1 or len(starts) > 1
    if unknown:
        seq_ids = {e.event_id for e in seq}
        events = [PriceEvent(**{**e.__dict__, "intrabar_order_unknown": True})
                  if e.event_id in seq_ids else e for e in events]
    return tuple(events)


def advance_attempt(tracker, events, bar=None, level=None):
    """把事件应用到 tracker，返回状态迁移记录 (attempt_id, from, to,
    event_id)。按 event_id 幂等：重复投递不产生第二次迁移（E10）。
    给出 bar+level 时按几何重算 away；RETESTING 中整根重新离开观察
    带 → 回 OUTSIDE_TRACKING，下一次返回才是新的 retest（E11）。"""
    transitions = []
    for e in events:
        if e.event_id in tracker.applied_event_ids:
            continue
        tracker.applied_event_ids.add(e.event_id)
        if e.direction not in ("up", "down") or e.attempt_id is None:
            continue
        if e.type in _START_TYPES:
            prev_id = tracker.last_up_attempt_id if e.direction == "up" \
                else tracker.last_down_attempt_id
            att = Attempt(attempt_id=e.attempt_id, level_id=e.level_id,
                          level_version=e.level_version, direction=e.direction,
                          state=STARTED, started_bar_id=e.bar_id,
                          previous_attempt_id=prev_id)
            if e.direction == "up":
                tracker.up, tracker.last_up_attempt_id = att, att.attempt_id
            else:
                tracker.down, tracker.last_down_attempt_id = att, att.attempt_id
            transitions.append((att.attempt_id, None, STARTED, e.event_id))
            continue
        att = tracker.active(e.direction)
        if att is None or att.attempt_id != e.attempt_id:
            continue
        frm = att.state
        if e.type in _CLOSE_TYPES:
            if att.state == STARTED:
                att.state = OUTSIDE_TRACKING
        elif e.type in _SEP_TYPES:
            att.separated_once = True
            if att.state in (STARTED, RETESTING):
                att.state = OUTSIDE_TRACKING
        elif e.type == RETEST_STARTED:
            att.state = RETESTING
            att.retest_sequence += 1
        elif e.type in _RECLAIM_TYPES:
            att.reclaimed = True
            att.state = RECLAIMED
        if att.state != frm:
            transitions.append((att.attempt_id, frm, att.state, e.event_id))
    if bar is not None and level is not None:
        for direction in ("up", "down"):
            att = tracker.active(direction)
            if att is None or not att.separated_once:
                continue
            att.away = _fully_out(bar, level, direction)
            if att.state == RETESTING and att.away:
                att.state = OUTSIDE_TRACKING
                transitions.append((att.attempt_id, RETESTING,
                                    OUTSIDE_TRACKING, None))
    return transitions
