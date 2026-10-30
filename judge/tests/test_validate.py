

def test_hypotheses_object_shape_reports_not_crashes():
    from judge.validate import validate_judgment
    j = {"primary": "main", "candidates": [], "uncertainty": [],
         "hypotheses": {"main": {"statement": "x"}, "backup": {}},
         "no_trade_reason": "位置不对"}
    errs = validate_judgment(j)
    assert any("必须是数组" in e for e in errs)
