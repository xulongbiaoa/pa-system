"""反思归因初分测试。"""

from judge.reflect import reflect

J = {"candidates": [{"feature_refs": ["trend.label"]}], "hypotheses": []}


def test_stop_hit_is_variance():
    r = reflect(J, {"segment": "s1", "setup": "A1", "exit_reason": "stop", "net_r": -1.02})
    assert r["category"] == "E" and r["allowed_action"] == "记账"
    assert r["new_rule_proposed"] is False and r["matches_original"] is True


def test_window_end_is_execution():
    r = reflect(J, {"segment": "s1", "setup": "A1", "exit_reason": "window_end", "net_r": 0.3})
    assert r["category"] == "D" and r["matches_original"] is False


def test_undefined_feature_ref_is_perception():
    j = {"candidates": [{"feature_refs": ["fortress.band（未定）"]}], "hypotheses": []}
    r = reflect(j, {"segment": "s1", "setup": "B1", "exit_reason": "stop", "net_r": -1.0})
    assert r["category"] == "A" and r["allowed_action"] == "补感知测试"
