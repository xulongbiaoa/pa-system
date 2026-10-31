"""判断/反思 JSON 的轻量校验（无第三方依赖）。

除结构校验外，强制两条本系统裁定：
- 假设不许带数字权重（weight/weights/probability 键出现即拒）；
- 反思输出的 new_rule_proposed 必须为 false（改规走独立提案流程）。
"""

SETUPS = {"B1", "B2", "B3", "A1", "A2", "C1", "G1"}
COND_ROLES = {"required", "enhancing", "veto"}
COND_STATUS = {"met", "not_met", "unknown", "not_applicable"}
# G1 条件矩阵的必需/否决项（定义在 knowledge/setups/G1-confluence-gap.md，
# 校验器与裁决层 H7 共用同一份名单，改卡必须同步改这里）
G1_REQUIRED = ("R1", "R2", "R3")
G1_VETO = ("V1", "V2", "V3")
# 维度固定映射（用户 2026-10-30 定：多证据按维度计数，同维只算一票；
# 维度由 rule_id 定死，判断层申报错位即造假/误读，两层都拒）
COND_DIMENSIONS = {"账本", "位置", "过程", "触发", "背景", "反证", "风险"}
G1_DIMENSION_MAP = {
    "R1": "账本", "R2": "位置", "R3": "触发",
    "E1": "触发", "E2": "位置", "E3": "过程", "E4": "背景",
    "V1": "反证", "V2": "账本", "V3": "位置",
}
NO_TRADE = {"无命中", "位置不对", "成色不合格", "背景不明", "感知未定"}
BANNED_KEYS = {"weight", "weights", "probability", "prob"}


def _scan_banned(obj, path="$"):
    errs = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in BANNED_KEYS:
                errs.append(f"{path}.{k}: 禁止数字权重字段")
            errs += _scan_banned(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            errs += _scan_banned(v, f"{path}[{i}]")
    return errs


def validate_judgment(j):
    errs = _scan_banned(j)
    if not isinstance(j, dict):
        return ["顶层必须是对象"]
    for k in ("context", "primary", "hypotheses", "candidates", "uncertainty"):
        if k not in j:
            errs.append(f"缺字段 {k}")
    if j.get("context") is not None and j["context"] not in ("上升", "下降", "震荡"):
        errs.append("context 必须是 上升/下降/震荡")
    # 顶层只许契约字段：A/B 实验里生成方自创 market_purpose 等键 5 例，
    # schema 的 additionalProperties=false 必须在轻量校验里也成立。
    allowed = {"context", "primary", "hypotheses", "candidates",
               "no_trade_reason", "pending_conditions", "uncertainty"}
    for k in j:
        if k not in allowed:
            errs.append(f"顶层未知字段 {k}（契约外）")
    hyps = j.get("hypotheses") or []
    if isinstance(hyps, dict):
        # 生成方把 hypotheses 写成 {main: ..., backup: ...} 对象式（A/B 实验
        # 实测两例）——校验器的职责是报错，不是崩溃（原先在此 AttributeError
        # 把整段打分打断）。其余非 list 形状同理。
        errs.append("hypotheses 必须是数组（主假设在前），不是对象")
        hyps = []
    if not (1 <= len(hyps) <= 3):
        errs.append("hypotheses 须 1–3 个")
    ids = set()
    for h in hyps:
        if not isinstance(h, dict):
            errs.append("hypothesis 必须是对象")
            continue
        for k in ("id", "statement", "holds_if", "void_if", "takeover_if", "menu"):
            if k not in h:
                errs.append(f"hypothesis 缺字段 {k}")
        ids.add(h.get("id"))
    if hyps and j.get("primary") not in ids:
        errs.append("primary 必须指向某个 hypothesis id")
    for c in j.get("candidates") or []:
        if c.get("setup") not in SETUPS:
            errs.append(f"未知 setup: {c.get('setup')}")
        if c.get("side") not in ("long", "short"):
            errs.append("candidate.side 必须是 long/short")
        # 方向定版（2026-10-31 分支 A/B 抓到 A2 标多头）：A1 只多、
        # A2 只空，其余 setup 双向合法
        if c.get("setup") == "A1" and c.get("side") != "long":
            errs.append("A1（M2B）只许多头")
        if c.get("setup") == "A2" and c.get("side") != "short":
            errs.append("A2（M2S）只许空头")
        if not c.get("feature_refs"):
            errs.append("candidate 必须引用至少一个特征字段")
        _validate_conditions(c, errs)
        if c.get("qualified"):
            p = c.get("plan")
            if not p:
                errs.append("qualified 候选必须带 plan")
            else:
                for k in ("entry", "stop", "targets", "void_if", "risk_frac"):
                    if k not in p:
                        errs.append(f"plan 缺字段 {k}")
                # 结构化 void 必备（2026-10-31 审计处置）：回放只执行
                # 结构化 void，自由文本 void_if 不出场——只写文字版等于
                # 前提破无人管（红线 5 半执行）。qualified 计划缺 void
                # 直接判格式不合格。
                if "void" not in p:
                    errs.append("plan 缺结构化 void（前提失效必须可执行，"
                                "自由文本 void_if 不算）")
                v = p.get("void")
                if v is not None:
                    if not isinstance(v, dict) or not isinstance(v.get("level"), (int, float)):
                        errs.append("plan.void.level 必须是数字")
                    if isinstance(v, dict) and v.get("side") not in ("above", "below"):
                        errs.append("plan.void.side 必须是 above/below")
    if not (j.get("candidates")) and j.get("no_trade_reason") not in NO_TRADE:
        errs.append("无候选时 no_trade_reason 必须是枚举值")
    # pending_conditions 结构化（2026-10-30 职责归位）：字符串是旧格式、
    # 容忍存量；对象形式必须带合法 setup 与非空 missing，否则近失信息
    # 等于白写。
    for pc in j.get("pending_conditions") or []:
        if isinstance(pc, dict):
            if pc.get("setup") not in SETUPS:
                errs.append(f"pending_conditions 的 setup 非法：{pc.get('setup')}")
            if not (isinstance(pc.get("missing"), list) and pc["missing"]):
                errs.append("pending_conditions 对象必须带非空 missing 数组")
            # 依据引用（2026-10-31 Build 1）：missing 的对象形式必须三键
            # 齐全、basis 合法；card 引用的条目号必须属于本 pending 的
            # setup；branch 引用必须是点位号；extra 必须自述理由。
            # 字符串项是存量旧格式，容忍不验。
            import re as _re
            for mi in pc.get("missing") or []:
                if not isinstance(mi, dict):
                    continue
                for k in ("condition", "evidence", "basis"):
                    if not mi.get(k):
                        errs.append(f"pending missing 对象缺 {k}：{mi!r:.80}")
                b = mi.get("basis") or {}
                bt, ref = b.get("type"), b.get("ref") or ""
                if bt not in ("branch", "card", "skeleton", "extra"):
                    errs.append(f"pending missing basis.type 非法：{bt!r}")
                elif bt == "card" and not _re.fullmatch(
                        _re.escape(pc.get("setup") or "") + r"-[NBVR]\d+", ref):
                    errs.append(f"card 引用必须为本 setup 条目号（{pc.get('setup')}-N/B/V/R#）：{ref!r}")
                elif bt == "branch" and not _re.fullmatch(r"P\d+", ref):
                    errs.append(f"branch 引用必须是点位号 P#：{ref!r}")
                elif bt in ("skeleton", "extra") and not ref.strip():
                    errs.append(f"basis={bt} 必须写明 ref（条款名/加码理由）")
    return errs


def _validate_conditions(c, errs):
    conds = c.get("conditions")
    if conds is None:
        if c.get("setup") == "G1" and c.get("qualified"):
            errs.append("G1 合格候选必须带 conditions 条件矩阵")
        return
    if not isinstance(conds, list):
        errs.append("conditions 必须是数组")
        return
    for cd in conds:
        if not isinstance(cd, dict):
            errs.append("condition 必须是对象")
            continue
        for k in ("rule_id", "role", "status", "evidence_refs", "groups"):
            if k not in cd:
                errs.append(f"condition 缺字段 {k}")
        if cd.get("role") not in COND_ROLES:
            errs.append(f"condition.role 必须是 required/enhancing/veto：{cd.get('rule_id')}")
        if cd.get("status") not in COND_STATUS:
            errs.append(f"condition.status 不在枚举内：{cd.get('rule_id')}")
        if cd.get("status") == "met" and not cd.get("evidence_refs"):
            errs.append(f"condition {cd.get('rule_id')} 声明 met 必须带 evidence_refs")
        if not isinstance(cd.get("groups"), list):
            errs.append(f"condition {cd.get('rule_id')} 的 groups 必须是数组（证据同源组）")
        if c.get("setup") == "G1":
            dim = cd.get("dimension")
            if dim not in COND_DIMENSIONS:
                errs.append(f"G1 condition {cd.get('rule_id')} 必须申报 dimension（证据维度）")
            elif G1_DIMENSION_MAP.get(cd.get("rule_id")) not in (None, dim):
                errs.append(
                    f"G1 condition {cd.get('rule_id')} 维度错位：申报 {dim}，"
                    f"固定映射 {G1_DIMENSION_MAP[cd['rule_id']]}")
    if c.get("setup") == "G1" and c.get("qualified"):
        ids = {cd.get("rule_id") for cd in conds if isinstance(cd, dict)}
        for rid in G1_REQUIRED + G1_VETO:
            if rid not in ids:
                errs.append(f"G1 候选缺条件 {rid}（矩阵不完整）")
        if not (c.get("strongest_countercase") or "").strip():
            errs.append("G1 合格候选必须写 strongest_countercase（最强反证）")


def validate_reflection(r):
    errs = _scan_banned(r)
    if r.get("category") not in ("A", "B", "C", "D", "E"):
        errs.append("category 必须是 A–E")
    if r.get("new_rule_proposed") is not False:
        errs.append("new_rule_proposed 必须为 false")
    if r.get("allowed_action") not in ("记账", "强化裁决", "补感知测试", "补反例样本", "入骨架外池"):
        errs.append("allowed_action 不在枚举内")
    return errs
