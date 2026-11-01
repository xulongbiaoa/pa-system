"""行情接入（外部 K 线资源 -> Bar）。翻译内核不负责采集，这里只是薄适配。

数据源：Binance 公开行情镜像 data-api.binance.vision（与前向影子同一源）。
只取已收盘 K 线：接口最后一根可能未收盘，按服务器时间过滤掉。
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from typing import Iterable, List, Sequence

from .contracts import Bar, make_bar

BASE = "https://data-api.binance.vision"

TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
         "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}

DEFAULT_WINDOW_BARS = 96
DEFAULT_FETCH_MARGIN = 4


class InputIncompleteError(ValueError):
    """窗口不完整/不连续：本轮输入不合格，不允许构建供模型使用的战场。"""


class FeedError(RuntimeError):
    """行情接口或响应本身失败，与窗口完整性错误分开记录。"""


def parse_klines(raw: list, symbol: str, timeframe: str, now_ms: int) -> List[Bar]:
    """Binance kline 数组 -> Bar 列表（只保留 close_time <= now_ms 的已收盘根）。"""
    bars: List[Bar] = []
    for row in raw:
        open_time, close_time = int(row[0]), int(row[6])
        if close_time > now_ms:
            continue
        bars.append(make_bar(symbol, timeframe, open_time, close_time,
                             row[1], row[2], row[3], row[4],
                             source="binance-vision", received_at=now_ms))
    return bars


def fetch_klines(symbol: str, timeframe: str, limit: int = 300) -> List[Bar]:
    try:
        url = f"{BASE}/api/v3/klines?symbol={symbol}&interval={timeframe}&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "pa-battlefield/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        time_url = f"{BASE}/api/v3/time"
        with urllib.request.urlopen(time_url, timeout=15) as resp:
            now_ms = int(json.loads(resp.read().decode("utf-8"))["serverTime"])
    except Exception as exc:
        raise FeedError(f"Binance 行情拉取失败: {type(exc).__name__}: {exc}") from exc
    if not isinstance(raw, list):
        raise FeedError("Binance 行情响应不是数组")
    return parse_klines(raw, symbol, timeframe, now_ms)


def window_input_hash(bars: Sequence[Bar]) -> str:
    """窗口输入指纹：绑定标的/周期与每根 OHLC/时间/修订，禁止只凭尾根判断同一窗。"""
    payload = [{
        "symbol": b.symbol, "timeframe": b.timeframe,
        "open_time": b.open_time, "close_time": b.close_time,
        "open": str(b.open), "high": str(b.high), "low": str(b.low),
        "close": str(b.close), "source": b.source,
        "data_revision": b.data_revision,
    } for b in bars]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_closed_window(bars: Iterable[Bar], symbol: str, timeframe: str,
                           expected_count: int = DEFAULT_WINDOW_BARS,
                           timeframe_ms: int | None = None) -> List[Bar]:
    """校验一个可供模型使用的已收盘窗口。

    合格条件：恰好 expected_count 根；标的/周期一致；open_time 严格递增且
    每根间隔恰为 timeframe_ms；每根都落在周期边界上；close_time 与该根周期
    终点一致（兼容 Binance 的 open+周期-1 与内部合成数据的 open+周期）。
    任一条件不满足都抛 InputIncompleteError，调用方不得降级使用残缺窗口。
    """
    tf_ms = timeframe_ms or TF_MS.get(timeframe)
    if not tf_ms:
        raise InputIncompleteError(f"未知周期: {timeframe}")
    window = list(bars)
    if len(window) != expected_count:
        raise InputIncompleteError(
            f"窗口根数不符: got={len(window)} expected={expected_count}")
    prev_open = None
    close_style = None
    for i, bar in enumerate(window):
        if bar.symbol != symbol or bar.timeframe != timeframe:
            raise InputIncompleteError(
                f"第 {i} 根标的/周期不符: {bar.symbol}/{bar.timeframe}")
        try:
            bar.validate()
        except ValueError as exc:
            raise InputIncompleteError(str(exc)) from exc
        if bar.open_time % tf_ms != 0:
            raise InputIncompleteError(
                f"第 {i} 根 open_time 不在 {timeframe} 边界: {bar.open_time}")
        style = bar.close_time - bar.open_time
        if style not in (tf_ms - 1, tf_ms):
            raise InputIncompleteError(
                f"第 {i} 根 close_time 与周期不符: {bar.open_time}->{bar.close_time}")
        if close_style is None:
            close_style = style
        elif style != close_style:
            raise InputIncompleteError("窗口内 close_time 口径不一致")
        if prev_open is not None and bar.open_time != prev_open + tf_ms:
            raise InputIncompleteError(
                f"窗口不连续: 第 {i} 根 open_time={bar.open_time}，"
                f"期望 {prev_open + tf_ms}")
        prev_open = bar.open_time
    return window


def select_closed_window(bars: Iterable[Bar], symbol: str, timeframe: str,
                         expected_count: int = DEFAULT_WINDOW_BARS,
                         timeframe_ms: int | None = None) -> List[Bar]:
    """从带余量的已收盘序列尾部选最近 expected_count 根，并做完整性校验。

    只从尾部切片，不向前跨越缺口补根：最近窗口只要缺一根就明确失败。
    """
    ordered = sorted(bars, key=lambda b: b.open_time)
    if len(ordered) < expected_count:
        raise InputIncompleteError(
            f"已收盘根不足: got={len(ordered)} expected={expected_count}")
    return validate_closed_window(ordered[-expected_count:], symbol, timeframe,
                                  expected_count=expected_count,
                                  timeframe_ms=timeframe_ms)


def fetch_closed_window(symbol: str, timeframe: str = "15m",
                        expected_count: int = DEFAULT_WINDOW_BARS,
                        margin: int = DEFAULT_FETCH_MARGIN) -> List[Bar]:
    """拉取带余量的已收盘 K 线，返回校验通过的最近完整窗口。"""
    bars = fetch_klines(symbol, timeframe, limit=expected_count + max(0, margin))
    return select_closed_window(bars, symbol, timeframe,
                                expected_count=expected_count,
                                timeframe_ms=TF_MS.get(timeframe))


def validate_chain(bars: Iterable[Bar], symbol: str, timeframe: str,
                   timeframe_ms: int | None = None) -> List[Bar]:
    """校验一串已收盘 Bar 自身连续：标的/周期一致、边界对齐、逐根间隔恰为
    一个周期、顺序严格递增。长度任意（>=1）。乱序/缺根/错位一律显式报错。"""
    tf_ms = timeframe_ms or TF_MS.get(timeframe)
    if not tf_ms:
        raise InputIncompleteError(f"未知周期: {timeframe}")
    chain = list(bars)
    if not chain:
        raise InputIncompleteError("空 Bar 序列")
    prev_open = None
    for i, bar in enumerate(chain):
        if bar.symbol != symbol or bar.timeframe != timeframe:
            raise InputIncompleteError(
                f"第 {i} 根标的/周期不符: {bar.symbol}/{bar.timeframe}")
        try:
            bar.validate()
        except ValueError as exc:
            raise InputIncompleteError(str(exc)) from exc
        if bar.open_time % tf_ms != 0:
            raise InputIncompleteError(
                f"第 {i} 根 open_time 不在 {timeframe} 边界: {bar.open_time}")
        if prev_open is not None and bar.open_time != prev_open + tf_ms:
            raise InputIncompleteError(
                f"序列不连续/乱序: 第 {i} 根 open_time={bar.open_time}，"
                f"期望 {prev_open + tf_ms}")
        prev_open = bar.open_time
    return chain


def plan_increment(existing: Sequence[Bar], fetched: Sequence[Bar],
                   timeframe_ms: int) -> List[Bar]:
    """连续账本增量规划：给定账本已有 Bar 与新拉取的已收盘 Bar，算出可追加
    的新 Bar 列表。规则（任一违反 = InputIncompleteError，显式停机）：
    - fetched 本身必须顺序严格递增（乱序不重排掩盖）；
    - 与账本重叠的 Bar 必须同 ID 同内容（修订冲突报错）；
    - 第一个新 Bar 必须恰好接在账本尾根之后，中间缺根报错；
    - 新 Bar 之间逐根连续。
    账本为空时，fetched 校验为一条连续链后全量返回（种子）。"""
    if fetched:
        opens = [b.open_time for b in fetched]
        if any(b <= a for a, b in zip(opens, opens[1:])):
            raise InputIncompleteError("拉取序列乱序：open_time 非严格递增")
    if not existing:
        return validate_chain(fetched, fetched[0].symbol if fetched else "",
                              fetched[0].timeframe if fetched else "",
                              timeframe_ms) if fetched else []
    known = {b.open_time: b for b in existing}
    tail_open = existing[-1].open_time
    new_bars: List[Bar] = []
    expected = tail_open + timeframe_ms
    for bar in fetched:
        prev = known.get(bar.open_time)
        if prev is not None:
            if not prev.same_content(bar):
                raise InputIncompleteError(
                    f"同 ID 内容修订冲突: {bar.id} 已收盘根 OHLC 与账本不符")
            continue
        if bar.open_time <= tail_open:
            continue  # 账本尾根之前的旧重叠（超出核对范围）：不是新根，跳过
        if bar.open_time != expected:
            raise InputIncompleteError(
                f"增量缺根: 期望 open_time={expected}，实际 {bar.open_time}")
        new_bars.append(bar)
        expected = bar.open_time + timeframe_ms
    if new_bars:
        validate_chain(new_bars, new_bars[0].symbol, new_bars[0].timeframe,
                       timeframe_ms)
    return new_bars


def fetch_incremental(symbol: str, timeframe: str, existing: Sequence[Bar],
                      limit: int = 1000) -> List[Bar]:
    """为连续账本拉增量：只返回账本尾根之后、校验通过的新已收盘 Bar。

    existing 为账本现有 Bar（至少尾部若干根；重叠段用于修订冲突核对）。
    无新根返回 []（调用方据此判 no_new_bar）。"""
    fetched = fetch_klines(symbol, timeframe, limit=limit)
    return plan_increment(existing, fetched, TF_MS[timeframe])
