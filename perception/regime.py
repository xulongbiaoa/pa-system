"""语境（regime）特征原型：把阿布的趋势/通道/区间判据落成可计算特征。

出处（原册讲义，knowledge/brooks-cases）：
- v1 s5：市场要么趋势要么区间；通道是趋势较弱的部分；通道演变为区间。
- v1 s10：趋势 K = 小影线、单根成趋势；区间 K = 十字、显著影线、小实体、
  单根即区间（重叠）。
- v10 s30/31：区间内压力转移看连续同向 K、实体变大、收在极值、缺口、
  HH/LL 开始出现。

现行 trend_state 只看最后两对 major 摆动（4 个点定 180 根的语境），
官网盲测两天全错。本模块补上 K 线质量类证据：重叠、效率、EMA 穿越、
突破失败率、缺口回补率。阈值为 v0 暂定（未拟合），验收走
knowledge/specs/context-regime.md 的考场协议。
"""

from .features import build_feature_pack, ema_series


def _overlap(bars):
    vals = []
    for i in range(1, len(bars)):
        p, b = bars[i - 1], bars[i]
        lo, hi = max(p["l"], b["l"]), min(p["h"], b["h"])
        rng = b["h"] - b["l"]
        vals.append(max(0.0, hi - lo) / rng if rng > 0 else 0.0)
    return sum(vals) / len(vals) if vals else 0.0


def _efficiency(bars):
    path = sum(abs(bars[i]["c"] - bars[i - 1]["c"]) for i in range(1, len(bars)))
    net = abs(bars[-1]["c"] - bars[0]["c"])
    return net / path if path > 0 else 0.0


def _ema_behavior(bars, period=20):
    closes = [b["c"] for b in bars]
    es = ema_series(closes, period)
    if not es:
        return {"crosses": 0, "drift_units": 0.0}
    full = [None] * (len(closes) - len(es)) + es
    crosses, prev = 0, None
    for c, e in zip(closes, full):
        if e is None:
            continue
        side = 1 if c >= e else -1
        if prev is not None and side != prev:
            crosses += 1
        prev = side
    rng = sum(b["h"] - b["l"] for b in bars) / len(bars)
    drift = (es[-1] - es[0]) / rng if rng > 0 else 0.0
    return {"crosses": crosses, "drift_units": drift}


def _breakout_failures(bars, look=20, hold=3):
    """推过前 look 根极值后 hold 根内收盘回到极值内侧 = 一次失败。"""
    pushes = fails = 0
    for i in range(look, len(bars)):
        prior_hi = max(b["h"] for b in bars[i - look:i])
        prior_lo = min(b["l"] for b in bars[i - look:i])
        for side, broke in (("up", bars[i]["h"] > prior_hi),
                            ("dn", bars[i]["l"] < prior_lo)):
            if not broke:
                continue
            pushes += 1
            level = prior_hi if side == "up" else prior_lo
            window = bars[i:i + hold + 1]
            back = any(b["c"] < level for b in window) if side == "up" \
                else any(b["c"] > level for b in window)
            if back:
                fails += 1
    return {"pushes": pushes, "fails": fails,
            "fail_ratio": (fails / pushes) if pushes else None}


def _body_stats(bars):
    bodies = []
    for b in bars:
        rng = b["h"] - b["l"]
        bodies.append(abs(b["c"] - b["o"]) / rng if rng > 0 else 0.0)
    doji = sum(1 for x in bodies if x < 0.3) / len(bodies) if bodies else 0.0
    strong = sum(1 for x in bodies if x >= 0.6) / len(bodies) if bodies else 0.0
    return {"doji_share": doji, "strong_share": strong}


def regime_features(bars, cfg=None):
    pack = build_feature_pack(bars, [], cfg)
    opened = len(pack["gaps"]["open"]) + len(pack["gaps"]["closed"])
    return {
        "overlap_mean": round(_overlap(bars), 4),
        "efficiency": round(_efficiency(bars), 4),
        "ema": _ema_behavior(bars),
        "breakouts": _breakout_failures(bars),
        "gaps": {"open": len(pack["gaps"]["open"]),
                 "opened": opened,
                 "refill_ratio": (len(pack["gaps"]["closed"]) / opened) if opened else None},
        "bodies": _body_stats(bars),
        "swing_score": pack["trend"]["score"],
        "swing_label": pack["trend"]["label"],
    }


def classify_regime(bars, cfg=None):
    """v0 规则（暂定阈值，未拟合；先看证据表再下判）：
    震荡 = 高重叠 + 低效率（阿布：区间 K 是重叠与十字）；
    趋势 = 摆动同向 + 效率够 + EMA 少穿越；
    通道 = 摆动同向但重叠/穿越偏高（趋势的弱形态，映射到方向）。"""
    f = regime_features(bars, cfg)
    score = f["swing_score"]
    direction = "上升" if score > 0 else "下降" if score < 0 else None
    if f["overlap_mean"] >= 0.55 and f["efficiency"] <= 0.25:
        regime = "震荡"
    elif direction and f["efficiency"] >= 0.30 and f["ema"]["crosses"] <= max(3, len(bars) // 30):
        regime = "趋势"
    elif direction:
        regime = "通道"
    else:
        regime = "震荡"
    context = f["swing_label"] if regime == "趋势" else \
        (direction if regime == "通道" else "震荡")
    if regime in ("趋势", "通道"):
        context = direction
    return {"regime": regime, "context": context, "features": f}
