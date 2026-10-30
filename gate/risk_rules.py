"""裁决层：AI 提议，代码否决。只能否决或降仓，不能改计划、不能放宽。

硬规则（违反即拒绝）：H1 净 RR、H2 止损结构外、H3 单笔风险上限、
H4 入场截止、H5 引用完整性（引用了置信「未定」的特征）、H6 模式停牌、
H7 条件矩阵（契约 v2：必需/否决逐项执法，G1 另查矩阵完整性、
R2 同源组数与最强反证）。
软规则（降仓不拒绝）：S1 抛物线高潮折扣、S2 踩踏继承、S3 衰减边缘。
每次裁决返回命中的规则编号与数值明细，写入日志供改规证据统计。
"""

import math

from perception.features import load_config, net_rr as _net_rr


RR_MIN = 1.5
RISK_FRAC_MAX = 0.01  # core 红线 3「单笔风险 1%」；原为 0.015，源自方案原文
# 的「1% 到 1.5%」，未跟冻结口径收窄（2026-10-30 对齐）
CUTOFF_LEFT = 10  # trainer 局内：距窗口末尾不足 10 根不开仓
CONTEXTS = ("上升", "下降", "震荡")  # 语境枚举，与 perception 趋势标签一致


def _rr(entry, stop, target, fees, limit_in=False):
    """薄包装：净 RR 的唯一实现在 perception.features.net_rr，此处只补 side
    形参（公式本身与方向无关，用绝对幅度）。"""
    return _net_rr(entry, stop, target, None, fees, limit_in=limit_in)


def _rr_gross(entry, stop, target):
    """毛 RR（未扣费），只用于和设计目标比差距——用户说的「盈亏比 2:1」
    是毛口径（赢 2R 亏 1R），拿净 RR 去比会让每个合格的 2:1 单都显示差
    0.03，属于自找的误读。"""
    risk = abs(entry - stop)
    return round(abs(target - entry) / risk, 4) if risk > 0 else None


def net_rr_of_design_target(stop_frac=0.01, cfg=None, limit_in=False):
    """设计目标（毛 2:1）在给定止损宽度下的**净** RR。

    毛 RR 是设计目标，红线 1 是净 RR 地板，两者不同量纲。费用按价格收，
    所以止损越窄，费用占风险的比例越大，净 RR 越低：

        止损占价 0.5% → 净 1.499   1.0% → 1.726   5.0% → 1.940

    这意味着两件事：① 地板不能抬到 2.0 净（会把所有合格的 2:1 单拒掉，
    实测 9/9）；② 做 2:1 的止损不能窄于约 0.5% 的价格，否则费用本身就
    把单子压到地板以下——这不是规则问题，是费用算术。
    """
    cfg = cfg or load_config()
    target_rr = cfg.get("target_rr")
    if not target_rr:
        return None
    risk = float(stop_frac)
    entry, stop = 1.0, 1.0 - risk
    target = entry + target_rr * risk
    return _net_rr(entry, stop, target, None, cfg["fees"], limit_in=limit_in)


def min_stop_frac_for_floor(rr_min=RR_MIN, cfg=None, hi=0.5):
    """反解：毛 2:1 的止损至少要占价格多少，净 RR 才过得去 rr_min。

    二分而非解析解——解析解依赖费用只按价格线性收这个假设，一旦费率结构
    变成固定佣金就不成立；二分对任何费用结构都成立。
    """
    lo = 1e-6
    if (net_rr_of_design_target(hi, cfg) or 0) < rr_min:
        return None  # 止损再宽也过不了（地板高过毛目标能给的净 RR）
    for _ in range(80):
        mid = (lo + hi) / 2
        if (net_rr_of_design_target(mid, cfg) or 0) < rr_min:
            lo = mid
        else:
            hi = mid
    return round(hi, 6)


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
    """plan: {side, entry, stop, targets[], risk_frac, order_type?, limit_in?}
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
    target_rr = cfg.get("target_rr")  # 设计目标（毛口径），None = 未声明
    flags = flags or {}
    # 下单方式口径统一（2026-10-30 复核）：schema 只认 order_type，gate 原先只读
    # limit_in，两套键名并存 → 判断层写 limit 的单子按**市价**费率算 RR，H1 永远
    # 吃不到限价优惠，回放又按市价费率结算。这里以 order_type 为准，保留
    # limit_in 兼容旧调用。
    limit_in = (plan.get("order_type") == "limit") or bool(plan.get("limit_in"))
    hard, soft = [], []
    notes = []
    rr_by_target = [
        _rr(plan["entry"], plan["stop"], t, fees, limit_in)
        for t in plan["targets"]
    ]
    rr_gross = (_rr_gross(plan["entry"], plan["stop"], plan["targets"][0])
                if plan.get("targets") else None)
    # 现价口径（2026-10-30 修正）：H1 只认「不优于现价的入场价」算出来的 RR。
    #
    # 原口径只看计划自己的 entry，于是把入场价往有利方向挪一点就能无界放大
    # 承诺净 RR——做空入场价抬 2%，风险分母 (stop−entry) 缩小，RR 从 2.59 涨
    # 到 7.98，H1/H2/H3 全过；但止损时 R ≈ −1 − 费用/风险，风险越小 |R| 越大，
    # 实现 R 从 −1.031 反而恶化到 −1.083。**承诺 RR 与实际亏损方向相反**，
    # 这是与「加远目标过门槛」同族的分母侧利用。
    #
    # 修法取 element-wise min：计划入场价优于现价时按现价重算（该价必然可达），
    # 劣于现价时保留计划口径（不奖励追单）。零新常数；市价单 entry≈现价，
    # 行为不变。
    #
    # 限价计划豁免（2026-10-31 用户裁定，按 Brooks 原册）：限价单是事前
    # 声明的挂单价，阿布的交易者等式锚在自己的入场价（v30 slide 34：
    # risk/reward 均从 entry price 起算；slide 72/74：50% 回踩限价单按
    # 限价位算 risk=reward）。故 limit_in 的计划 rr_gate 直接取计划口径，
    # 不再与现价取 min。防滥用由三件套兜底：① 成交须穿越限价（回放
    # simulate_limit_trade 从严口径），RR 承诺只能在真实成交后兑现；
    # ② 未成交单单独留档统计，未成交率即这类计划的诚实度量；③ 红线 4
    # 禁事后挑价，限价必须是决策点当时写明的价。现价口径 RR 仍算出并
    # 记入 notes 供对照。市价计划维持 min 口径不变。
    px = pack.get("last_close")
    rr_at_decision = None
    if px:
        rr_at_decision = [
            _rr(px, plan["stop"], t, fees, limit_in)
            for t in plan["targets"]
        ]
    rr_gate = rr_by_target
    if limit_in:
        if rr_at_decision:
            notes.append(
                f"H1 按限价入场价 {plan['entry']} 计价（2026-10-31 裁定）；"
                f"现价口径净RR {rr_at_decision[0]} 仅作对照"
            )
    elif rr_at_decision:
        rr_gate = [min(a, b) for a, b in zip(rr_by_target, rr_at_decision)]
        if rr_gate[0] != rr_by_target[0]:
            notes.append(
                f"H1 按现价 {px} 计价：计划入场价 {plan['entry']} 优于现价，"
                f"净RR {rr_by_target[0]} → {rr_gate[0]}"
            )
    # H1 按**首目标**计价：回放（eval/replay.simulate_trade）就按 targets[0]
    # 结算，门槛必须与结算同口径。原先取末级目标，等于「加一个远目标就能
    # 过 1.5 门槛」，是「目标改近」的反向利用（2026-10-30 修正）。
    rr_main = rr_gate[0] if rr_gate else None
    # H1 净 RR（按首目标计价，与回放结算同口径；计价基点：市价计划取
    # 现价与计划入场价的 element-wise min，限价计划取限价入场价）
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
    # 2026-10-31 审计修复：原先只查 gaps/ema/trend 三个根，fortress/mm/
    # pullback/trend_age 的置信不查——判读引用「未定」置信的 MM 候选作
    # 放行依据时无人拦。改通用口径：包里任何带 confidence 字段的子包，
    # 被 feature_refs 引用且置信「未定」即拒。
    conf = {k: v.get("confidence") for k, v in pack.items()
            if isinstance(v, dict) and "confidence" in v}
    for ref in feature_refs:
        root = ref.split(".")[0]
        if conf.get(root) == "未定":
            hard.append({"rule": "H5", "detail": f"引用了未定特征 {ref}"})
    # H6 模式停牌
    # 台账键是 (setup, 语境)，语境必须是枚举 上升/下降/震荡——否则永远查不中，
    # 规则静默失效（试点原先把假设 statement 自由文本塞进 context，即此坑）。
    context = plan.get("context")
    if ledger is None:
        notes.append("H6 未生效：未提供台账")
    elif context not in CONTEXTS:
        notes.append(f"H6 未生效：context={context!r} 不在枚举 {CONTEXTS}")
    else:
        st = ledger.get((plan["setup"], context))
        if st and st.get("n", 0) >= 3 and st.get("wins", 0) == 0:
            # 2026-10-31 审计修复（防误杀）：原阈值 n≥3 即硬停牌，但真胜率
            # 45% 的模式连输 3 把的概率约 17%，且与本系统「绩效 n<30 不下
            # 结论」的回放纪律矛盾。硬停牌抬到 n≥8；n=3..7 只记观察。
            if st["n"] >= 8:
                hard.append({"rule": "H6", "detail": f"{plan['setup']}×{context} 样本{st['n']} 0胜，停牌"})
            else:
                notes.append(
                    f"H6 观察：{plan['setup']}×{context} 样本{st['n']} 0胜，"
                    f"未达硬停牌门槛（n≥8），只记观察不拒")
        elif not st or not st.get("n"):
            # 传了台账但这一格是空的：和「没传台账」是两件事，不许静默。
            # 2026-10-30 复核发现：传 {} 看起来像接好了，实际 H6 从未生效。
            n_cell = (st or {}).get("n", 0)
            notes.append(
                f"H6 未生效：台账无 {plan['setup']}×{context} 样本（n={n_cell}）"
            )
    # H7 条件矩阵（契约 v2，2026-10-30 落地）：带 conditions 的计划逐项
    # 执法；G1 强制带矩阵。原则（应用建设方案 §3.2）：必需项全 met 才
    # 放行、任一否决 met 即拒、关键否决 unknown 同样拒；增强项只加成色，
    # 不能抵必需缺失或否决触发。G1 的 R2 另查同源组数——前高/区间上沿/
    # 阻力同出一高点只算一组证据，「多证据」不许同源凑数。
    conds = plan.get("conditions")
    if plan.get("setup") == "G1" or conds:
        if not conds:
            hard.append({"rule": "H7", "detail": "G1 候选缺 conditions 条件矩阵"})
            conds = []
        by_id = {}
        for cd in conds:
            if isinstance(cd, dict) and cd.get("rule_id"):
                by_id[cd["rule_id"]] = cd
            if not isinstance(cd, dict):
                continue
            role, status = cd.get("role"), cd.get("status")
            if role == "required" and status != "met":
                hard.append({"rule": "H7", "detail":
                             f"必需条件 {cd.get('rule_id')} 状态 {status} ≠ met"})
            if role == "veto" and status == "met":
                hard.append({"rule": "H7", "detail":
                             f"否决条件 {cd.get('rule_id')} 已触发"})
            if role == "veto" and status == "unknown":
                hard.append({"rule": "H7", "detail":
                             f"否决条件 {cd.get('rule_id')} 未定，不可放行"})
        if plan.get("setup") == "G1":
            for rid in ("R1", "R2", "R3", "V1", "V2", "V3"):
                if rid not in by_id:
                    hard.append({"rule": "H7", "detail": f"G1 矩阵缺条件 {rid}"})
            # 维度错位执法（与 validate 同一映射，两层都查）：必需三项
            # 必须各占其固定维度（账本/位置/触发），把 R2 的一堆同维锚
            # 申报成多个维度 = 维度造假，与同源凑数同罪。
            for rid, dim in (("R1", "账本"), ("R2", "位置"), ("R3", "触发")):
                cd = by_id.get(rid)
                if cd is not None and cd.get("dimension") != dim:
                    hard.append({"rule": "H7", "detail":
                                 f"{rid} 维度错位：申报 {cd.get('dimension')}，应为 {dim}"})
            r2 = by_id.get("R2")
            if r2 is not None and len(set(r2.get("groups") or [])) < 2:
                hard.append({"rule": "H7", "detail":
                             "R2 落点叠加同源组 <2（同源证据不算第二锚）"})
            if not (plan.get("strongest_countercase") or "").strip():
                hard.append({"rule": "H7", "detail": "G1 候选缺 strongest_countercase"})
    # 软规则：降仓。
    # 2026-10-30 去掉 S1/S3 的 RR 条件：设计目标定为盈亏比 2:1（净 RR ≈ 1.95）
    # 后，S1 的 `< 2.5` 与 S3 的 `< 2.0` 对**每一个**合格计划都恒成立，条件
    # 实际是死代码，只剩「抛物线就减半」「衰减就减半」在起作用。与其留一个
    # 永远为真的条件让人以为还有闸门，不如写明它是无条件减仓。
    # 注意这是**收紧**：净 RR ≥ 2.5 的计划原先逃过 S1，现在也要减半。方向与
    # 「裁决层只能否决或降仓」一致，故无需另案；若要改回有条件，须先证明
    # 高 RR 能豁免抛物线风险，那是放宽，要证据。
    risk_mult = 1.0
    if flags.get("parabolic"):
        soft.append({"rule": "S1", "detail": "抛物线高潮后首次恢复，仓位减半"})
        risk_mult *= 0.5
    if flags.get("trample") and not flags.get("second_bar_confirmed"):
        soft.append({"rule": "S2", "detail": "踩踏继承区未见第二根确认，仓位减半"})
        risk_mult *= 0.5
    if flags.get("decaying"):
        soft.append({"rule": "S3", "detail": "衰减边缘，仓位减半"})
        risk_mult *= 0.5
    # 凯利 sizing 已于 2026-10-31 按用户裁定整体移除（从未生效、用不到，
    # 不留）：仓位只由骨架硬数字决定（风险 100/笔、H3 上限 1%），裁决层
    # 不再给仓位建议。台账只保留 H6 需要的 n/wins。
    return {
        "verdict": "reject" if hard else "pass",
        "hard_hits": hard,
        "soft_hits": soft,
        "risk_mult": risk_mult,
        "rr_by_target": rr_by_target,          # 计划自己入场价算的（留档，不改语义）
        "rr_by_target_at_decision": rr_at_decision,  # 按现价重算的
        "rr_gate": rr_gate,                    # element-wise min，H1/S1–S3 实际用的
        "decision_price": px,
        # 设计目标（用户 2026-10-30 定「盈亏比 2:1」= 毛 RR 2.0）：只报差距，不否决。
        # 红线 1 的 1.5 是**地板**，不是目标；目标进这里是为了让「离自己想做的
        # 单子差多远」在每份裁决里可见，而不是等人工去比。毛口径对毛口径比。
        "target_rr": target_rr,
        "rr_gross": rr_gross,
        "rr_gap_to_target": None if (rr_gross is None or target_rr is None)
        else round(rr_gross - target_rr, 4),
        "notes": notes,
    }
