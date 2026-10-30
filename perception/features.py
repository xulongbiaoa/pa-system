"""特征包组装：纯函数，输入 OHLC + 地图锚，输出 JSON 可序列化的 dict。

每个特征带置信标记（确定 / 边界 / 未定）；置信为「未定」的特征不得被
判断层用作放行依据。所有价位带来源 K 线索引。
"""

import json
import os

from .gaps import build_ledger, trimmed_avg_range
from .legs import legs_from_swings
from .swings import find_swings

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


def net_rr(entry, stop, target, side, fees):
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk <= 0:
        return None
    if side == "long":
        net_risk = risk + entry * fees["market_in"] + entry * fees["out"]
        net_reward = reward - entry * fees["market_in"] - entry * fees["out"]
    else:
        net_risk = risk + entry * fees["market_in"] + entry * fees["out"]
        net_reward = reward - entry * fees["market_in"] - entry * fees["out"]
    return round(net_reward / net_risk, 4) if net_risk > 0 else None


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
        seg = list(zip(closes, emas))[-20:]
        # emas 与 closes 的对齐：emas 从第 period-1 根起
        offset = len(closes) - len(emas)
        pairs = [(closes[i], emas[i - offset]) for i in range(offset, len(closes))][-20:]
        if pairs:
            ride = round(sum(1 for c, e in pairs if c > e) / len(pairs), 4)
    ledger = build_ledger(bars, map_anchors, cfg)
    pullback = None
    if legs:
        last = legs[-1]
        prev_same = next((l for l in reversed(legs[:-1]) if l["dir"] == last["dir"]), None)
        if prev_same and last["dir"] != prev_same["dir"]:
            pass
        # 回调 = 与前一条同向前进腿方向相反的最近腿
        adv = next((l for l in reversed(legs) if l["dir"] != last["dir"]), None)
        if last["height"] and adv and adv["height"]:
            pullback = {
                "depth_ratio": round(last["height"] / adv["height"], 4),
                "bars": last["to_bar"] - last["from_bar"],
                "dir_against": last["dir"],
            }
    return {
        "bars": len(bars),
        "swings": {"minor": minor, "major": major},
        "legs_major": legs,
        "trend": trend_state(major),
        "ema": {
            "period": cfg["ema_period"],
            "value": None if ema_now is None else round(ema_now, 6),
            "slope3": None if ema_now is None else round(ema_now - ema_prev, 6),
            "ride_ratio_20": ride,
            "confidence": "确定" if ema_now is not None else "未定",
        },
        "last_bar": bar_stats(bars[-1], bars[-2] if len(bars) > 1 else None),
        "seg_avg_range": round(trimmed_avg_range(bars), 6),
        "pullback": pullback,
        "gaps": {
            "open": [g for g in ledger if g["status"] == "open"],
            "closed": [g for g in ledger if g["status"] == "closed"],
            "confidence": "确定" if map_anchors else "未定",
        },
    }
