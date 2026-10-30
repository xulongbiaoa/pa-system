"""凯利仓位测试：真实数据下它给什么、以及为什么不能拿它替换上限。"""

from gate.sizing import kelly_fraction, suggest, wilson_interval

# 真实样本（2026-10-30 实测）
GOLD = {"n": 2, "wins": 1, "b": 2.926 / 1.031}       # 金标准两张单
LOOSE = {"n": 31, "wins": 15, "b": 1.409 / 1.070}    # simple_loose 31 笔


def test_kelly_formula_known_values():
    # p=0.6, b=2 → 0.6 − 0.4/2 = 0.4
    assert abs(kelly_fraction(0.6, 2.0) - 0.4) < 1e-9
    assert kelly_fraction(0.4, 1.0) == 0.0  # 负优势不下注
    assert kelly_fraction(0.5, 0.0) == 0.0  # 盈亏比非法


def test_wilson_shrinks_hard_on_two_samples():
    lo, hi = wilson_interval(1, 2)
    assert lo < 0.12 and hi > 0.88  # n=2 时区间几乎覆盖全域


def test_gold_set_kelly_is_zero_but_naive_is_ruinous():
    """同一组数据：p̂ 版全凯利 32%，下界版是负的。这就是不能直接用的理由。"""
    s = suggest(GOLD["wins"], GOLD["n"], GOLD["b"])
    assert s["kelly_naive"] > 0.30            # 满仓级
    assert s["kelly_lo"] == 0.0               # 下界为负 → 0
    assert s["f_applied"] == 0.0 and s["binding"] == "evidence"


def test_loose_baseline_still_gated_out():
    """n=31 也不够：盈亏比只有 1.32，下界胜率撑不起正优势。"""
    s = suggest(LOOSE["wins"], LOOSE["n"], LOOSE["b"])
    assert s["n"] >= 30
    assert s["kelly_naive"] > 0.05            # p̂ 版 9%
    assert s["f_applied"] == 0.0              # 下界版仍是 0


def test_strong_evidence_gets_a_positive_size_under_the_cap():
    s = suggest(130, 200, 2.0)  # 130/200，p̂=0.65、b=2
    assert 0 < s["f_applied"] <= s["cap"]
    assert s["binding"] in ("kelly", "cap")


def test_cap_is_never_exceeded():
    s = suggest(450, 500, 5.0)  # 极端优势
    assert s["f_applied"] == s["cap"] and s["binding"] == "cap"


def test_size_is_monotone_in_sample_size():
    """同样的 p̂，样本越多下界越高 → 建议仓位单调不减（不许越赌越大靠猜）。"""
    prev = -1
    for n in (30, 60, 120, 240):
        f = suggest(int(n * 0.65), n, 2.0)["f_applied"]
        assert f >= prev
        prev = f
