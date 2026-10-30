"""要塞带与尝试计数。

要塞带：把摆动锚价按「协商段收盘簇」聚成带——锚价彼此距离在容差内
（0.5 × 段均幅）视为同一带；带内有收盘簇时，上下边取收盘簇的极值
（钉得死）；只有一个孤锚、收盘簇不成宽度的，带退化为单线并标
far_undefined（远边未定，不得当作完整要塞用）。
尝试计数：某带被 K 线区间到达 = 测 1 次；收盘越过带的远边 = 穿 1 次
（穿越以收盘计，盘中刺穿只记到达——尝试计数 v2.1–v2.4 口径）。

粒度修复（2026-10-31 审计处置）：旧聚类是单链 chaining——锚价以
≤tol 的台阶一路相连就能并成跨度任意大的「巨带」。140 段语料实测
带宽/段均幅 p90=2.26、p99=4.81、>3× 占 5.8%：一条宽 3 倍均幅的
「带」是区域不是价位，污染 R2 落点判定、事件采样与 flags 相关性。
修法：簇跨度上限 = 2 × 段均幅（4×tol），新锚加入会超限即另起一簇；
局部密度分组不变，只剪链式并带。修后同语料复测见 changelog。

衰减口径（同日再修）：decaying 旧定义 tests≥4 在语料里 140/140 段
都有带命中、规范计划触发率 88%——「被测 ≥4 次」是要塞的证据而非
衰减。改 tests≥4 且 crosses≥1 后复测仍 81%，crosses≥2 仍 63%：
180 根尺度上计数聚合表达不了「排斥力在变弱」（那是最近几次测试的
反应问题，需要逐测反应记录）。故 decaying 只保留为**描述字段**
（decaying = tests≥4 且 crosses≥1），gate 自 2026-10-31 起不再据它
减半（S3 删除）；trampled（crosses≥3）是用户体系里有定义的踩踏
状态，S2 继续消费。逐测反应衰减检测器要另立项，不许拿计数凑。
"""

from .gaps import trimmed_avg_range
from .precision import r6

MAX_BAND_SPAN = 2.0  # 簇跨度上限（× 段均幅）


def build_fortress_bands(bars, swings, seg_avg=None):
    seg_avg = seg_avg or trimmed_avg_range(bars)
    tol = 0.5 * seg_avg if seg_avg else 0.0
    max_span = MAX_BAND_SPAN * seg_avg if seg_avg else 0.0
    anchors = sorted(s["anchor"] for s in swings)
    clusters = []
    for a in anchors:
        if (clusters and a - clusters[-1][-1] <= tol
                and a - clusters[-1][0] <= max_span):
            clusters[-1].append(a)
        else:
            clusters.append([a])
    bands = []
    for cl in clusters:
        lo0, hi0 = min(cl), max(cl)
        closes_in = [b["c"] for b in bars if lo0 - tol <= b["c"] <= hi0 + tol]
        if len(closes_in) >= 3 and max(closes_in) > min(closes_in):
            lo, hi = min(closes_in), max(closes_in)
            far_undefined = False
        else:
            lo = hi = cl[len(cl) // 2]
            far_undefined = True
        tests = crosses = 0
        for b in bars:
            if b["l"] <= hi and b["h"] >= lo:
                tests += 1
        # 穿越：收盘从带的一侧到另一侧（相邻两根收盘分居带上下）
        prev = None
        for b in bars:
            side = 1 if b["c"] > hi else -1 if b["c"] < lo else 0
            if prev in (1, -1) and side in (1, -1) and side != prev:
                crosses += 1
            if side != 0:
                prev = side
        bands.append(
            {
                "lo": r6(lo),
                "hi": r6(hi),
                "anchors": len(cl),
                "far_undefined": far_undefined,
                "tests": tests,
                "crosses": crosses,
                "decaying": tests >= 4 and crosses >= 1,
                "trampled": crosses >= 3,
            }
        )
    return bands


def trend_age(bars, legs, emas, closes, direction=None):
    """趋势年龄与高潮距离：推腿数、现价远离 EMA 的倍数（以最近回调腿
    全长为单位）。

    2026-10-31 审计修复：旧实现数「尾部连续同向腿」，而腿序列由摆动点
    交替生成、同向腿不可能相邻，该字段在 dev 31/31 段恒为 1（结构性
    退化）。新口径 = 当前趋势的**推腿**数：direction 缺省取最后一条腿
    方向（features 传入趋势标签方向）；同向推腿须逐腿推进极值（up 看
    end 创新高、down 看 end 创新低）才累计，不推进的推腿使计数重置为
    1（自它起算新序列）；回调腿不计、不重置。bars = 自当前计数序列
    第一条推腿起点以来的根数。
    """
    if not legs:
        return {"bars": 0, "legs": 0, "ema_distance_units": None, "confidence": "未定"}
    direction = direction or legs[-1]["dir"]
    seq, best_end = [], None
    for leg in legs:
        if leg["dir"] != direction:
            continue
        e = leg["end"]
        if best_end is None or (e > best_end if direction == "up" else e < best_end):
            seq.append(leg)
            best_end = e
        else:
            seq, best_end = [leg], e
    start_bar = seq[0]["from_bar"] if seq else legs[-1]["from_bar"]
    pullbacks = [l for l in legs if l["dir"] != direction]
    unit = pullbacks[-1]["height"] if pullbacks else None
    dist = None
    if emas and unit:
        dist = round(abs(closes[-1] - emas[-1]) / unit, 4)
    return {
        "bars": len(bars) - 1 - start_bar,
        "legs": len(seq),
        "ema_distance_units": dist,
        "confidence": "确定" if unit else "边界",
    }
