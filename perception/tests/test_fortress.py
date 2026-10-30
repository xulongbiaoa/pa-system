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


def test_chained_anchors_split_by_span_cap():
    # 2026-10-31 粒度修复：台阶式锚链（步长 ≤tol）旧实现并成一条巨带；
    # 跨度上限 2×seg_avg=4.0，锚 100→106 的链必须断成 ≥2 条带
    anchors = [S(100.0 + 0.9 * i) for i in range(8)]  # 100.0 … 106.3
    bars = [B(103.0) for _ in range(6)]
    bands = build_fortress_bands(bars, anchors, seg_avg=2.0)
    assert len(bands) >= 2
    for b in bands:
        assert b["hi"] - b["lo"] <= 4.0 + 1e-9 or b["far_undefined"]


def test_decaying_needs_a_close_cross():
    # 2026-10-31 衰减口径：被测 ≥4 次但从未被收盘穿过 = 要塞本色，不是衰减
    # 收盘簇钉出带 [99.6, 100.3]，五根收盘全在带内 → 穿越 0 次
    bars = [B(c, pad=0.6) for c in [99.6, 100.3, 99.7, 100.2, 99.6]]
    bands = build_fortress_bands(bars, [S(100.0)], seg_avg=2.0)
    b = bands[0]
    assert b["tests"] >= 4 and b["crosses"] == 0
    assert b["decaying"] is False and b["trampled"] is False
    # 孤锚单线 100：五根影线都够到线（测 ≥4），收盘只越线一次 → 衰减
    bars2 = [B(c, pad=2.5) for c in [98.0, 98.5, 102.0, 102.5, 101.8]]
    b2 = build_fortress_bands(bars2, [S(100.0)], seg_avg=2.0)[0]
    assert b2["tests"] >= 4 and b2["crosses"] == 1
    assert b2["decaying"] is True and b2["trampled"] is False


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
