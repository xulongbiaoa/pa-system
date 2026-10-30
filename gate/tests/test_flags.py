"""flags 生产者（gate/flags.py）与 S2/S3 端到端触发测试。

2026-10-30 接线修复：此前 adjudicate 的 flags 无任何生产者，S1–S3
在真实回放从未触发。本文件钉住映射口径与端到端行为。
"""
from gate.flags import band_relevant, build_flags
from gate.risk_rules import adjudicate

BAND_TRAMPLED = {"lo": 99.0, "hi": 101.0, "trampled": True, "decaying": False}
BAND_DECAYING = {"lo": 90.0, "hi": 92.0, "trampled": False, "decaying": True}
BAND_CLEAN_FAR = {"lo": 50.0, "hi": 52.0, "trampled": True, "decaying": True}


def pack(*bands):
    return {"fortress": {"bands": list(bands)}}


def test_entry_inside_trampled_band_sets_trample():
    f = build_flags({"entry": 100.0, "stop": 103.0}, pack(BAND_TRAMPLED))
    assert f.get("trample") is True
    assert "decaying" not in f


def test_stop_crossing_decaying_band_sets_decaying():
    # 入场在带上方、止损穿过整带落到带外远侧 → 带与本单相关
    f = build_flags({"entry": 95.0, "stop": 89.0}, pack(BAND_DECAYING))
    assert f.get("decaying") is True


def test_far_band_not_relevant_even_if_trampled_and_decaying():
    f = build_flags({"entry": 100.0, "stop": 103.0}, pack(BAND_CLEAN_FAR))
    assert "trample" not in f and "decaying" not in f


def test_stop_inside_band_is_not_crossing():
    # 止损落在带内 = 没穿过去，不算穿越（区间与带相交但止损未出带）
    assert band_relevant(BAND_DECAYING, 95.0, 91.0) is False


def test_second_bar_confirmed_comes_from_plan_declaration():
    f = build_flags({"entry": 100.0, "stop": 103.0,
                     "second_bar_confirmed": True}, pack())
    assert f["second_bar_confirmed"] is True
    f2 = build_flags({"entry": 100.0, "stop": 103.0}, pack())
    assert f2["second_bar_confirmed"] is False


def test_no_fortress_pack_is_safe():
    f = build_flags({"entry": 1.0, "stop": 2.0}, {})
    assert f == {"second_bar_confirmed": False}


def _clean_pack():
    return {
        "last_close": 100.0, "seg_avg_range": 2.0,
        "swings": {"major": [], "minor": []},
        "gaps": {"confidence": "确定"}, "ema": {"confidence": "确定"},
        "trend": {"confidence": "确定"},
        "fortress": {"bands": [dict(BAND_TRAMPLED)]},
    }


def _plan(**kw):
    p = {"side": "short", "entry": 100.0, "stop": 101.0,
         "targets": [97.0], "risk_frac": 0.01, "setup": "B3",
         "context": "震荡"}
    p.update(kw)
    return p


def test_s2_fires_end_to_end_via_build_flags():
    plan = _plan()
    v = adjudicate(plan, _clean_pack(), bars_left=300, mode="annotation",
                   flags=build_flags(plan, _clean_pack()))
    assert [s["rule"] for s in v["soft_hits"]] == ["S2"]
    assert v["risk_mult"] == 0.5


def test_s2_silenced_by_second_bar_confirmation():
    plan = _plan(second_bar_confirmed=True)
    v = adjudicate(plan, _clean_pack(), bars_left=300, mode="annotation",
                   flags=build_flags(plan, _clean_pack()))
    assert v["soft_hits"] == [] and v["risk_mult"] == 1.0
