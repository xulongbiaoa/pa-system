"""契约 v2 条件矩阵的结构校验（judge/validate）：G1 合格候选必须带
完整矩阵与最强反证；声明 met 必须带证据；角色/状态枚举执法。"""

from judge.validate import validate_judgment


def _cond(rid, role, status, refs=("gaps.open[0]",), groups=("g",)):
    return {"rule_id": rid, "role": role, "status": status,
            "evidence_refs": list(refs) if status == "met" else [],
            "groups": list(groups)}


def _matrix():
    return [
        _cond("R1", "required", "met"),
        _cond("R2", "required", "met", groups=("gap", "mm")),
        _cond("R3", "required", "met"),
        _cond("V1", "veto", "not_met"),
        _cond("V2", "veto", "not_met"),
        _cond("V3", "veto", "not_met"),
    ]


def _judgment(cand):
    return {
        "context": "上升", "primary": "H1",
        "hypotheses": [{"id": "H1", "statement": "回补缺口", "holds_if": "x",
                        "void_if": "y", "takeover_if": "", "menu": ["G1"]}],
        "candidates": [cand], "uncertainty": [],
    }


def _cand(**kw):
    c = {"setup": "G1", "side": "long", "qualified": True, "reason": "公式三齐",
         "feature_refs": ["gaps.open"],
         "plan": {"entry": 100.0, "stop": 94.0, "targets": [110.0],
                  "void_if": "收盘破落点", "risk_frac": 0.01},
         "conditions": _matrix(),
         "strongest_countercase": "缺口被强阴线回补关闭"}
    c.update(kw)
    return c


def test_g1_full_matrix_valid():
    assert validate_judgment(_judgment(_cand())) == []


def test_g1_qualified_without_conditions_errors():
    c = _cand()
    del c["conditions"]
    errs = validate_judgment(_judgment(c))
    assert any("conditions" in e for e in errs)


def test_g1_missing_veto_row_errors():
    conds = [x for x in _matrix() if x["rule_id"] != "V3"]
    errs = validate_judgment(_judgment(_cand(conditions=conds)))
    assert any("V3" in e for e in errs)


def test_g1_missing_countercase_errors():
    errs = validate_judgment(_judgment(_cand(strongest_countercase="")))
    assert any("countercase" in e for e in errs)


def test_met_without_evidence_refs_errors():
    conds = _matrix()
    conds[0]["evidence_refs"] = []
    errs = validate_judgment(_judgment(_cand(conditions=conds)))
    assert any("evidence_refs" in e for e in errs)


def test_bad_role_errors():
    conds = _matrix()
    conds[0]["role"] = "must"
    errs = validate_judgment(_judgment(_cand(conditions=conds)))
    assert any("role" in e for e in errs)


def test_g1_unqualified_without_conditions_ok():
    c = _cand(qualified=False)
    del c["conditions"], c["plan"]
    assert validate_judgment(_judgment(c)) == []
