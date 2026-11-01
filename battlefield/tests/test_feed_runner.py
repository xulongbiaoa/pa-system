"""feed 解析与 runner 组装测试（离线，不打网络）。"""
import pytest

from battlefield import feed as feed_mod
from battlefield.feed import (InputIncompleteError, fetch_closed_window,
                              parse_klines, select_closed_window,
                              validate_closed_window, window_input_hash)
from battlefield.runner import build_battlefield, scene_package, summarize
from battlefield.contracts import make_bar

TF_MS = 900_000
BASE = 1_700_000_100_000  # 900000 的整数倍，落在 15m 边界上


def _closed_bar(i, close="100"):
    return make_bar("BTCUSDT", "15m", BASE + i * TF_MS,
                    BASE + i * TF_MS + TF_MS - 1,
                    "100", "101", "99", close, source="binance-vision",
                    received_at=BASE + i * TF_MS + TF_MS)


def _window(n=96):
    return [_closed_bar(i) for i in range(n)]


def test_parse_klines_filters_unclosed():
    raw = [
        [0, "100", "101", "99", "100.5", "1", TF_MS - 1],
        [TF_MS, "100.5", "102", "100", "101.5", "1", 2 * TF_MS - 1],
    ]
    bars = parse_klines(raw, "BTCUSDT", "15m", now_ms=TF_MS)  # 第二根尚未收盘
    assert len(bars) == 1 and bars[0].close == bars[0].close  # 占位断言下行校验
    assert str(bars[0].close) == "100.5"


def _bar(i, o, h, l, c):
    return make_bar("TEST", "15m", i * TF_MS, (i + 1) * TF_MS, o, h, l, c,
                    received_at=(i + 1) * TF_MS)


def test_runner_gap_opens_on_confirmed_swing():
    # 定版 v0.2（2026-11-01）：波段点 = 收盘折线拐点（回撤 >= 3 倍尺度
    # 确认）。每根 range 恒 2.4（尺度 2.4，门槛 7.2）：收盘腿 100->108
    # 的极值根影线高点 108.2 是波段高点，回撤 7.4 确认；回踩低点 100.4
    # 再回升 7.4 确认成起点拐点；收盘破 108.2 时波段点缺口与起点缺口同开
    closes = [100, 102, 104, 106, 108,
              106, 104, 102, "100.6",
              102, 104, 106, 108,
              110]
    bars = []
    prev = "99"
    for i, c in enumerate(closes):
        c = str(c)
        hi = max(float(prev), float(c)) + 0.2
        lo = min(float(prev), float(c)) - 0.2
        bars.append(_bar(i, prev, f"{hi:.1f}", f"{lo:.1f}", c))
        prev = c
    repo = build_battlefield("TEST", "15m", TF_MS, bars)
    pkg = scene_package(repo)
    anchors = [g["anchor"] for g in pkg["scene"]["open_gaps"]]
    assert "108.2" in anchors
    assert "100.4" in anchors                 # 起点缺口（腿起点的背向极值）
    assert pkg["side_up"]["recorded"] is True
    text = summarize(pkg)
    assert "开放缺口" in text


def test_validate_closed_window_accepts_binance_style():
    bars = _window()
    out = validate_closed_window(bars, "BTCUSDT", "15m")
    assert len(out) == 96 and out[-1].close_time == BASE + 96 * TF_MS - 1
    assert window_input_hash(bars) == window_input_hash(_window())


def test_validate_closed_window_rejects_wrong_count_and_gap():
    with pytest.raises(InputIncompleteError):
        validate_closed_window(_window(95), "BTCUSDT", "15m")
    bars = _window()
    bars[40] = make_bar("BTCUSDT", "15m", BASE + 41 * TF_MS,
                        BASE + 41 * TF_MS + TF_MS - 1, "100", "101", "99", "100",
                        source="binance-vision")  # 与上一根重叠、缺第 40 根
    with pytest.raises(InputIncompleteError):
        validate_closed_window(bars, "BTCUSDT", "15m")


def test_validate_closed_window_rejects_misaligned_and_mixed_close_style():
    bars = _window()
    bars[3] = make_bar("BTCUSDT", "15m", BASE + 3 * TF_MS + 1,
                       BASE + 3 * TF_MS + TF_MS, "100", "101", "99", "100")
    with pytest.raises(InputIncompleteError):
        validate_closed_window(bars, "BTCUSDT", "15m")
    bars = _window()
    bars[3] = make_bar("BTCUSDT", "15m", BASE + 3 * TF_MS,
                       BASE + 4 * TF_MS, "100", "101", "99", "100")  # open+周期
    with pytest.raises(InputIncompleteError):
        validate_closed_window(bars, "BTCUSDT", "15m")


def test_select_closed_window_uses_tail_only():
    bars = _window(100)
    out = select_closed_window(bars, "BTCUSDT", "15m")
    assert out[0].open_time == BASE + 4 * TF_MS and len(out) == 96
    with pytest.raises(InputIncompleteError):
        select_closed_window(_window(90), "BTCUSDT", "15m")


def test_fetch_closed_window_fetches_with_margin(monkeypatch):
    seen = {}

    def fake_fetch(symbol, timeframe, limit=300):
        seen["limit"] = limit
        return _window(100)

    monkeypatch.setattr(feed_mod, "fetch_klines", fake_fetch)
    out = fetch_closed_window("BTCUSDT", "15m", expected_count=96, margin=4)
    assert seen["limit"] == 100 and len(out) == 96


def test_scene_package_carries_last_bar():
    # W08 发现：状态包缺最新收盘价，判读员被迫包外找价并出错——包必须自带 last_bar
    from battlefield.feed import parse_klines
    raw = [[1700000000000 + i * 900000, "100", "101", "99", "100.5", "1",
            1700000000000 + i * 900000 + 899999] for i in range(30)]
    bars = parse_klines(raw, "BTCUSDT", "15m", now_ms=1700000000000 + 30 * 900000)
    repo = build_battlefield("BTCUSDT", "15m", 900_000, bars)
    pkg = scene_package(repo)
    assert pkg["last_bar"] is not None
    assert pkg["last_bar"]["close"] == "100.5"
    assert pkg["last_bar"]["open_time"] == bars[-1].open_time
