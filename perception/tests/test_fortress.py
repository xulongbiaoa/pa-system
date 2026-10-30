"""要塞带与趋势年龄测试。"""

from perception.fortress import build_fortress_bands, trend_age


def B(c, pad=0.3):
    return {"t": 0, "o": c, "h": c + pad, "l": c - pad, "c": c, "v": 1}


def S(anchor, kind="H"):
    return {"bar": 0, "kind": kind, "close": anchor, "anchor": anchor}


def test_band_from_close_cluster():
    bars = [B(c) for c in [99.9, 100.2, 100.5, 100.1, 105.0, 108.0]]
    bands = build_fortress_bands(bars, [S(100.0), S(100.3)], seg_avg=2.0)
    assert len(bands) == 1
    b = bands[0]
    assert b["anchors"] == 2 and b["far_undefined"] is False
    assert b["lo"] == 99.9 and b["hi"] == 100.5  # 边由收盘簇钉定
    assert b["tests"] == 4


def test_lone_anchor_band_far_undefined():
    bars = [B(c) for c in [105.0, 109.8, 110.2, 112.0]]
    bands = build_fortress_bands(bars, [S(110.0)], seg_avg=2.0)
    assert bands[0]["far_undefined"] is True  # 收盘簇不足，远边未定
    assert bands[0]["lo"] == bands[0]["hi"] == 110.0


def test_crosses_and_trample_flag():
    bars = [B(c, pad=0.5) for c in [98.0, 102.0, 98.0, 102.0]]
    bands = build_fortress_bands(bars, [S(100.0)], seg_avg=2.0)
    assert bands[0]["crosses"] == 3 and bands[0]["trampled"] is True


def test_trend_age_sequence_and_ema_distance():
    bars = [B(100.0) for _ in range(49)] + [B(102.0)]
    legs = [
        {"from_bar": 0, "to_bar": 10, "dir": "down", "start": 104.0, "end": 100.0, "height": 4.0},
        {"from_bar": 10, "to_bar": 20, "dir": "up", "start": 100.0, "end": 103.0, "height": 3.0},
        {"from_bar": 20, "to_bar": 30, "dir": "down", "start": 103.0, "end": 99.0, "height": 4.0},
        {"from_bar": 30, "to_bar": 49, "dir": "up", "start": 99.0, "end": 102.0, "height": 3.0},
    ]
    age = trend_age(bars, legs, [100.0], [b["c"] for b in bars])
    assert age["bars"] == 19 and age["legs"] == 1
    assert age["ema_distance_units"] == 0.5 and age["confidence"] == "确定"
