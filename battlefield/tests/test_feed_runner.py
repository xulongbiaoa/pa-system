"""feed 解析与 runner 组装测试（离线，不打网络）。"""
from battlefield.feed import parse_klines
from battlefield.runner import build_battlefield, scene_package, summarize
from battlefield.contracts import make_bar

TF_MS = 900_000


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
    # major 摆动（左5右5）高点 102 在 i=10 收盘确认；minor 摆动只作地形不立账
    rows = [
        (100, 100, 99, 100),
        (100, "100.5", "99.1", "100.2"),
        ("100.2", 101, "99.2", "100.6"),
        ("100.6", "101.5", "99.3", "101"),
        (101, "101.8", "99.4", "101.2"),
        ("101.2", 102, "99.5", "101.4"),   # major 摆动高点候选 102
        ("101.4", "101.5", "99.4", "100.8"),
        ("100.8", "101.2", "99.3", "100.4"),
        ("100.4", 101, "99.2", "100.2"),
        ("100.2", "100.8", "99.1", 100),
        (100, "100.5", 99, "100.2"),       # 右侧满 5 根 -> 确认
        ("100.2", "103.5", 100, 103),  # 收盘越过 102 -> 尝试
        (103, 105, "102.5", "104.5"),      # 整根在 102 上方 -> major 立账
        ("104.5", 105, 103, 104),
    ]
    bars = [_bar(i, *r) for i, r in enumerate(rows)]
    repo = build_battlefield("TEST", "15m", TF_MS, bars)
    pkg = scene_package(repo)
    anchors = [g["anchor"] for g in pkg["scene"]["open_gaps"]]
    assert "102" in anchors
    assert pkg["side_up"]["recorded"] is True
    text = summarize(pkg)
    assert "开放缺口" in text


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
