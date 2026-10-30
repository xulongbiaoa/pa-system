"""限价口径与自然时间换算测试（2026-10-30 用户口径）。"""

from replay import bars_for_days, simulate_limit_trade, simulate_trade


def B(o, h, l, c):
    return {"t": 0, "o": o, "h": h, "l": l, "c": c, "v": 1}


def test_touch_is_not_fill():
    # 低点恰好等于限价 = 只触及，不算成交
    bars = [B(100, 101, 99.0, 100)]
    t = simulate_limit_trade(bars, "long", 99.0, 97.0, 103.0)
    assert t["filled"] is False and t["exit_reason"] == "unfilled"


def test_through_is_fill_then_target():
    bars = [B(100, 101, 98.9, 100), B(100, 104, 99.5, 103.5)]
    t = simulate_limit_trade(bars, "long", 99.0, 97.0, 103.0)
    assert t["filled"] is True and t["fill_bar"] == 0
    assert t["exit_reason"] == "target" and t["win"] is True


def test_window_anchored_at_decision_point():
    # 第 299 根才成交，窗口仍在第 300 根结束（不因成交晚而顺延）
    bars = [B(100, 100.5, 99.5, 100)] * 298 + [B(100, 101, 98.0, 99.0), B(99, 99.5, 98.5, 99.2)]
    t = simulate_limit_trade(bars, "long", 98.5, 97.0, 103.0, window=300)
    assert t["filled"] is True and t["fill_bar"] == 298
    assert t["exit_reason"] == "window_end" and t["exit_bar"] == 299


def test_short_limit_needs_high_through():
    bars = [B(100, 101.0, 99, 100)]
    t = simulate_limit_trade(bars, "short", 101.0, 103.0, 97.0)
    assert t["filled"] is False


def test_exit_reason_present_on_market_trades():
    t = simulate_trade([B(100, 101, 99, 100.5)], "long", 100.0, 98.0, 103.0)
    assert t["exit_reason"] == "window_end"


def test_bars_for_days():
    assert bars_for_days("15m", 7) == 672
    assert bars_for_days("1d", 7) == 7
    assert bars_for_days("4h", 7) == 42


def test_simulate_plan_dispatches_on_order_type():
    """限价口径必须真的进管线：写 limit 却按市价回放，正是这条口径要防的高估。"""
    from replay import simulate_plan
    bars = [B(100, 101, 99, 100), B(100, 101, 98, 99)]  # 最低 98，未穿越 95
    plan = {"entry": 95.0, "stop": 90.0, "targets": [110.0], "order_type": "limit"}
    t = simulate_plan(bars, plan, "long", window=300)
    assert t["order_type"] == "limit" and t["filled"] is False


def test_simulate_plan_limit_fills_when_crossed():
    from replay import simulate_plan
    bars = [B(100, 101, 94, 99), B(99, 112, 98, 111)]  # 第二根穿越 95 并打到 110
    plan = {"entry": 95.0, "stop": 90.0, "targets": [110.0], "order_type": "limit"}
    t = simulate_plan(bars, plan, "long", window=300)
    assert t["filled"] is True and t["exit_reason"] == "target"


def test_simulate_plan_defaults_to_market():
    from replay import simulate_plan
    bars = [B(100, 111, 99, 108)]
    t = simulate_plan(bars, {"entry": 100.0, "stop": 94.0, "targets": [110.0]},
                      "long", window=300)
    assert t["order_type"] == "market" and t["filled"] is True


def test_limit_fill_charges_limit_entry_fee():
    """限价单入场按 fees['limit_in'] 计费，与 H1 的净 RR 同口径。

    原先本模块硬编码 FEE=0.0005：裁决层按 0.02% 承诺 RR、回放按 0.05% 结算，
    承诺与结算两套账（2026-10-30 复核）。
    """
    bars = [B(100, 101, 98.9, 100), B(100, 104, 99.5, 103.5)]
    market = simulate_trade(bars, "long", 99.0, 97.0, 103.0)
    limit = simulate_limit_trade(bars, "long", 99.0, 97.0, 103.0)
    assert limit["filled"] is True
    # 入场费更低 → 净 R 更高；差额 = (0.0005-0.0002)*99/risk
    assert limit["r"] > market["r"]
    assert abs((limit["r"] - market["r"]) - 0.0003 * 99.0 / 2.0) < 1e-9


def test_replay_has_no_numpy_dependency():
    """评估链路必须能在无第三方包的环境跑（原先顶层 import numpy，
    gold_run/gold_build 整体起不来）。"""
    import inspect
    import replay
    src = inspect.getsource(replay)
    assert "import numpy" not in src, "replay 又引入 numpy 了"


def test_summarize_without_numpy():
    from replay import summarize
    s = summarize([{"r": 1.0, "win": True}, {"r": -1.0, "win": False},
                   {"r": 2.0, "win": True}])
    assert s["n"] == 3 and s["median_r"] == 1.0
    assert s["mean_r_ci95"][0] <= s["mean_r"] <= s["mean_r_ci95"][1]
    assert s["proven_edge"] is False and "样本不足" in s["note"]
