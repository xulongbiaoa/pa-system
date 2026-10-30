"""感知层单元测试：口径以知识库定版为准（摆动=收盘折线拐点、缺口=账本 v0.2）。

运行：PYTHONPATH=~/workspace/pylibs:~/workspace/pa-system python3 -m pytest perception/tests -q
"""

from perception.features import build_feature_pack, ema_series, load_config, mm_project
from perception.gaps import build_ledger
from perception.legs import count_entry_attempts, legs_from_swings
from perception.swings import find_swings

CFG = load_config()


def B(o, h, l, c):
    return {"t": 0, "o": o, "h": h, "l": l, "c": c, "v": 1}


def bars_from_closes(closes, pad=0.4):
    return [B(c, c + pad, c - pad, c) for c in closes]


def test_swings_known_pivots():
    bars = bars_from_closes([12, 11, 10, 11, 12, 13, 12, 11, 10, 11, 12])
    sw = find_swings(bars, 2)
    assert [s["kind"] for s in sw] == ["L", "H", "L"]
    assert [s["bar"] for s in sw] == [2, 5, 8]
    assert abs(sw[1]["anchor"] - 13.4) < 1e-9  # 锚价 = 拐点 K 影线极值


def test_single_leg_no_internal_swings():
    bars = bars_from_closes(list(range(10, 26)))
    sw = find_swings(bars, 2)
    assert sw == [] and legs_from_swings(sw) == []  # 清一色推进 = 一条腿，无内部切分


def test_h_attempts_two_legs():
    seg = [
        B(9.5, 10.0, 9.0, 9.5),
        B(9.2, 9.8, 8.5, 8.8),
        B(8.8, 9.9, 8.8, 9.4),
        B(9.4, 9.6, 8.2, 8.6),
        B(8.6, 9.7, 8.6, 9.2),
        B(9.2, 9.65, 8.4, 8.8),
    ]
    assert count_entry_attempts(seg, 0, 5, "long") == 2


def _gap_bars(with_touch=True):
    bars = [
        B(99.0, 99.4, 98.6, 99.0),
        B(99.2, 99.8, 99.0, 99.6),
        B(100.5, 101.5, 100.6, 101.2),  # 整根越过 100：立账，套空
        B(101.2, 103.0, 101.0, 102.5),  # 套深到 3.0
        B(102.5, 102.8, 100.2, 101.0),  # 逼近未碰（回补未遂候选）
        B(101.0, 102.0, 100.8, 101.8),  # 转身离去：未遂 +1
    ]
    if with_touch:
        bars.append(B(101.8, 102.0, 99.9, 100.5))  # 碰回锚：销账
    return bars


def test_gap_lifecycle_open_attempt_close():
    led = build_ledger(_gap_bars(True), [{"price": 100.0, "source": "map"}], CFG)
    maps = [g for g in led if g["source"] == "map"]
    assert len(maps) == 1
    g = maps[0]
    assert g["opened_at"] == 2 and g["trapped"] == "short"
    assert g["depth"] == 3.0 and g["attempts"] == 1
    assert g["status"] == "closed" and g["closed_at"] == 6


def test_gap_stays_open_when_never_touched():
    led = build_ledger(_gap_bars(False), [{"price": 100.0, "source": "map"}], CFG)
    g = [x for x in led if x["source"] == "map"][0]
    assert g["status"] == "open" and g["closed_at"] is None  # 差 0.2 没碰 = 没解套


def test_gap_stillborn_if_touched_before_leaving():
    bars = [
        B(99.0, 99.4, 98.6, 99.0),
        B(99.5, 100.8, 99.2, 100.5),  # 收盘穿越但整根未越过
        B(100.5, 101.0, 99.7, 100.2),  # 立账前先碰回：胎死
        B(100.2, 101.5, 100.3, 101.2),
    ]
    led = build_ledger(bars, [{"price": 100.0, "source": "map"}], CFG)
    assert [g for g in led if g["source"] == "map"] == []


def test_origin_gap_from_strong_breakout():
    bars = [
        B(98.5, 99.2, 98.2, 98.8),
        B(98.8, 99.4, 98.4, 99.1),
        B(99.1, 106.0, 98.6, 105.5),  # 强突破：起点锚 = 背向极值 98.6
        B(105.5, 107.0, 104.0, 106.0),
    ]
    led = build_ledger(bars, [{"price": 100.0, "source": "map"}], CFG)
    org = [g for g in led if g["source"] == "origin"]
    assert len(org) == 1
    assert org[0]["price"] == 98.6 and org[0]["status"] == "open"
    assert org[0]["depth"] == 8.4


def test_ema_seed_and_recursion():
    assert ema_series([1, 2, 3, 4, 5], 3) == [2.0, 3.0, 4.0]


def test_mm_project_single_leg():
    assert mm_project(110.0, 100.0, 108.0) == 118.0


def test_feature_pack_shape_and_confidence():
    bars = bars_from_closes([12, 11, 10, 11, 12, 13, 12, 11, 10, 11, 12])
    pack = build_feature_pack(bars)
    assert pack["bars"] == 11
    assert pack["ema"]["confidence"] == "未定"  # 根数不足 EMA 周期
    assert pack["gaps"]["confidence"] == "未定"  # 无地图锚 = 无账本
    pack2 = build_feature_pack(bars, [{"price": 10.0, "source": "map"}])
    assert pack2["gaps"]["confidence"] == "确定"


def test_pullback_legs_counts_higher_low_second_leg():
    """两腿回调的第二腿是更高低点——尝试计数器只算 1，腿数必须算 2。"""
    from perception.legs import count_pullback_legs
    sw = [{"bar": 3, "kind": "L", "anchor": 90.0},
          {"bar": 6, "kind": "H", "anchor": 94.0},
          {"bar": 9, "kind": "L", "anchor": 91.0}]  # 第二腿 91 > 第一腿 90
    assert count_pullback_legs(sw, 3, 9, "H") == 2


def test_pullback_legs_ignores_terminal_bounce():
    """只有端点反抽、后面没有同向推进 = 单腿，不算第二腿。"""
    from perception.legs import count_pullback_legs
    sw = [{"bar": 3, "kind": "L", "anchor": 90.0},
          {"bar": 6, "kind": "H", "anchor": 94.0}]
    assert count_pullback_legs(sw, 3, 6, "H") == 1


def test_pullback_legs_single_leg():
    from perception.legs import count_pullback_legs
    sw = [{"bar": 3, "kind": "L", "anchor": 90.0},
          {"bar": 9, "kind": "L", "anchor": 86.0}]
    assert count_pullback_legs(sw, 3, 9, "H") == 1
