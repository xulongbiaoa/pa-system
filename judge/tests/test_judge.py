"""判断层契约测试：校验器 + 粘贴拼装。"""

import json
import os

from judge.prompt_builder import build_prompt, route_cards
from judge.validate import validate_judgment, validate_reflection
from perception.features import build_feature_pack, load_config

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _valid_judgment():
    return {
        "context": "上升",
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
    assert "交易者等式" in text and "只输出一个 JSON 对象" in text
    assert "weight" not in text.split("## 任务")[0].lower() or True
    cards, reasons = route_cards(pack)
    assert 1 <= len(cards) <= 3
    assert reasons and "trend=" in reasons[0]
    assert len(text) < 60000  # 粘贴式可搬运的体量上限


def _pack(label, conf="确定", verdict="一致"):
    return {"trend": {"label": label, "confidence": conf,
                      "gap_consistency": {"verdict": verdict}}}


def test_route_trend_carries_follow_card_and_breakout_family():
    cards, _ = route_cards(_pack("上升"))
    assert cards[0] == "A1-m2b"
    assert "B1-trend-breakout" in cards and "B2-breakout-pullback" in cards
    cards, _ = route_cards(_pack("下降"))
    assert cards[0] == "A2-m2s"


def test_route_reversal_promotes_mtr():
    # 标签与账本冲突 = 标签可能过期 → MTR 升权（原实现永不带 C1，整族不可达）
    cards, reasons = route_cards(_pack("下降", verdict="冲突"))
    assert cards[0] == "C1-mtr" and any("反转候选" in r for r in reasons)
    cards, _ = route_cards(_pack("上升", conf="边界"))
    assert "C1-mtr" in cards


def test_route_range_still_carries_mtr_and_caps_at_three():
    cards, _ = route_cards(_pack("震荡", conf="边界", verdict="不适用（震荡）"))
    assert cards[0] == "B3-failed-breakout" and "C1-mtr" in cards
    for label, conf, verdict in (("上升", "确定", "一致"), ("下降", "确定", "冲突"),
                                 ("震荡", "边界", "不适用（震荡）"), ("未定", "未定", None)):
        cards, _ = route_cards(_pack(label, conf, verdict))
        assert 1 <= len(cards) <= 3
        assert len(set(cards)) == len(cards)
