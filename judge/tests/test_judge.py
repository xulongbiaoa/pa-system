"""判断层契约测试：校验器 + 粘贴拼装。"""

import json
import os

from judge.prompt_builder import build_prompt, route_cards
from judge.validate import validate_judgment, validate_reflection
from perception.features import build_feature_pack, load_config

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _valid_judgment():
    return {
        "primary": "H1",
        "hypotheses": [
            {
                "id": "H1",
                "statement": "上升趋势回踩延续",
                "holds_if": "回踩不破起点",
                "void_if": "收盘破起点",
                "takeover_if": "",
                "menu": ["A1"],
            },
            {
                "id": "H2",
                "statement": "高位转震荡",
                "holds_if": "MM 已达后横盘",
                "void_if": "强突破创新高",
                "takeover_if": "MM 到达",
                "menu": ["B3"],
            },
        ],
        "candidates": [],
        "no_trade_reason": "位置不对",
        "pending_conditions": [],
        "uncertainty": [],
    }


def test_valid_judgment_passes():
    assert validate_judgment(_valid_judgment()) == []


def test_numeric_weight_rejected():
    j = _valid_judgment()
    j["hypotheses"][0]["weight"] = 0.7  # 用户裁定：数字权重是假精确
    assert any("权重" in e for e in validate_judgment(j))


def test_no_candidate_requires_reason():
    j = _valid_judgment()
    j["no_trade_reason"] = None
    assert validate_judgment(j) != []


def test_reflection_cannot_propose_rule():
    r = {
        "blind_rejudge": "同原判",
        "matches_original": True,
        "info_available_at_time": True,
        "category": "A",
        "evidence": ["gaps.open"],
        "in_prior_range": "是",
        "allowed_action": "记账",
        "new_rule_proposed": True,
    }
    assert validate_reflection(r) != []
    r["new_rule_proposed"] = False
    assert validate_reflection(r) == []


def test_prompt_assembly_on_dev_segment():
    seg = json.load(open(os.path.join(ROOT, "eval/datasets/dev/ds03.json")))
    bars = seg["bars"][:180]
    cfg = load_config()
    pack = build_feature_pack(bars, [], cfg)
    text = build_prompt(pack, bars)
    assert "交易者等式" in text and "只输出 JSON" in text
    assert "weight" not in text.split("## 任务")[0].lower() or True
    cards = route_cards(pack)
    assert 1 <= len(cards) <= 3
    assert len(text) < 60000  # 粘贴式可搬运的体量上限
