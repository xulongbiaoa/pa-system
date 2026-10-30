"""判断/反思 JSON 的轻量校验（无第三方依赖）。

除结构校验外，强制两条本系统裁定：
- 假设不许带数字权重（weight/weights/probability 键出现即拒）；
- 反思输出的 new_rule_proposed 必须为 false（改规走独立提案流程）。
"""

SETUPS = {"B1", "B2", "B3", "A1", "A2", "C1"}
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
        if not c.get("feature_refs"):
            errs.append("candidate 必须引用至少一个特征字段")
        if c.get("qualified"):
            p = c.get("plan")
            if not p:
                errs.append("qualified 候选必须带 plan")
            else:
                for k in ("entry", "stop", "targets", "void_if", "risk_frac"):
                    if k not in p:
                        errs.append(f"plan 缺字段 {k}")
                v = p.get("void")
                if v is not None:
                    if not isinstance(v, dict) or not isinstance(v.get("level"), (int, float)):
                        errs.append("plan.void.level 必须是数字")
                    if isinstance(v, dict) and v.get("side") not in ("above", "below"):
                        errs.append("plan.void.side 必须是 above/below")
    if not (j.get("candidates")) and j.get("no_trade_reason") not in NO_TRADE:
        errs.append("无候选时 no_trade_reason 必须是枚举值")
    return errs


def validate_reflection(r):
    errs = _scan_banned(r)
    if r.get("category") not in ("A", "B", "C", "D", "E"):
        errs.append("category 必须是 A–E")
    if r.get("new_rule_proposed") is not False:
        errs.append("new_rule_proposed 必须为 false")
    if r.get("allowed_action") not in ("记账", "强化裁决", "补感知测试", "补反例样本", "入骨架外池"):
        errs.append("allowed_action 不在枚举内")
    return errs
