"""虚拟战场翻译器 · 数据契约（W01）。

设计依据：《虚拟战场翻译器完整实施方案 v1》§4/§5。
原则：价格用 Decimal（入参为字符串），时间为 UTC epoch 毫秒，
bar_id 稳定 = source/symbol/timeframe/open_time。
本层只定义可观察事实的对象，不含任何交易语义推断。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


def D(x) -> Decimal:
    """统一 Decimal 构造：接受 str/int/Decimal，禁止 float 直入（精度）。"""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        raise TypeError("价格禁止 float 直入，用字符串")
    return Decimal(str(x))


@dataclass(frozen=True)
class Bar:
    symbol: str
    timeframe: str
    open_time: int          # UTC epoch ms
    close_time: int         # UTC epoch ms
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    source: str = "external"
    received_at: int = 0    # 系统接收序（epoch ms 或外部序号）
    data_revision: int = 1

    @property
    def id(self) -> str:
        return f"{self.source}/{self.symbol}/{self.timeframe}/{self.open_time}"

    def validate(self) -> None:
        if not (self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high):
            raise ValueError(f"OHLC 不合法: {self.id} O={self.open} H={self.high} L={self.low} C={self.close}")
        if self.close_time <= self.open_time:
            raise ValueError(f"close_time 必须晚于 open_time: {self.id}")

    def same_content(self, other: "Bar") -> bool:
        return (self.open, self.high, self.low, self.close) == (other.open, other.high, other.low, other.close)


def make_bar(symbol, timeframe, open_time, close_time, o, h, l, c,
             source="external", received_at=0, data_revision=1) -> Bar:
    bar = Bar(symbol=symbol, timeframe=timeframe, open_time=int(open_time),
              close_time=int(close_time), open=D(o), high=D(h), low=D(l), close=D(c),
              source=source, received_at=int(received_at), data_revision=int(data_revision))
    bar.validate()
    return bar


@dataclass(frozen=True)
class Snapshot:
    """一次输入的截止快照：查询与模型任务必须绑定它，禁止跨时刻混读。"""
    id: str
    cutoff_at: int
    observed_until: int
    bar_refs: tuple = ()
    completeness: str = "complete"   # complete | missing_bars | revision_conflict
    content_hash: str = ""


@dataclass
class Level:
    """地形：价格线/区域及来源。原始边界与观察带分开，改界 = 新版本。"""
    level_id: str
    version: int
    kind: str                       # manual | swing | gap_anchor | target | model_proposed
    lo: Decimal
    hi: Decimal
    watch_lo: Decimal
    watch_hi: Decimal
    source: str                     # 生成方法/来源说明
    source_available_at: int        # 该位置最早可被知道的时刻
    confirmed_at: int               # 确认时刻（摆动点须晚于极值 bar）
    direction_hint: Optional[str] = None

    @property
    def anchor(self) -> Decimal:
        """单线锚价：lo==hi 时即该线；区域时取中点仅作引用，判定仍用边界。"""
        return self.lo if self.lo == self.hi else (self.lo + self.hi) / 2

    def key(self) -> str:
        return f"{self.level_id}@v{self.version}"


@dataclass
class Target:
    """目标区域：事前可计算的投影/结构。没有提前注册的目标不许事后补写。"""
    target_id: str
    price: Decimal
    formula: str                    # 计算公式说明（如 MM: anchor + height）
    anchor_refs: tuple
    created_at: int
    available_at: int
    touched: bool = False
    touched_bar: Optional[str] = None


@dataclass
class Event:
    """事实事件日志条目。日志不可覆盖；修订只追加 correction。"""
    event_id: str
    type: str
    bar_id: str
    event_time: int                 # 行情发生时刻（bar close_time）
    confirmed_at: int               # 系统确认时刻（本版 = 该 bar 收盘）
    observed_at: int
    sequence: int                   # 全局单调序
    level_key: Optional[str] = None
    direction: Optional[str] = None  # up | down
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id, "type": self.type, "bar_id": self.bar_id,
            "event_time": self.event_time, "confirmed_at": self.confirmed_at,
            "observed_at": self.observed_at, "sequence": self.sequence,
            "level_key": self.level_key, "direction": self.direction,
            "payload": self.payload,
        }
