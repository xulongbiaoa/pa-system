"""原册讲义召回测试：标签推导、排序确定性、提示词装配。"""
from judge.brooks_recall import query_tags, recall_cases
from judge.prompt_builder import build_prompt

PACK_TREND = {"trend": {"label": "上升", "confidence": "确定",
                        "gap_consistency": {"verdict": "一致"}}}
PACK_RANGE = {"trend": {"label": "震荡", "confidence": "边界",
                        "gap_consistency": {"verdict": "冲突"}}}


def test_query_tags_from_cards_and_context():
    tags = query_tags(PACK_TREND, ["A1-m2b", "B1-trend-breakout"])
    assert "H2/L2" in tags and "突破" in tags and "通道" in tags
    tags2 = query_tags(PACK_RANGE, ["B3-failed-breakout", "C1-mtr"])
    assert "区间" in tags2 and "反转" in tags2 and "MTR" in tags2


def test_recall_returns_provenanced_pages():
    cases = recall_cases(PACK_TREND, ["A1-m2b", "B1-trend-breakout"], k=2)
    assert 1 <= len(cases) <= 2
    for c in cases:
        assert c["book"] and c["slide"] and len(c["text"]) <= 520
        assert c["tags"]  # 每页带标签，判断层可判相关性


def test_recall_deterministic():
    a = recall_cases(PACK_RANGE, ["B3-failed-breakout", "C1-mtr"])
    b = recall_cases(PACK_RANGE, ["B3-failed-breakout", "C1-mtr"])
    assert [(x["book"], x["slide"]) for x in a] == \
           [(x["book"], x["slide"]) for x in b]


def test_prompt_contains_brooks_section():
    pack = {"trend": {"label": "上升", "confidence": "确定",
                      "gap_consistency": {"verdict": "一致"}}}
    bars = [{"o": 1, "h": 1, "l": 1, "c": 1, "t": i} for i in range(5)]
    prompt = build_prompt(pack, bars)
    assert "阿布原册讲义" in prompt and "slide" in prompt
