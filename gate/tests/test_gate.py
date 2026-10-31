"""裁决层测试：硬规则拒绝、软规则只降仓、回放口径。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "eval"))

from gate.risk_rules import adjudicate  # noqa: E402
from replay import simulate_trade  # noqa: E402


def _pack():
    return {
        "swings": {"major": [{"bar": 5, "kind": "L", "close": 95.0, "anchor": 94.3}]},
        "seg_avg_range": 2.0,
        "gaps": {"confidence": "确定"},
        "ema": {"confidence": "确定"},
        "trend": {"confidence": "确定"},
    }


def _plan(**kw):
    p = {
        "side": "long",
        "entry": 100.0,
        "stop": 93.87,  # 在摆动低点 94.3 之外，且不压整数位
        "targets": [110.0],  # 净 RR 约 1.59
        "risk_frac": 0.01,
        "setup": "A1",
        "context": "上升",
        # 毛 RR 1.63 不到设计目标 2:1：夹具按 H8 口径带封顶说明，
        # 个别测试要验 H8 时自行 del p["cap_reason"]
        "cap_reason": "110 上方完好要塞封顶，目标按序列只能取到此处",
        "stop_basis": 94.3,  # 止损所依结构极值 = 夹具包里的摆动低点
    }
    p.update(kw)
    return p


def test_pass_clean_plan():
    r = adjudicate(_plan(), _pack(), bars_left=50, feature_refs=["trend.label"])
    assert r["verdict"] == "pass" and r["risk_mult"] == 1.0


def test_h1_rr_reject():
    r = adjudicate(_plan(targets=[105.0]), _pack(), bars_left=50)
    assert r["verdict"] == "reject" and any(h["rule"] == "H1" for h in r["hard_hits"])


def test_h2_stop_inside_structure_reject():
    r = adjudicate(_plan(stop=95.0), _pack(), bars_left=50)
    assert any(h["rule"] == "H2" for h in r["hard_hits"])


def test_h4_cutoff_reject():
    # H4 只约束 trainer 局内；annotation（标注/试点）下决策点即「当下」，不截止
    r = adjudicate(_plan(), _pack(), bars_left=5, mode="trainer")
    assert any(h["rule"] == "H4" for h in r["hard_hits"])


def test_h4_not_applied_in_annotation():
    r = adjudicate(_plan(), _pack(), bars_left=5, mode="annotation")
    assert not any(h["rule"] == "H4" for h in r["hard_hits"])
    assert r["verdict"] == "pass"


def test_h3_risk_frac_one_pct_is_the_cap():
    # core 红线 3：单笔风险 1%。1.0% 放行，1.1% 拒绝（原上限 1.5% 已收窄）
    assert adjudicate(_plan(risk_frac=0.01), _pack(), bars_left=50)["verdict"] == "pass"
    r = adjudicate(_plan(risk_frac=0.011), _pack(), bars_left=50)
    assert any(h["rule"] == "H3" for h in r["hard_hits"])


def test_h1_uses_first_target_not_last():
    # 首目标净 RR 不足 1.5，靠加一个远目标不能过关（与回放结算同口径）
    r = adjudicate(_plan(targets=[105.0, 130.0]), _pack(), bars_left=50)
    assert any(h["rule"] == "H1" for h in r["hard_hits"])
    assert r["rr_by_target"][0] < 1.5 < r["rr_by_target"][-1]


def test_soft_rule_no_longer_depends_on_target_choice():
    # 旧行为：S1 按**末级目标** RR 判断（首目标 1.6 / 末级 3.3 → 不降仓），
    # 于是「多写一个远目标」就能免掉降仓。2026-10-30 去掉 RR 条件后该漏洞
    # 一并消失；S1 已于 2026-10-31 删除，本例改用 S2 钉同一不变量：
    # 软降仓只看 flags，加不加远目标都降仓。
    r = adjudicate(_plan(targets=[110.0, 130.0]), _pack(), bars_left=50,
                   flags={"trample": True})
    assert r["risk_mult"] == 0.5
    assert any(s["rule"] == "S2" for s in r["soft_hits"])


def test_h6_skipped_notes_when_ledger_missing():
    # 不传台账时不许静默：结果里必须写明 H6 未生效
    r = adjudicate(_plan(), _pack(), bars_left=50)
    assert r["verdict"] == "pass"
    assert any("H6" in n for n in r["notes"])


def test_h6_requires_context_enum():
    ledger = {("A1", "上升"): {"n": 3, "wins": 0}}
    r = adjudicate(_plan(context="下降趋势里的回调多"), _pack(), bars_left=50,
                   ledger=ledger)
    assert not any(h["rule"] == "H6" for h in r["hard_hits"])
    assert any("context" in n for n in r["notes"])


def test_h2_round_level_reject_any_price_scale():
    # 关口判据按价格量级取步长：1.58 这类价格也有整数关口（0.05 一档），
    # 原来的 round(stop) 判据对非整数报价资产恒不命中（死代码）
    p = _pack()
    p["seg_avg_range"] = 0.4
    p["swings"]["minor"] = [{"bar": 9, "kind": "H", "close": 11.8, "anchor": 11.88}]
    base = _plan(side="short", entry=11.5, stop=12.0, targets=[10.0],
                 stop_basis=11.88)
    assert any(h["rule"] == "H2" for h in adjudicate(base, p, bars_left=50)["hard_hits"])
    off = _plan(side="short", entry=11.5, stop=11.91, targets=[10.0],
                stop_basis=11.88)
    assert not any(h["rule"] == "H2" for h in adjudicate(off, p, bars_left=50)["hard_hits"])


def test_h2_basis_unverifiable_when_pack_has_no_same_kind_swings():
    # 短窗包无同向摆动点：存在性检查无从执行，沉默不许否决（v3 dp4）
    p = _pack()
    p["swings"] = {"major": [], "minor": []}
    plan = _plan(stop=96.9, stop_basis=97.05)
    r = adjudicate(plan, p, bars_left=50)
    assert not any(h["rule"] == "H2" for h in r["hard_hits"])
    assert any("H2" in n for n in r["notes"])


def test_h2_missing_stop_basis_reject():
    # 眼主导 H2：未点名止损所依结构极值 = 无从核对，拒
    p = _plan()
    del p["stop_basis"]
    r = adjudicate(p, _pack(), bars_left=50)
    assert any(h["rule"] == "H2" for h in r["hard_hits"])


def test_h2_fabricated_basis_reject():
    # 点名的极值在附件摆动点中不存在（防编造）
    r = adjudicate(_plan(stop_basis=90.0), _pack(), bars_left=50)
    assert any(h["rule"] == "H2" for h in r["hard_hits"])


def test_h2_eye_named_minor_structure_passes():
    # 眼睛点名小级别结构、止损越过它即可——附件最近大级别极值不再代行识别
    p = _pack()
    p["swings"]["minor"] = [{"bar": 40, "kind": "L", "close": 97.2, "anchor": 97.05}]
    plan = _plan(stop=96.9, stop_basis=97.05, targets=[110.0])
    r = adjudicate(plan, p, bars_left=50)
    assert not any(h["rule"] == "H2" for h in r["hard_hits"])


def test_h5_undefined_feature_reject():
    pack = _pack()
    pack["gaps"] = {"confidence": "未定"}
    r = adjudicate(_plan(), pack, bars_left=50, feature_refs=["gaps.open"])
    assert any(h["rule"] == "H5" for h in r["hard_hits"])


def test_h6_suspended_mode_reject():
    # 2026-10-31 审计修复后：硬停牌门槛 n≥8（n=3 零胜的误杀率约 17%）。
    ledger = {("A1", "上升"): {"n": 8, "wins": 0}}
    r = adjudicate(_plan(), _pack(), bars_left=50, ledger=ledger)
    assert any(h["rule"] == "H6" for h in r["hard_hits"])


def test_h6_small_sample_zero_wins_is_observation_only():
    ledger = {("A1", "上升"): {"n": 3, "wins": 0}}
    r = adjudicate(_plan(), _pack(), bars_left=50, ledger=ledger)
    assert not any(h["rule"] == "H6" for h in r["hard_hits"])
    assert any("H6 观察" in n for n in r["notes"])


def test_soft_rule_downgrades_not_rejects():
    r = adjudicate(_plan(), _pack(), bars_left=50, flags={"trample": True})
    assert r["verdict"] == "pass" and r["risk_mult"] == 0.5
    assert any(s["rule"] == "S2" for s in r["soft_hits"])


def test_replay_stop_priority_same_bar():
    bars = [{"o": 101, "h": 112, "l": 93, "c": 105, "v": 1}]  # 同根同碰止损与目标
    t = simulate_trade(bars, "long", 100.0, 94.0, 110.0)
    assert t["exit_price"] == 94.0 and t["r"] < 0  # 止损优先


def test_replay_target_hit():
    bars = [{"o": 101, "h": 111, "l": 99, "c": 108, "v": 1}]
    t = simulate_trade(bars, "long", 100.0, 94.0, 110.0)
    assert t["exit_price"] == 110.0 and t["win"]


# --- H1 现价口径（2026-10-30）：入场价优于现价时按现价重算 -------------------


def _pack_px(px):
    p = _pack()
    p["last_close"] = px
    return p


def test_h1_rejects_favorable_entry_inflated_rr():
    # 做多入场价压到 97（优于现价 100）→ 计划自身 RR 约 3.2 过门槛；
    # 但按现价 100 算只有约 1.11 → 必须被 H1 拒
    plan = _plan(entry=97.0, stop=93.87, targets=[107.0])
    loose = adjudicate(plan, _pack(), bars_left=50)
    assert loose["verdict"] == "pass"          # 无现价字段时行为不变
    tight = adjudicate(plan, _pack_px(100.0), bars_left=50)
    assert tight["verdict"] == "reject"
    assert any(h["rule"] == "H1" for h in tight["hard_hits"])
    assert tight["rr_gate"][0] < tight["rr_by_target"][0]
    assert tight["decision_price"] == 100.0


def test_h1_keeps_plan_rr_when_entry_worse_than_price():
    # 追单（做多入场 102 > 现价 100）：不奖励，按计划自己的（更差的）RR 计
    plan = _plan(entry=102.0, stop=93.87, targets=[115.0])
    r = adjudicate(plan, _pack_px(100.0), bars_left=50)
    assert r["rr_gate"][0] == r["rr_by_target"][0]
    assert r["rr_by_target_at_decision"][0] > r["rr_gate"][0]


def test_market_order_unaffected_by_decision_price():
    plan = _plan(entry=100.0, stop=93.87, targets=[110.0])
    r = adjudicate(plan, _pack_px(100.0), bars_left=50)
    assert r["rr_gate"] == r["rr_by_target"]
    assert not any("现价" in n for n in r["notes"])


def test_short_entry_raised_cannot_inflate_rr():
    # ds23 式：做空入场价从现价 11.43 抬到 11.659（风险分母 0.37→0.141）
    base = {"side": "short", "stop": 11.8, "targets": [10.9],
            "risk_frac": 0.01, "setup": "B3", "context": "下降"}
    pack = _pack()
    pack["last_close"] = 11.43
    pack["swings"] = {"major": [{"bar": 5, "kind": "H", "close": 12.0, "anchor": 12.1}]}
    inflated = adjudicate({**base, "entry": 11.659}, pack, bars_left=50)
    assert inflated["verdict"] == "reject"      # 承诺 RR 5.4 被现价口径压回 1.43
    assert inflated["rr_by_target"][0] > 3.0
    assert inflated["rr_gate"][0] < 1.5


# --- 设计目标 RR（用户 2026-10-30 定「盈亏比 2:1」= 毛 RR 2.0）-------------


def test_reports_gap_to_design_target():
    # 盈亏比 2:1：entry 100、止损 93.87（风险 6.13）、目标 112.26（回报 12.26）
    r = adjudicate(_plan(targets=[112.26]), _pack(), bars_left=50)
    assert r["target_rr"] == 2.0
    assert r["rr_gross"] == 2.0
    assert r["rr_gap_to_target"] == 0.0
    assert r["rr_gate"][0] < 2.0        # 净 RR 必然低于毛 RR（费用）
    assert r["verdict"] == "pass"


def test_design_target_does_not_veto_below_target():
    # 毛 1.6（低于设计目标）但净 RR 仍过 1.5 地板、且带封顶说明 → 放行，
    # 只报差距。2026-10-31 H8 后口径细化：不否决的是 RR 水平本身，
    # 否决的是「低于目标又不说明被什么挡住」（见 test_h8.py）。
    r = adjudicate(_plan(targets=[109.808]), _pack(), bars_left=50)
    assert r["verdict"] == "pass"
    assert r["rr_gap_to_target"] < 0
    assert not any(h["rule"] == "H1" for h in r["hard_hits"])
    p = _plan(targets=[109.808])
    del p["cap_reason"]
    r2 = adjudicate(p, _pack(), bars_left=50)
    assert any(h["rule"] == "H8" for h in r2["hard_hits"])


def test_soft_rules_unconditional_after_design_target():
    # S2 无条件减仓（2026-10-30 去掉恒真 RR 条件）。S1/S3 已于
    # 2026-10-31 删除：parabolic 判据自始不存在、decaying 计数口径
    # 无区分力——两键传入 flags 也必须毫无效果，不许留装饰性规则。
    r = adjudicate(_plan(targets=[112.26]), _pack(), bars_left=50,
                   flags={"parabolic": True, "decaying": True,
                          "trample": True})
    rules = {s["rule"] for s in r["soft_hits"]}
    assert rules == {"S2"} and r["risk_mult"] == 0.5


def test_s1_deleted_parabolic_flag_is_inert():
    # 高 RR 计划 + parabolic 键：S1 删除后软规则零命中、仓位不减
    r = adjudicate(_plan(targets=[118.0]), _pack(), bars_left=50,
                   flags={"parabolic": True})
    assert r["rr_gate"][-1] > 2.5
    assert r["soft_hits"] == [] and r["risk_mult"] == 1.0


# --- 毛目标与净地板的量纲：地板不能高过设计目标能给的净 RR -------------------


def test_design_target_net_shrinks_with_tight_stop():
    from gate.risk_rules import net_rr_of_design_target
    vals = [net_rr_of_design_target(f) for f in (0.002, 0.005, 0.01, 0.05)]
    assert vals == sorted(vals)                 # 止损越宽，净 RR 越高
    assert net_rr_of_design_target(0.01) < 2.0  # 毛 2:1 的净 RR 永远低于 2


def test_floor_must_stay_below_design_target_net():
    # 护栏：红线地板若抬到 2.0 净，所有合格的毛 2:1 单都会被自己拒掉
    from gate.risk_rules import RR_MIN, min_stop_frac_for_floor, net_rr_of_design_target
    assert RR_MIN < net_rr_of_design_target(0.01)
    assert min_stop_frac_for_floor(2.0) is None


def test_min_stop_frac_for_floor():
    # 毛 2:1 要过 1.5 净地板，止损至少占价约 0.5%（解析解 0.501%）
    from gate.risk_rules import min_stop_frac_for_floor
    f = min_stop_frac_for_floor(1.5)
    assert 0.0049 < f < 0.0052


def test_h6_notes_when_ledger_has_no_cell():
    """传了台账但没这一格，必须留痕——传 {} 看起来像接好了，实际 H6 从未生效。"""
    r = adjudicate(_plan(), _pack(), bars_left=50, ledger={})
    assert r["verdict"] == "pass"
    assert any("H6" in n and "样本" in n for n in r["notes"]), r["notes"]


def test_h6_notes_when_cell_empty():
    ledger = {("A1", "上升"): {"n": 0, "wins": 0}}
    r = adjudicate(_plan(), _pack(), bars_left=50, ledger=ledger)
    assert not any(h["rule"] == "H6" for h in r["hard_hits"])
    assert any("H6" in n for n in r["notes"]), r["notes"]


def test_limit_order_type_uses_limit_fee():
    """order_type=limit 必须走限价费率；原先 gate 只认 limit_in，写 limit 的
    单子按市价费率算 RR，H1 永远吃不到限价优惠（2026-10-30 复核）。"""
    market = adjudicate(_plan(order_type="market"), _pack(), bars_left=50)
    limit = adjudicate(_plan(order_type="limit"), _pack(), bars_left=50)
    assert limit["rr_by_target"][0] > market["rr_by_target"][0]


def test_legacy_limit_in_still_honoured():
    legacy = adjudicate(_plan(limit_in=True), _pack(), bars_left=50)
    limit = adjudicate(_plan(order_type="limit"), _pack(), bars_left=50)
    assert legacy["rr_by_target"] == limit["rr_by_target"]


def test_h1_limit_plan_priced_at_limit_entry():
    """2026-10-31 裁定（按 Brooks v30）：限价计划按限价入场价计 H1。
    同一组数字：现价已贴近目标 → 现价口径 RR≈0，市价计划被 H1 拒；
    限价计划按事前写明的限价位计 RR≈1.59 → 过 H1。"""
    pack = _pack()
    pack["last_close"] = 109.5
    market = adjudicate(_plan(), pack, bars_left=50,
                        feature_refs=["trend.label"])
    assert any(h["rule"] == "H1" for h in market["hard_hits"])
    limit = adjudicate(_plan(order_type="limit"), pack, bars_left=50,
                       feature_refs=["trend.label"])
    assert not any(h["rule"] == "H1" for h in limit["hard_hits"])
    assert limit["verdict"] == "pass"
