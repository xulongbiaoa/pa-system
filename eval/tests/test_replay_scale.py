"""分批出场（exit_mode=scale）回放测试（2026-10-31）。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from eval.replay import simulate_plan, _scale_fracs


def B(h, l, c):
    return {"o": c, "h": h, "l": l, "c": c}


def test_fracs():
    assert _scale_fracs(1) == [1.0]
    assert _scale_fracs(2) == [0.5, 0.5]
    assert _scale_fracs(3) == [0.5, 0.25, 0.25]
    assert _scale_fracs(5) == [0.5, 0.25, 0.25]


def test_scale_t1_hit_then_stop():
    # 多：入 100 损 90（风险 10），T1=110（+1R）、T2=120（+2R）。
    # 第 1 根摸 T1，第 2 根砸到止损：full=+1R；scale=0.5*1 + 0.5*(-1)=0。
    # market 成交价 = 决策后首根开盘（2026-10-31 新语义），故首根 o=100。
    bars = [{"o": 100, "h": 111, "l": 99, "c": 105}, B(105, 89, 95)] + [B(100, 95, 98)] * 5
    plan = {"entry": 100, "stop": 90, "targets": [110, 120], "order_type": "market"}
    full = simulate_plan(bars, plan, "long")
    assert full["exit_mode"] == "full" and abs(full["r"] - 1.0) < 0.02
    plan2 = dict(plan, exit_mode="scale")
    sc = simulate_plan(bars, plan2, "long")
    assert sc["exit_mode"] == "scale" and abs(sc["r"] - 0.0) < 0.02
    assert len(sc["tranches"]) == 2


def test_scale_runner_reaches_last_target():
    bars = [{"o": 100, "h": 121, "l": 99, "c": 115}] + [B(122, 110, 120)] * 3
    plan = {"entry": 100, "stop": 90, "targets": [110, 120, 130],
            "order_type": "market", "exit_mode": "scale"}
    sc = simulate_plan(bars, plan, "long")
    # T1/T2 首根同达；末档 130 未达 → 窗口末平仓（c=120 → +2R）
    assert sc["tranches"][0]["r"] > 0.9 and sc["tranches"][1]["r"] > 1.9
    assert sc["r"] > 1.4


def test_scale_limit_unfilled_is_whole_unfilled():
    bars = [B(105, 101, 103)] * 5  # 限价 100 永不穿越
    plan = {"entry": 100, "stop": 90, "targets": [110, 120],
            "order_type": "limit", "exit_mode": "scale"}
    sc = simulate_plan(bars, plan, "long")
    assert sc["filled"] is False
