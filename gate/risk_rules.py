"""裁决层：AI 提议，代码否决。只能否决或降仓，不能改计划、不能放宽。

硬规则（违反即拒绝）：H1 净 RR、H2 止损结构外、H3 单笔风险上限、
H4 入场截止、H5 引用完整性（引用了置信「未定」的特征）、H6 模式停牌。
软规则（降仓不拒绝）：S1 抛物线高潮折扣、S2 踩踏继承、S3 衰减边缘。
每次裁决返回命中的规则编号与数值明细，写入日志供改规证据统计。
"""

import math

from perception.features import load_config

RR_MIN = 1.5
RISK_FRAC_MAX = 0.01  # core 红线 3「单笔风险 1%」；原为 0.015，源自方案原文
# 的「1% 到 1.5%」，未跟冻结口径收窄（2026-10-30 对齐）
CUTOFF_LEFT = 10  # trainer 局内：距窗口末尾不足 10 根不开仓
CONTEXTS = ("上升", "下降", "震荡")  # 语境枚举，与 perception 趋势标签一致


def _net_rr(entry, stop, target, fees, limit_in=False):
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    fin = fees["limit_in"] if limit_in else fees["market_in"]
    cost = entry * fin + target * fees["out"]
    return (abs(target - entry) - cost) / (risk + entry * fin + entry * fees["out"])


def _round_step(price):
    """该价位上「整数关口」的密度：按数量级取 mag/20。

    1.58 → 0.05（1.55 / 1.60 这类关口）；11.80 → 0.5（11.5 / 12.0）；
    3450 → 50（3400 / 3450）。价格非法返回 None。
    """
    if not price or price <= 0:
        return None
    mag = 10 ** math.floor(math.log10(price))
    return mag / 20.0


def _round_level(price):
    """离 price 最近的整数关口价。"""
    step = _round_step(price)
    return None if step is None else round(price / step) * step


def adjudicate(plan, pack, *, bars_left, feature_refs=(), flags=None, ledger=None,
               mode="annotation"):
    """plan: {side, entry, stop, targets[], risk_frac, limit_in?}
    flags: {parabolic, trample, decaying, second_bar_confirmed}
    ledger: {(setup, 语境): {'n': int, 'wins': int}}，语境须为
    plan['context'] 且取值在 CONTEXTS 枚举内，否则 H6 不查（结果里 notes 会
    写明原因，不让规则静默失效）。
    mode: "annotation"（标注/试点，默认）或 "trainer"（局内）。
    bars_left: 距**局内窗口**末尾还剩几根。仅 mode="trainer" 时参与 H4；
    annotation 下该参数无意义，传未来窗长度或任意值都不影响裁决（core 红线 4
    2026-10-30 定版：入场截止只约束 trainer 局内）。"""
    cfg = load_config()
    fees = cfg["fees"]
    flags = flags or {}
    hard, soft = [], []
    rr_by_target = [
        _net_rr(plan["entry"], plan["stop"], t, fees, plan.get("limit_in", False))
        for t in plan["targets"]
    ]
    # H1 按**首目标**计价：回放（eval/replay.simulate_trade）就按 targets[0]
    # 结算，门槛必须与结算同口径。原先取末级目标，等于「加一个远目标就能
    # 过 1.5 门槛」，是「目标改近」的反向利用（2026-10-30 修正）。
    rr_main = rr_by_target[0] if rr_by_target else None
    # 软规则另用末级目标的 RR：S1–S3 的阈值（2.5 / 2.0）是按末级口径标的，
    # 直接换首目标会让它们几乎恒成立。此处保持原标定，阈值重标定另案。
    rr_soft = rr_by_target[-1] if rr_by_target else None
    # H1 净 RR（按首目标计价，与回放结算同口径）
    if rr_main is None or rr_main < RR_MIN:
        hard.append({"rule": "H1", "detail": f"净RR={rr_main} < {RR_MIN}（首目标）"})
    # H2 止损在结构外：止损须越过入场最近一侧的摆动极值（大小级别合并看；
    # 2026-10-30 修正：原先只看大级别摆动，DOT A2 案的第二腿高点 1.576
    # 只是小级别摆动，大级别最近高点远在 1.896，合理止损 1.585 被误杀）
    swings = pack.get("swings", {}).get("major", []) + pack.get("swings", {}).get("minor", [])
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
    if seg_avg:
        level = _round_level(stop)
        # 紧口径：止损须**几乎正好**压在关口上才算命中（容差 5% 个关口步长）。
        # 原判据 abs(stop-round(stop))<0.02*seg_avg 只对「整数报价」资产成立，
        # 1.58 这类价格 round() 到 2，差 0.42 永不命中——规则实际是死代码。
        if level is not None and abs(stop - level) <= 0.05 * _round_step(stop):
            hard.append({"rule": "H2", "detail": f"止损 {stop} 压整数关口 {level:g}"})
    # H3 风险上限
    if plan.get("risk_frac", 0) > RISK_FRAC_MAX:
        hard.append({"rule": "H3", "detail": f"risk_frac={plan.get('risk_frac')} > {RISK_FRAC_MAX}"})
    # H4 入场截止（只约束 trainer 局内；标注/试点以决策点为「当下」）
    if mode == "trainer" and bars_left < CUTOFF_LEFT:
        hard.append({"rule": "H4", "detail": f"距局内窗口末尾 {bars_left} 根 < {CUTOFF_LEFT}"})
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
    # 台账键是 (setup, 语境)，语境必须是枚举 上升/下降/震荡——否则永远查不中，
    # 规则静默失效（试点原先把假设 statement 自由文本塞进 context，即此坑）。
    notes = []
    context = plan.get("context")
    if ledger is None:
        notes.append("H6 未生效：未提供台账")
    elif context not in CONTEXTS:
        notes.append(f"H6 未生效：context={context!r} 不在枚举 {CONTEXTS}")
    else:
        st = ledger.get((plan["setup"], context))
        if st and st.get("n", 0) >= 3 and st.get("wins", 0) == 0:
            hard.append({"rule": "H6", "detail": f"{plan['setup']}×{context} 样本{st['n']} 0胜，停牌"})
    # 软规则：降仓（用末级目标 RR，保持 S1–S3 原标定口径）
    risk_mult = 1.0
    if flags.get("parabolic") and (rr_soft or 0) < 2.5:
        soft.append({"rule": "S1", "detail": "抛物线高潮后首次恢复，净RR<2.5，仓位减半"})
        risk_mult *= 0.5
    if flags.get("trample") and not flags.get("second_bar_confirmed"):
        soft.append({"rule": "S2", "detail": "踩踏继承区未见第二根确认，仓位减半"})
        risk_mult *= 0.5
    if flags.get("decaying") and (rr_soft or 0) < 2.0:
        soft.append({"rule": "S3", "detail": "衰减边缘且净RR<2.0，仓位减半"})
        risk_mult *= 0.5
    return {
        "verdict": "reject" if hard else "pass",
        "hard_hits": hard,
        "soft_hits": soft,
        "risk_mult": risk_mult,
        "rr_by_target": rr_by_target,
        "notes": notes,
    }
