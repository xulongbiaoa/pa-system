"""void 前提失效：解释器 + 回放执行（2026-10-30 补）。

此前 plan.void_if 只有文字、回放不执行——出场纪律只有止损/目标一半。
结构化口径：plan.void = {level, side}，收盘越过 level 即失效出场。
"""
from eval.replay import simulate_limit_trade, simulate_plan, simulate_trade, void_hit

V_BELOW = {"level": 98.0, "side": "below"}   # 多单：收盘跌破 98 前提失效
V_ABOVE = {"level": 102.0, "side": "above"}  # 空单：收盘站上 102 前提失效


def bar(o, h, l, c):
    return {"o": o, "h": h, "l": l, "c": c}


def test_void_hit_primitive():
    assert void_hit(V_BELOW, 97.9) is True
    assert void_hit(V_BELOW, 98.0) is False  # 压线不算越过（收盘须严格越线）
    assert void_hit(V_ABOVE, 102.1) is True
    assert void_hit(None, 1.0) is False
    assert void_hit({}, 1.0) is False


def test_market_long_void_exit_at_close():
    bars = [bar(100, 101, 99.5, 100.5),          # 无事
            bar(100.5, 100.8, 98.6, 97.8),       # 收盘 97.8 < 98 → void
            bar(97.8, 99.0, 97.0, 98.5)]
    t = simulate_trade(bars, "long", 100.0, 95.0, 110.0, void=V_BELOW)
    assert t["exit_reason"] == "void"
    assert t["exit_bar"] == 1 and t["exit_price"] == 97.8
    assert t["win"] is False


def test_stop_intrabar_beats_void_same_bar():
    bars = [bar(100, 100.5, 94.0, 97.0)]  # 盘中触损且收盘也越 void 线
    t = simulate_trade(bars, "long", 100.0, 95.0, 110.0, void=V_BELOW)
    assert t["exit_reason"] == "stop" and t["exit_price"] == 95.0


def test_no_void_keeps_window_end():
    bars = [bar(100, 101, 99.0, 100.2)]
    t = simulate_trade(bars, "long", 100.0, 95.0, 110.0)
    assert t["exit_reason"] == "window_end"


def test_limit_void_before_fill_cancels_order():
    # 限价 99 买入；第 0 根没穿 99 且收盘 97.5 已越 void 线 → 挂单作废
    bars = [bar(100, 100.5, 99.2, 97.5),
            bar(97.5, 98.0, 96.0, 97.0)]
    t = simulate_limit_trade(bars, "long", 99.0, 95.0, 110.0, void=V_BELOW)
    assert t["filled"] is False
    assert t["exit_reason"] == "void_before_fill" and t["void_bar"] == 0


def test_limit_fill_then_void_exits():
    bars = [bar(100, 100.5, 98.8, 99.5),   # 穿越 99 成交，收盘未越线
            bar(99.5, 100.0, 98.4, 97.6)]  # 收盘越线 → void 出场
    t = simulate_limit_trade(bars, "long", 99.0, 95.0, 110.0, void=V_BELOW)
    assert t["filled"] is True and t["exit_reason"] == "void"
    assert t["exit_price"] == 97.6 and t["exit_bar"] == 1


def test_simulate_plan_passes_void_through():
    plan = {"entry": 100.0, "stop": 95.0, "targets": [110.0],
            "order_type": "market", "void": V_BELOW}
    bars = [bar(100, 101, 99.0, 97.0)]
    t = simulate_plan(bars, plan, "long")
    assert t["exit_reason"] == "void" and t["order_type"] == "market"
