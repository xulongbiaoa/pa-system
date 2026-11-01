"""定版 v0.2 立账验收（2026-11-01 对齐线索C《缺口篇 上》）。

病根回顾：旧口径用影线 (5,5) 分形认摆动点——一段波段在相近价位
多顶几次就多确认几个点、每个被破各立一座账（实测三座相邻 35 点），
且没有「腿/起点」概念，千年历史的分形破位无差别入账（开放缺口 67 座）。
新口径：波段点 = 收盘折线拐点（一段波段一个点）；立账只在拐点与
强突破起点；收盘破锚即开账、碰回即销账。
"""
from battlefield.contracts import make_bar
from battlefield.reducers import Battlefield
from battlefield.repository import InMemoryRepository

TF_MS = 900_000


def bar(i, o, h, l, c):
    return make_bar("TEST", "15m", i * TF_MS, (i + 1) * TF_MS, o, h, l, c,
                    received_at=(i + 1) * TF_MS)


def bc(i, c, hi=2, lo=8):
    """以收盘定型的简易 bar：o=c、h=c+hi、l=c-lo（默认 range=10，尺度=10）。"""
    return bar(i, c, c + hi, c - lo, c)


def run(closes_or_bars):
    # 合成 bar 的腿幅只有 10-25 点（尺度 10），用 reversal=1.0 才认得出
    # 波段；生产口径 3.0 只改门槛倍数，认点/立账逻辑同一套
    from decimal import Decimal
    kernel = Battlefield("TEST", "15m", TF_MS, zigzag=True,
                         zigzag_reversal=Decimal("1.0"))
    repo = InMemoryRepository(kernel)
    bars = [b if not isinstance(b, (int, float)) else bc(i, b)
            for i, b in enumerate(closes_or_bars)]
    for b in bars:
        res = repo.commit_bar(b)
        assert res["status"] == "applied"
    return kernel


def zigzag_levels(kernel):
    return [lv for lv in kernel.state_dict()["levels"]
            if '"zigzag"' in str(lv) or lv["kind"] == "zigzag"]


def test_cluster_top_collapses_to_one_pivot():
    """波段顶部反复试探、影线乱刺：折线只认一个拐点。"""
    bars = [bc(0, 100), bc(1, 100), bc(2, 100),
            bc(3, 104), bc(4, 108),
            bc(5, 112, hi=8),    # 影线刺到 120
            bc(6, 111, hi=7),    # 118
            bc(7, 113, hi=8),    # 121
            bc(8, 112, hi=7),    # 119
            bc(9, 114, hi=8),    # 122 ← 收盘极值所在根
            bc(10, 108), bc(11, 102)]  # 回撤 12 >= 尺度 10 -> 确认拐点
    kernel = run(bars)
    highs = [lv for lv in zigzag_levels(kernel) if "-H-" in lv["level_key"]]
    assert len(highs) == 1
    assert highs[0]["lo"] == "122"          # 锚 = 拐点 K 的影线极值


def test_leg_break_books_pivot_gap_and_origin_gap():
    """腿破前一波段高点：波段点缺口与起点缺口同时开账（定版两种锚）。"""
    closes = [100, 105, 110, 115,      # 上行，收盘极值 115（锚 117）
              110, 105,                # 回撤 10 -> 确认 H
              100, 95, 90,             # 下行腿，收盘极值 90（锚 82）
              95, 100,                 # 回撤 10 -> 确认 L（本腿起点）
              105, 110, 115, 118]      # 上行腿收盘 118 > 117 破前高
    kernel = run(closes)
    gaps = list(kernel.gaps.values())
    assert len(gaps) == 2
    origin = [g for g in gaps if g.origin]
    pivot_gap = [g for g in gaps if not g.origin]
    assert len(origin) == 1 and origin[0].direction == "up"
    assert str(origin[0].anchor) == "82"        # 起点 K 背向极值（低点）
    assert len(pivot_gap) == 1 and pivot_gap[0].direction == "up"
    assert str(pivot_gap[0].anchor) == "117"    # 被破的波段高点
    assert all(g.status == "open" for g in gaps)


def test_touch_back_closes_gap():
    """价格碰回锚线 = 被套者解套，销账（起点缺口与波段点缺口同理）。"""
    closes = [100, 105, 110, 115, 110, 105, 100, 95, 90,
              95, 100, 105, 110, 115, 118]
    kernel = run(closes)
    assert len([g for g in kernel.gaps.values() if g.status == "open"]) == 2
    repo_bar = bar(len(closes), 110, 118, 80, 100)   # 一根砸回，碰到 117 与 82
    kernel.process_bar(repo_bar)
    assert all(g.status == "closed" for g in kernel.gaps.values())


def test_small_wiggles_book_nothing():
    """阈值以下的来回折腾：没有波段、没有拐点、不立账。"""
    closes = [100, 104] * 15
    kernel = run(closes)
    assert zigzag_levels(kernel) == []
    assert kernel.gaps == {}
