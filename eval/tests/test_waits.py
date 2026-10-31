"""Build 3 等待对象：登记构造与机械核对的纯函数测试。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from forward_waits import build_waits, scan_wait  # noqa: E402


def _bar(t, o, h, l, c):
    return {"t": t, "o": o, "h": h, "l": l, "c": c}


def test_build_waits_from_pending(tmp_path):
    import json
    jd = tmp_path / "judgments"
    jd.mkdir()
    j = {"pending_conditions": [
        {"setup": "B3", "missing": ["缺收回"], "watch": "等回到翻面位"},
        "旧格式字符串跳过"]}
    (jd / "ev1.json").write_text(json.dumps(j))
    state = {"queued": {"ev1": {
        "status": "judged_no_trade", "symbol": "X", "interval": "15m",
        "decision_t": 1000,
        "levels": [{"kind": "fortress", "lo": 90.0, "hi": 95.0}]},
        "ev2": {"status": "tracked"}}}
    waits = build_waits(state, str(jd))
    assert list(waits) == ["ev1::B3"]
    w = waits["ev1::B3"]
    assert w["bands"] == [{"lo": 90.0, "hi": 95.0, "src": "level:fortress"}]
    assert w["frozen_missing"] == ["缺收回"] and w["status"] == "open"


def test_scan_wait_due_on_band_touch():
    # 先离开（整根在带外）再回到带内才 due
    w = {"bands": [{"lo": 90.0, "hi": 95.0}], "_avg": 2.0}
    bars = [_bar(1, 100, 101, 99, 100), _bar(2, 100, 100, 94, 96)]
    tr, info = scan_wait(w, bars)
    assert tr == "due" and info["t"] == 2


def test_scan_wait_no_due_without_departure():
    # 一直贴在带边没真正离开过 → 不 due（防首扫式假阳性）
    w = {"bands": [{"lo": 90.0, "hi": 95.0}], "_avg": 2.0}
    bars = [_bar(1, 94, 96, 93, 95), _bar(2, 95, 96, 94, 95.5)]
    tr, _ = scan_wait(w, bars)
    assert tr is None


def test_scan_wait_cancelled_on_acceptance():
    w = {"bands": [{"lo": 90.0, "hi": 95.0}], "_avg": 2.0}
    bars = [_bar(1, 100, 102, 99, 101), _bar(2, 101, 103, 100, 102),
            _bar(3, 102, 104, 101, 103)]
    tr, info = scan_wait(w, bars)
    assert tr == "cancelled" and info["proxy"].startswith("accepted")


def test_scan_wait_stays_open():
    w = {"bands": [{"lo": 90.0, "hi": 95.0}], "_avg": 2.0}
    bars = [_bar(1, 97, 98, 96, 96.5), _bar(2, 96.5, 97.5, 96, 97)]
    tr, _ = scan_wait(w, bars)
    assert tr is None
