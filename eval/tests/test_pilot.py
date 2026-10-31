"""试点管线空跑验证：两份手工判断（1 空仓 + 1 候选）走完整条管线。"""

import json
import os

from pilot_run import run
from perception.features import build_feature_pack, load_config

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
DS = os.path.join(ROOT, "eval", "datasets", "dev")


def _hyp():
    return [
        {"id": "H1", "statement": "测试假设", "holds_if": "x", "void_if": "y",
         "takeover_if": "", "menu": ["A1"]}
    ]


def test_pipeline_end_to_end(tmp_path):
    jd = tmp_path / "judgments"
    jd.mkdir()
    # 1) no_trade 判断
    seg1 = json.load(open(os.path.join(DS, "ds03.json")))
    j1 = {"context": "上升", "primary": "H1", "hypotheses": _hyp(), "candidates": [],
          "no_trade_reason": "位置不对", "pending_conditions": [], "uncertainty": []}
    (jd / "ds03.json").write_text(json.dumps(j1))
    # 2) 候选判断：按 ds04 决策点特征包机械构造一个能过裁决的计划
    seg2 = json.load(open(os.path.join(DS, "ds04.json")))
    bars = seg2["bars"][:180]
    pack = build_feature_pack(bars, [], load_config())
    entry = bars[-1]["c"]
    lows = [s["anchor"] for s in pack["swings"]["major"] if s["kind"] == "L" and s["anchor"] < entry]
    stop = (max(lows) if lows else entry * 0.98) - 0.13 * pack["seg_avg_range"]
    risk = entry - stop
    j2 = {"context": "上升", "primary": "H1", "hypotheses": _hyp(),
          "candidates": [{"setup": "A1", "side": "long", "qualified": True,
                          "reason": "管线验证用", "feature_refs": ["trend.label"],
                          "plan": {"entry": entry, "stop": stop,
                                   "targets": [entry + 1.8 * risk],
                                   "void_if": "收盘破起点", "risk_frac": 0.01,
                                   # 2026-10-31 契约：结构化 void 必备；
                                   # 毛 RR 1.8 不到 2:1 须带封顶说明（H8）
                                   "void": {"level": stop, "side": "below"},
                                   "cap_reason": "管线夹具：目标按 1.8R 构造"}}],
          "no_trade_reason": None, "pending_conditions": [], "uncertainty": []}
    (jd / "ds04.json").write_text(json.dumps(j2))
    rep = run(str(jd))
    assert rep["judged"] == 2 and rep["format_fail"] == 0
    assert rep["no_trade"] == 1
    assert len(rep["trades"]) + rep["gate_reject"] == 1


def test_pending_missing_basis_rules():
    from judge.validate import validate_judgment
    base = {"context": "上升", "primary": "H1", "hypotheses": _hyp(),
            "candidates": [], "no_trade_reason": "位置不对",
            "uncertainty": []}
    ok = dict(base, pending_conditions=[{"setup": "B3", "missing": [
        {"condition": "未收回位内", "evidence": "决策根收 100.5 在位外",
         "basis": {"type": "card", "ref": "B3-N3"}},
        {"condition": "想等更强跟进", "evidence": "决策根",
         "basis": {"type": "extra", "ref": "个人偏好"}}]}])
    assert validate_judgment(ok) == []
    bad_ref = dict(base, pending_conditions=[{"setup": "B3", "missing": [
        {"condition": "x", "evidence": "y",
         "basis": {"type": "card", "ref": "A1-N1"}}]}])
    assert any("条目号" in e for e in validate_judgment(bad_ref))
    bad_branch = dict(base, pending_conditions=[{"setup": "B3", "missing": [
        {"condition": "x", "evidence": "y",
         "basis": {"type": "branch", "ref": "触发未成立"}}]}])
    assert any("点位号" in e for e in validate_judgment(bad_branch))
    no_basis = dict(base, pending_conditions=[{"setup": "B3", "missing": [
        {"condition": "x", "evidence": "y"}]}])
    assert validate_judgment(no_basis)


def test_candidate_setup_side_lock():
    from judge.validate import validate_judgment
    base = {"context": "上升", "primary": "H1", "hypotheses": _hyp(),
            "no_trade_reason": None, "pending_conditions": [],
            "uncertainty": []}
    plan = {"entry": 100.0, "stop": 99.0, "targets": [102.0],
            "void": {"level": 99.0, "side": "below"},
            "cap_reason": "夹具"}
    bad = dict(base, candidates=[{"setup": "A2", "side": "long",
                                  "qualified": True, "reason": "x",
                                  "feature_refs": ["trend.label"],
                                  "plan": plan}])
    assert any("A2" in e for e in validate_judgment(bad))
