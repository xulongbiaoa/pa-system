"""stop_market 与 market 真语义测试（2026-10-31 设计 v2.2 P0）。

旧缺陷：order_type=market 的计划在回放里从决策后第一根起按计划
entry 无条件成交——顺势 stop 触发计划（entry 写信号极值外侧）在
价格从未到过 entry 时也被记成成交，历史统计口径被污染。
"""

from replay import simulate_plan, simulate_stop_trade


def B(o, h, l, c):
    return {"t": 0, "o": o, "h": h, "l": l, "c": c, "v": 1}


def test_stop_untriggered_is_not_a_fill():
    # 价格始终没到触发价 105 → 未触发，不算成交
    bars = [B(100, 104, 99, 102), B(102, 104.5, 100, 103)]
    t = simulate_stop_trade(bars, "long", 105.0, 98.0, 115.0)
    assert t["filled"] is False and t["exit_reason"] == "untriggered"


def test_stop_touch_triggers_at_trigger_price():
    bars = [B(100, 106, 99, 104), B(104, 116, 103, 115)]
    t = simulate_stop_trade(bars, "long", 105.0, 98.0, 115.0)
    assert t["filled"] is True and t["fill_bar"] == 0
    assert t["fill_price"] == 105.0
    assert t["exit_reason"] == "target" and t["win"] is True


def test_stop_gap_fills_at_open_not_trigger():
    # 跳空开在触发价上方：按开盘价成交，不按没交易过的触发价
    bars = [B(108, 112, 107, 110), B(110, 121, 109, 120)]
    t = simulate_stop_trade(bars, "long", 105.0, 98.0, 120.0)
    assert t["filled"] is True and t["fill_price"] == 108.0
    assert t["exit_reason"] == "target"


def test_stop_short_mirror_and_gap():
    bars = [B(100, 101, 94, 96), B(96, 97, 84, 85)]
    t = simulate_stop_trade(bars, "short", 95.0, 102.0, 85.0)
    assert t["filled"] is True and t["fill_price"] == 95.0
    assert t["exit_reason"] == "target" and t["win"] is True
    gap = simulate_stop_trade([B(92, 93, 88, 90), B(90, 91, 84, 85)],
                              "short", 95.0, 102.0, 85.0)
    assert gap["filled"] is True and gap["fill_price"] == 92.0


def test_stop_void_before_fill_cancels():
    void = {"level": 99.0, "side": "below"}  # 收盘跌破 99 前提失效
    bars = [B(100, 102, 98.5, 98.8), B(99, 106, 98, 104)]
    t = simulate_stop_trade(bars, "long", 105.0, 96.0, 115.0, void=void)
    assert t["filled"] is False and t["exit_reason"] == "void_before_fill"


def test_stop_fill_bar_hitting_stop_is_ambiguous():
    # 成交根同时扫到止损：先后不可知 → ambiguous，离场按止损优先
    bars = [B(100, 106, 97.0, 99), B(99, 103, 98, 100)]
    t = simulate_stop_trade(bars, "long", 105.0, 98.0, 115.0)
    assert t["filled"] is True and t["ambiguous"] is True
    assert t["exit_reason"] == "stop"


def test_stop_window_anchored_at_decision_point():
    bars = [B(100, 101, 99, 100)] * 299 + [B(100, 106, 99.5, 104)]
    t = simulate_stop_trade(bars, "long", 105.0, 98.0, 115.0, window=300)
    assert t["filled"] is True and t["fill_bar"] == 299
    assert t["exit_reason"] == "window_end" and t["exit_bar"] == 299


def test_simulate_plan_dispatches_stop_market():
    bars = [B(100, 104, 99, 102), B(102, 104, 100, 101)]
    plan = {"entry": 105.0, "stop": 98.0, "targets": [115.0],
            "order_type": "stop_market"}
    t = simulate_plan(bars, plan, "long", window=300)
    assert t["order_type"] == "stop_market" and t["filled"] is False
    assert t["exit_reason"] == "untriggered"


def test_market_fills_at_next_open_not_plan_entry():
    # 真市价：计划 entry 是决策点现价记录，成交价 = 决策后首根开盘
    bars = [B(90, 95, 88, 94), B(94, 131, 93, 130)]
    plan = {"entry": 100.0, "stop": 80.0, "targets": [130.0],
            "order_type": "market"}
    t = simulate_plan(bars, plan, "long", window=300)
    assert t["filled"] is True and t["fill_price"] == 90.0
    assert t["exit_reason"] == "target" and t["win"] is True
