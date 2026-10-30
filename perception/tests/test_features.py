from perception.features import build_feature_pack, gap_consistency


def test_gap_consistency_conflict():
    gaps = [{"trapped": "short"}] * 6
    c = gap_consistency(-2, gaps)
    assert c["verdict"] == "冲突" and c["trapped_short"] == 6
    assert gap_consistency(2, gaps)["verdict"] == "一致"
    assert gap_consistency(2, [])["verdict"] == "无敞开缺口"


def test_tiny_price_precision_not_zeroed():
    # 1e-5 量级标的：段均幅不得被 round 压成 0
    bars = []
    for i in range(40):
        c = 1.0e-5 + (i % 5) * 2e-7
        bars.append({"t": i, "o": c, "h": c + 1e-6, "l": c - 1e-6, "c": c, "v": 1})
    pack = build_feature_pack(bars, [])
    assert pack["seg_avg_range"] > 0


def test_pullback_dir_against_follows_trend():
    # 上升趋势末端出现回调腿：dir_against 必须是 down（逆势方向）
    closes = [100 + i for i in range(30)] + [128, 126, 124]
    bars = [{"t": i, "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 1}
            for i, c in enumerate(closes)]
    pack = build_feature_pack(bars, [])
    if pack["pullback"]:
        assert pack["pullback"]["dir_against"] == "down"
