"""金标准打分器测试：用合成判断验对账逻辑，不依赖任何 LLM。

要点：一致性轴与盈亏轴分开记；未判段不算失败；格式错单独计。
"""

import json
import os
import shutil
import tempfile

import pytest

# 2026-10-30：knowledge/gold 已按用户指令整目录删除（commit b093e18）、
# 由 gold-book 取代，本套件的夹具随之退役；打分逻辑保留待 gold-book
# 判断跑批时复用，故整模块 skip 而非删除。
pytest.skip("旧 gold 已删除（b093e18），夹具退役", allow_module_level=True)

from gold_run import score

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _j_candidate(setup, side, entry, stop, targets):
    return {
        "context": "震荡", "primary": "H1",
        "hypotheses": [{"id": "H1", "statement": "下降趋势内逆势突破失败",
                        "holds_if": "收回位内且不再新高", "void_if": "收盘站回上沿",
                        "takeover_if": "三根内重新站上则转顺势多", "menu": ["B3"]}],
        "candidates": [{
            "setup": setup, "side": side, "qualified": True, "reason": "翻面成立",
            "feature_refs": ["trend.label"],
            "plan": {"entry": entry, "stop": stop, "targets": targets,
                     "void_if": "收盘站回上沿", "risk_frac": 0.01},
        }],
        "no_trade_reason": None,
        "uncertainty": [],
    }


def _j_no_trade(reason):
    return {
        "context": "震荡", "primary": "H1",
        "hypotheses": [{"id": "H1", "statement": "无方向优势",
                        "holds_if": "继续区间往返", "void_if": "收盘破位",
                        "takeover_if": "破位带跟进则交突破面", "menu": []}],
        "candidates": [], "no_trade_reason": reason, "uncertainty": [],
    }


def _write(d, seg, obj):
    with open(os.path.join(d, seg + ".json"), "w") as f:
        json.dump(obj, f, ensure_ascii=False)


def test_score_rewards_matching_judgment_and_separates_axes():
    d = tempfile.mkdtemp(dir=os.path.dirname(__file__))
    try:
        # ds23 冻结为 candidate B3 short：照抄其计划，应一致性满分、R 复现 −1.03
        _write(d, "ds23", _j_candidate("B3", "short", 11.43, 11.80, [10.43, 10.29]))
        # ds16 冻结为 no_trade/无命中：理由一致
        _write(d, "ds16", _j_no_trade("无命中"))
        rep = score(judgments_dir=d)
        assert rep["n_judged"] == 2 and rep["format_fail"] == 0
        assert rep["verdict_agree"] == 2
        assert rep["reason_agree_rate"] == 1.0
        assert rep["setup_agree"] == 1 and rep["side_agree"] == 1
        assert rep["gate_reject"] == 0
        assert len(rep["trades"]) == 1
        assert abs(rep["trades"][0]["r"] - (-1.0314)) < 1e-3
    finally:
        shutil.rmtree(d)


def test_score_flags_mismatch_without_touching_pnl_axis():
    d = tempfile.mkdtemp(dir=os.path.dirname(__file__))
    try:
        # ds16 冻结为空仓，AI 硬凑一张候选单：一致性记错，盈亏轴照样单独算
        _write(d, "ds16", _j_candidate("A2", "short", 0.134, 0.137, [0.128]))
        rep = score(judgments_dir=d)
        assert rep["verdict_agree"] == 0
        assert rep["mismatches"] and rep["mismatches"][0]["kind"] == "verdict"
        assert "pnl" not in rep["mismatches"][0]  # 两轴不许互相折算
    finally:
        shutil.rmtree(d)


def test_unjudged_segments_are_not_failures():
    d = tempfile.mkdtemp(dir=os.path.dirname(__file__))
    try:
        _write(d, "ds23", _j_candidate("B3", "short", 11.43, 11.80, [10.43, 10.29]))
        rep = score(judgments_dir=d)
        assert rep["n_gold"] == 30 and rep["n_judged"] == 1
        assert rep["verdict_agree_rate"] == 1.0
    finally:
        shutil.rmtree(d)


def test_format_failure_counted_separately():
    d = tempfile.mkdtemp(dir=os.path.dirname(__file__))
    try:
        _write(d, "ds23", {"context": "震荡", "primary": "H1", "hypotheses": [], "candidates": [],
                           "uncertainty": []})
        rep = score(judgments_dir=d)
        assert rep["format_fail"] == 1 and rep["n_judged"] == 0
        assert rep["verdict_agree_rate"] is None
    finally:
        shutil.rmtree(d)
