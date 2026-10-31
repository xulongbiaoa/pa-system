"""H7 条件矩阵测试（契约 v2）：必需/否决逐项执法、同源去重、
增强项不抵必需缺失、非 G1 无矩阵不受影响。"""

from gate.risk_rules import adjudicate


def _pack():
    return {
        "swings": {"major": [{"bar": 5, "kind": "L", "close": 95.0, "anchor": 94.3}]},
        "seg_avg_range": 2.0,
        "gaps": {"confidence": "确定"},
        "ema": {"confidence": "确定"},
        "trend": {"confidence": "确定"},
    }


DIMS = {"R1": "账本", "R2": "位置", "R3": "触发", "E1": "触发",
        "E2": "位置", "V1": "反证", "V2": "账本", "V3": "位置"}


def _cond(rid, role, status, groups=("g1",), refs=("gaps.open[0]",)):
    return {"rule_id": rid, "role": role, "status": status,
            "dimension": DIMS[rid],
            "evidence_refs": list(refs) if status == "met" else [],
            "groups": list(groups), "note": ""}


def _matrix(**over):
    m = [
        _cond("R1", "required", "met", ("gap-anchor",)),
        _cond("R2", "required", "met", ("gap-anchor", "mm-target")),
        _cond("R3", "required", "met", ("arrival",)),
        _cond("E1", "enhancing", "met", ("arrival",)),
        _cond("E2", "enhancing", "not_met"),
        _cond("V1", "veto", "not_met"),
        _cond("V2", "veto", "not_met"),
        _cond("V3", "veto", "not_met"),
    ]
    for cd in m:
        if cd["rule_id"] in over:
            cd.update(over[cd["rule_id"]])
    return m


def _plan(**kw):
    p = {
        "side": "long", "entry": 100.0, "stop": 93.87,
        "targets": [110.0], "risk_frac": 0.01,
        "cap_reason": "110 完好要塞封顶（H8 说明义务，毛 RR 1.63）",
        "stop_basis": 94.3,
        "setup": "G1", "context": "上升",
        "conditions": _matrix(),
        "strongest_countercase": "缺口被一根强阴线回补关闭，立论消失",
    }
    p.update(kw)
    return p


def _h7(r):
    return [h for h in r["hard_hits"] if h["rule"] == "H7"]


def test_g1_full_matrix_passes():
    r = adjudicate(_plan(), _pack(), bars_left=50, feature_refs=["trend.label"])
    assert r["verdict"] == "pass" and not _h7(r)


def test_g1_missing_conditions_rejected():
    p = _plan()
    del p["conditions"]
    r = adjudicate(p, _pack(), bars_left=50)
    assert r["verdict"] == "reject" and _h7(r)


def test_required_not_met_rejected():
    r = adjudicate(_plan(conditions=_matrix(R3={"status": "not_met"})),
                   _pack(), bars_left=50)
    assert any("R3" in h["detail"] for h in _h7(r))


def test_required_unknown_rejected():
    r = adjudicate(_plan(conditions=_matrix(R1={"status": "unknown"})),
                   _pack(), bars_left=50)
    assert any("R1" in h["detail"] for h in _h7(r))


def test_veto_met_rejected():
    r = adjudicate(_plan(conditions=_matrix(V2={"status": "met",
                                                "evidence_refs": ["gaps.closed[0]"]})),
                   _pack(), bars_left=50)
    assert any("V2" in h["detail"] for h in _h7(r))


def test_veto_unknown_rejected():
    r = adjudicate(_plan(conditions=_matrix(V1={"status": "unknown"})),
                   _pack(), bars_left=50)
    assert any("V1" in h["detail"] for h in _h7(r))


def test_r2_single_group_rejected():
    # 前高/区间上沿/阻力同出一高点：groups 只申报一组 = 同源凑数
    r = adjudicate(_plan(conditions=_matrix(R2={"groups": ["same-swing-high"]})),
                   _pack(), bars_left=50)
    assert any("R2" in h["detail"] for h in _h7(r))


def test_missing_countercase_rejected():
    r = adjudicate(_plan(strongest_countercase=""), _pack(), bars_left=50)
    assert any("countercase" in h["detail"] for h in _h7(r))


def test_enhancing_not_met_does_not_reject():
    r = adjudicate(_plan(conditions=_matrix(E1={"status": "not_met"})),
                   _pack(), bars_left=50)
    assert r["verdict"] == "pass" and not _h7(r)


def test_missing_veto_row_rejected():
    conds = [c for c in _matrix() if c["rule_id"] != "V3"]
    r = adjudicate(_plan(conditions=conds), _pack(), bars_left=50)
    assert any("V3" in h["detail"] for h in _h7(r))


def test_non_g1_without_conditions_unaffected():
    p = _plan(setup="A1")
    del p["conditions"], p["strongest_countercase"]
    r = adjudicate(p, _pack(), bars_left=50, feature_refs=["trend.label"])
    assert r["verdict"] == "pass" and not _h7(r)


def test_non_g1_with_veto_met_conditions_rejected():
    # 非 G1 自愿带矩阵：否决触发一样执法
    p = _plan(setup="B3",
              conditions=[_cond("V1", "veto", "met", refs=("x",))])
    r = adjudicate(p, _pack(), bars_left=50)
    assert any(h["rule"] == "H7" for h in r["hard_hits"])


def test_dimension_mislabel_rejected():
    # 把 R2（一堆位置锚）申报成「过程」维度充数 = 维度造假
    conds = _matrix(R2={"dimension": "过程"})
    r = adjudicate(_plan(conditions=conds), _pack(), bars_left=50)
    assert any("维度错位" in h["detail"] for h in _h7(r))
