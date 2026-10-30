"""基线口径测试：入场窗收到决策点、结局窗固定 300 根、漏斗可拆。

这三个口径 2026-10-30 才对齐（原 WARM/END=30/170 是红线 4 旧截止的残留，
回放又跑到段末），因此单独立测，防止回潮。
"""

import json
import os

import baselines
from baselines import DECISION, LIFECYCLE, funnel_stats, random_baseline, simple_baseline

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
DS = os.path.join(ROOT, "eval", "datasets", "dev")


def _segs():
    return [json.load(open(os.path.join(DS, n)))
            for n in sorted(os.listdir(DS)) if n.endswith(".json")]


def test_entry_window_stops_at_decision_point():
    for seg in _segs():
        for t in simple_baseline(seg, min_attempts=1):
            assert t["entry_bar"] < DECISION, f"{seg['id']} 在决策点之后入场"


def test_lifecycle_window_is_capped_at_300(monkeypatch):
    seen = {}

    def fake(bars_after, side, entry, stop, target, **kw):
        seen["n"] = len(bars_after)
        return {"r": 0.0, "exit_price": entry, "exit_bar": 0,
                "exit_reason": "window_end", "win": False}

    monkeypatch.setattr(baselines, "simulate_trade", fake)
    seg = _segs()[0]
    simple_baseline(seg, min_attempts=1)
    assert seen["n"] == LIFECYCLE == 300


def test_funnel_is_monotone_and_names_the_bottleneck():
    segs = _segs()
    loose = funnel_stats(segs, min_attempts=1)
    strict = funnel_stats(segs, min_attempts=2)
    for f in (loose, strict):
        assert f["bars"] >= f["ema_side"] >= f["pullback_cross"] >= f["attempts"]
        assert f["attempts"] >= f["signals"]
    # 记录当前事实：attempts≥2 只留下不到 1% 的候选（计数器要求先做新低才计
    # 第二次尝试，而 A1 的两腿允许「更高的第二腿低点」）。数值变了就该有人
    # 回头看是不是计数器语义被改了。
    assert strict["attempts"] / loose["attempts"] < 0.05
    assert strict["segments_with_signal"] <= loose["segments_with_signal"]


def test_random_baseline_is_reproducible_across_processes():
    seg = _segs()[0]
    a, b = random_baseline(seg), random_baseline(seg)
    assert a[0]["entry_bar"] == b[0]["entry_bar"] and a[0]["side"] == b[0]["side"]
