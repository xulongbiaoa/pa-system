"""特征包组装：纯函数，输入 OHLC + 地图锚，输出 JSON 可序列化的 dict。

每个特征带置信标记（确定 / 边界 / 未定）；置信为「未定」的特征不得被
判断层用作放行依据。所有价位带来源 K 线索引。
"""

import json
import os

from .fortress import build_fortress_bands, trend_age
from .gaps import build_ledger, trimmed_avg_range
from .legs import count_pullback_legs, legs_from_swings
from .precision import r6
from .swings import find_swings


def gap_consistency(score, open_gaps):
    """趋势标签与缺口账本的一致性：套空头 = 上行压力，套多头 = 下行压力。
    标签方向与压力方向相反 = 冲突（标签可能已过期，判断层须警觉）。"""
    ts = sum(1 for g in open_gaps if g["trapped"] == "short")
    tl = sum(1 for g in open_gaps if g["trapped"] == "long")
    if not open_gaps:
        verdict = "无敞开缺口"
    elif score == 0:
        verdict = "不适用（震荡）"
    else:
        pressure = 1 if ts > tl else -1 if tl > ts else 0
        if pressure == 0:
            verdict = "混合"
        elif (score > 0) == (pressure > 0):
            verdict = "一致"
        else:
            verdict = "冲突"
    return {"verdict": verdict, "trapped_short": ts, "trapped_long": tl}

_CFG = None


def load_config():
    global _CFG
    if _CFG is None:
        with open(os.path.join(os.path.dirname(__file__), "config.json")) as f:
            _CFG = json.load(f)
    return _CFG


def ema_series(closes, period):
    if len(closes) < period:
        return []
    k = 2.0 / (period + 1)
    out = [sum(closes[:period]) / period]
    for c in closes[period:]:
        out.append(out[-1] + k * (c - out[-1]))
    return out


def bar_stats(b, prev):
    rng = b["h"] - b["l"]
    body_pct = abs(b["c"] - b["o"]) / rng if rng > 0 else 0.0
    clv = ((b["c"] - b["l"]) - (b["h"] - b["c"])) / rng if rng > 0 else 0.0
    overlap = None
    if prev is not None:
        prng = prev["h"] - prev["l"]
        ov = min(b["h"], prev["h"]) - max(b["l"], prev["l"])
        overlap = max(0.0, ov) / prng if prng > 0 else None
    return {
        "body_pct": round(body_pct, 4),
        "clv": round(clv, 4),
        "overlap_prev": None if overlap is None else round(overlap, 4),
        "range": rng,
    }


def mm_project(base, leg_start, leg_end):
    """单腿 MM：以 leg 的高度从 base 投影。"""
    return base + (leg_end - leg_start)


def net_rr(entry, stop, target, side, fees, limit_in=False):
    """净 RR 的**唯一实现**（裁决层 H1 与特征包都用它，防两套公式漂移）。

    亏损侧风险 = 价格风险 + 入场费 + 出场费；盈利侧 = 毛幅 − 入场费 −
    出场费（出场费按**目标价**计，原实现按入场价计，差 ≤0.05%×幅度）。
    限价入场费率不同（fees['limit_in']）。
    原实现长/空两分支同体且重复计了一次入场费，已删。
    """
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    fin = fees["limit_in"] if limit_in else fees["market_in"]
    cost = entry * fin + target * fees["out"]
    denom = risk + entry * fin + entry * fees["out"]
    return round((abs(target - entry) - cost) / denom, 6) if denom > 0 else None


def trend_state(major_swings):
    """由大级别摆动序列给趋势分：HH+HL 计多分，LH+LL 计空分。"""
    if len(major_swings) < 4:
        return {"label": "未定", "score": 0, "confidence": "未定"}
    hs = [s["anchor"] for s in major_swings if s["kind"] == "H"][-2:]
    ls = [s["anchor"] for s in major_swings if s["kind"] == "L"][-2:]
    if len(hs) < 2 or len(ls) < 2:
        return {"label": "未定", "score": 0, "confidence": "未定"}
    score = 0
    score += 1 if hs[1] > hs[0] else -1
    score += 1 if ls[1] > ls[0] else -1
    if score == 2:
        return {"label": "上升", "score": 2, "confidence": "确定"}
    if score == -2:
        return {"label": "下降", "score": -2, "confidence": "确定"}
    return {"label": "震荡", "score": score, "confidence": "边界"}


def build_feature_pack(bars, map_anchors=None, cfg=None):
    cfg = cfg or load_config()
    map_anchors = map_anchors or []
    closes = [b["c"] for b in bars]
    minor = find_swings(bars, cfg["swing_window_minor"])
    major = find_swings(bars, cfg["swing_window_major"])
    legs = legs_from_swings(major)
    emas = ema_series(closes, cfg["ema_period"])
    ema_now = emas[-1] if emas else None
    ema_prev = emas[-4] if len(emas) >= 4 else ema_now
    ride = None
    if emas:
        # emas 与 closes 的对齐：emas 从第 period-1 根起
        offset = len(closes) - len(emas)
        pairs = [(closes[i], emas[i - offset]) for i in range(offset, len(closes))][-20:]
        if pairs:
            ride = round(sum(1 for c, e in pairs if c > e) / len(pairs), 4)
    ledger = build_ledger(bars, map_anchors, cfg)
    trend = trend_state(major)
    open_gaps = [g for g in ledger if g["status"] == "open"]
    trend["window"] = len(bars)
    trend["gap_consistency"] = gap_consistency(trend["score"], open_gaps)
    # 回调口径（2026-10-30 按外部复核意见修正）：参照方向 = 趋势标签方向
    # （±2 时），标签不定才退回最后一条腿的方向。dir_against = 最近一条
    # 逆势腿的方向；depth_ratio ≥ 1 = 回吐已超过被回吐腿，标 expired。
    pullback = None
    if legs:
        if trend["score"] >= 2:
            ref = "up"
        elif trend["score"] <= -2:
            ref = "down"
        else:
            ref = legs[-1]["dir"]
        pb = next((l for l in reversed(legs) if l["dir"] != ref), None)
        adv = None
        if pb:
            adv = next(
                (l for l in reversed(legs)
                 if l["dir"] == ref and l["to_bar"] <= pb["from_bar"]),
                None,
            )
        if pb and adv and adv["height"]:
            ratio = pb["height"] / adv["height"]
            # 腿数（2026-10-30 补）：A1/A2 卡要求「回踩已走出第二腿（腿数由
            # 特征包计）」，但包里一直没有这个字段——判断层只能靠感觉数。
            # 这里按 minor 摆动的结构计，不看根数（卡片原话）。
            sep = "H" if pb["dir"] == "down" else "L"
            n_legs = count_pullback_legs(minor, pb["from_bar"], pb["to_bar"], sep)
            pullback = {
                "depth_ratio": round(ratio, 4),
                "bars": pb["to_bar"] - pb["from_bar"],
                "dir_against": pb["dir"],
                "expired": ratio >= 1.0,
                "legs": n_legs,
                "two_legs": n_legs >= 2,
            }
    return {
        "bars": len(bars),
        "swings": {"minor": minor, "major": major},
        "legs_major": legs,
        "trend": trend,
        "ema": {
            "period": cfg["ema_period"],
            "value": None if ema_now is None else r6(ema_now),
            "slope3": None if ema_now is None else r6(ema_now - ema_prev),
            "ride_ratio_20": ride,
            "confidence": "确定" if ema_now is not None else "未定",
        },
        "last_bar": bar_stats(bars[-1], bars[-2] if len(bars) > 1 else None),
        "seg_avg_range": r6(trimmed_avg_range(bars)),
        "pullback": pullback,
        "gaps": {
            "open": [g for g in ledger if g["status"] == "open"],
            "closed": [g for g in ledger if g["status"] == "closed"],
            "confidence": "确定" if map_anchors else "未定",
        },
        "fortress": {
            "bands": build_fortress_bands(bars, minor + major),
            "confidence": "确定" if (minor or major) else "未定",
        },
        "trend_age": trend_age(bars, legs, emas, closes),
    }
