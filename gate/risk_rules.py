"""裁决层：AI 提议，代码否决。只能否决或降仓，不能改计划、不能放宽。

硬规则（违反即拒绝）：H1 净 RR、H2 止损结构外、H3 单笔风险上限、
H4 入场截止、H5 引用完整性（引用了置信「未定」的特征）、H6 模式停牌。
软规则（降仓不拒绝）：S1 抛物线高潮折扣、S2 踩踏继承、S3 衰减边缘。
每次裁决返回命中的规则编号与数值明细，写入日志供改规证据统计。
"""

from perception.features import load_config

RR_MIN = 1.5
RISK_FRAC_MAX = 0.015
CUTOFF_LEFT = 10  # 距窗口末尾不足 10 根不开仓


def _net_rr(entry, stop, target, fees, limit_in=False):
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    fin = fees["limit_in"] if limit_in else fees["market_in"]
    cost = entry * fin + target * fees["out"]
    return (abs(target - entry) - cost) / (risk + entry * fin + entry * fees["out"])


def adjudicate(plan, pack, *, bars_left, feature_refs=(), flags=None, ledger=None):
    """plan: {side, entry, stop, targets[], risk_frac, limit_in?}
    flags: {parabolic, trample, decaying, second_bar_confirmed}
    ledger: {(setup, context): {'n': int, 'wins': int}}，另需 plan['setup'] 与
    plan['context'] 才查停牌。"""
    cfg = load_config()
    fees = cfg["fees"]
    flags = flags or {}
    hard, soft = [], []
    rr_by_target = [
        _net_rr(plan["entry"], plan["stop"], t, fees, plan.get("limit_in", False))
        for t in plan["targets"]
    ]
    rr_main = rr_by_target[-1] if rr_by_target else None
    # H1 净 RR（按声明的目标序列末级计价）
    if rr_main is None or rr_main < RR_MIN:
        hard.append({"rule": "H1", "detail": f"净RR={rr_main} < {RR_MIN}"})
    # H2 止损在结构外：多头止损须低于最近的大级别摆动低点锚，且不压整数位
    swings = pack.get("swings", {}).get("major", [])
    seg_avg = pack.get("seg_avg_range") or 0
    entry, stop = plan["entry"], plan["stop"]
    if plan["side"] == "long":
        below = [s["anchor"] for s in swings if s["kind"] == "L" and s["anchor"] < entry]
        if below and stop >= max(below):
            hard.append({"rule": "H2", "detail": f"止损 {stop} 在摆动低点 {max(below)} 之内"})
    else:
        above = [s["anchor"] for s in swings if s["kind"] == "H" and s["anchor"] > entry]
        if above and stop <= min(above):
            hard.append({"rule": "H2", "detail": f"止损 {stop} 在摆动高点 {min(above)} 之内"})
    if seg_avg and abs(stop - round(stop)) < 0.02 * seg_avg:
        hard.append({"rule": "H2", "detail": f"止损 {stop} 压整数位"})
    # H3 风险上限
    if plan.get("risk_frac", 0) > RISK_FRAC_MAX:
        hard.append({"rule": "H3", "detail": f"risk_frac={plan.get('risk_frac')} > {RISK_FRAC_MAX}"})
    # H4 入场截止
    if bars_left < CUTOFF_LEFT:
        hard.append({"rule": "H4", "detail": f"距窗口末尾 {bars_left} 根 < {CUTOFF_LEFT}"})
    # H5 引用完整性
    conf = {
        "gaps": pack.get("gaps", {}).get("confidence"),
        "ema": pack.get("ema", {}).get("confidence"),
        "trend": pack.get("trend", {}).get("confidence"),
    }
    for ref in feature_refs:
        root = ref.split(".")[0]
        if conf.get(root) == "未定":
            hard.append({"rule": "H5", "detail": f"引用了未定特征 {ref}"})
    # H6 模式停牌
    if ledger is not None and plan.get("setup") and plan.get("context"):
        st = ledger.get((plan["setup"], plan["context"]))
        if st and st.get("n", 0) >= 3 and st.get("wins", 0) == 0:
            hard.append({"rule": "H6", "detail": f"{plan['setup']}×{plan['context']} 样本{st['n']} 0胜，停牌"})
    # 软规则：降仓
    risk_mult = 1.0
    if flags.get("parabolic") and (rr_main or 0) < 2.5:
        soft.append({"rule": "S1", "detail": "抛物线高潮后首次恢复，净RR<2.5，仓位减半"})
        risk_mult *= 0.5
    if flags.get("trample") and not flags.get("second_bar_confirmed"):
        soft.append({"rule": "S2", "detail": "踩踏继承区未见第二根确认，仓位减半"})
        risk_mult *= 0.5
    if flags.get("decaying") and (rr_main or 0) < 2.0:
        soft.append({"rule": "S3", "detail": "衰减边缘且净RR<2.0，仓位减半"})
        risk_mult *= 0.5
    return {
        "verdict": "reject" if hard else "pass",
        "hard_hits": hard,
        "soft_hits": soft,
        "risk_mult": risk_mult,
        "rr_by_target": rr_by_target,
    }
