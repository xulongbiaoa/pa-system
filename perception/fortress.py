"""要塞带与尝试计数。

要塞带：把摆动锚价按「协商段收盘簇」聚成带——锚价彼此距离在容差内
（0.5 × 段均幅）视为同一带；带内有收盘簇时，上下边取收盘簇的极值
（钉得死）；只有一个孤锚、收盘簇不成宽度的，带退化为单线并标
far_undefined（远边未定，不得当作完整要塞用）。
尝试计数：某带被 K 线区间到达 = 测 1 次；收盘越过带的远边 = 穿 1 次
（穿越以收盘计，盘中刺穿只记到达——尝试计数 v2.1–v2.4 口径）。
"""

from .gaps import trimmed_avg_range


def build_fortress_bands(bars, swings, seg_avg=None):
    seg_avg = seg_avg or trimmed_avg_range(bars)
    tol = 0.5 * seg_avg if seg_avg else 0.0
    anchors = sorted(s["anchor"] for s in swings)
    clusters = []
    for a in anchors:
        if clusters and a - clusters[-1][-1] <= tol:
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
                "lo": round(lo, 6),
                "hi": round(hi, 6),
                "anchors": len(cl),
                "far_undefined": far_undefined,
                "tests": tests,
                "crosses": crosses,
                "decaying": tests >= 4,
                "trampled": crosses >= 3,
            }
        )
    return bands


def trend_age(bars, legs, emas, closes):
    """趋势年龄与高潮距离：当前方向腿序的根数/腿数、现价远离 EMA 的
    倍数（以最近回调腿全长为单位）。"""
    if not legs:
        return {"bars": 0, "legs": 0, "ema_distance_units": None, "confidence": "未定"}
    direction = legs[-1]["dir"]
    seq = []
    for leg in reversed(legs):
        if leg["dir"] == direction:
            seq.append(leg)
        else:
            break
    start_bar = seq[-1]["from_bar"] if seq else legs[-1]["from_bar"]
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
