"""R1 回归钉：B3 收回认定三问必须同时存在于单点提示与到达提示。

解剖依据（recognition-anatomy-2026-10-31）：X16/X23 的误放机制
是「收回根与决策根脱钩」；三问自检是提示层对策，删任何一处都算
回归。本测试只钉条款存在与关键措辞，不钉全文。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from judge.campaign_prompt import ARRIVAL_TASK  # noqa: E402

KEY_PHRASES = ("收回认定三问", "从无任何一根收盘在位外", "B3-N3",
               "收回根也是入场决策根")


def test_arrival_task_has_reclaim_clause():
    for ph in KEY_PHRASES:
        assert ph in ARRIVAL_TASK, ph


def test_prompt_builder_has_reclaim_clause():
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "prompt_builder.py")).read()
    for ph in KEY_PHRASES:
        assert ph in src, ph
