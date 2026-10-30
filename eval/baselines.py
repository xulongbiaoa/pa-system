"""两条对照基线（与主系统同费用、同回放口径、同生命周期）。

1. 简单基线：趋势内（EMA 斜率 + 价在 EMA 同侧）回调做出第二信号（H2/L2
   尝试计数 ≥2）入场，止损在回调极值外加缓冲，固定 1.5R 目标。每段至多一笔。
2. 随机基线：同止损结构（1× 段均幅）与 1.5R 目标，入场根与方向由种子
   随机决定。每段一笔。

对齐口径（2026-10-30 修）：
- 入场窗收到**决策点**（bar 180）：原 WARM/END=30/170 是红线 4 旧截止的残留，
  比决策点早 10 根，等于把基线关在更小的窗里——对照不公平；
- 结局窗固定**决策点后/入场后 300 根**（生命周期口径），原来跑到段末（最长
  420 根），基线的单子比主系统多拿 120 根前向 K 线；
- 加漏斗计数：触发率低必须能拆开看是哪一环筛掉的，不许再用「口径过严或形态
  稀少」一句话糊过去。
"""

import hashlib

import numpy as np

from perception.features import ema_series, load_config
from perception.gaps import trimmed_avg_range
from perception.legs import count_entry_attempts
from replay import simulate_trade

WARM = 30
DECISION = 180   # 决策点：入场窗末端（与段协议、试点一致）
LIFECYCLE = 300  # 决策点后/入场后 300 根，到期按收盘出场
FUNNEL_KEYS = ("bars", "ema_side", "pullback_cross", "attempts", "signals")


def _ema_full(bars, period):
    closes = [b["c"] for b in bars]
    es = ema_series(closes, period)
    return [None] * (len(closes) - len(es)) + es


def _bump(funnel, key):
    if funnel is not None:
        funnel[key] = funnel.get(key, 0) + 1


def simple_baseline(seg, min_attempts=2, decision=DECISION, lifecycle=LIFECYCLE,
                    funnel=None, first_only=True):
    """返回该段的至多一笔交易。funnel 传 dict 则原地累加漏斗计数。

    first_only=False 时不提前返回，把整段扫完——漏斗统计必须扫全程，否则
    一旦在第一个信号处返回，后面每一环的分母都不一样，没法比较。
    """
    cfg = load_config()
    bars = seg["bars"]
    emas = _ema_full(bars, cfg["ema_period"])
    hits = []
    for i in range(WARM, min(decision, len(bars))):
        _bump(funnel, "bars")
        if emas[i] is None or emas[i - 5] is None:
            continue
        slope = emas[i] - emas[i - 5]
        c = bars[i]["c"]
        side = "long" if (slope > 0 and c > emas[i]) else "short" if (slope < 0 and c < emas[i]) else None
        if side is None:
            continue
        _bump(funnel, "ema_side")
        # 找当前回调起点：自 i 向前，价格在 EMA 另一侧的第一根
        j = i
        while j > WARM and (bars[j]["c"] - emas[j]) * (1 if side == "long" else -1) > 0:
            j -= 1
        if j == i:
            continue  # 没有回调
        sign = 1 if side == "long" else -1
        if not any((bars[k]["c"] - emas[k]) * sign < 0 for k in range(j, i + 1)):
            continue  # 价从未到 EMA 另一侧，不算回调
        _bump(funnel, "pullback_cross")
        attempts = count_entry_attempts(bars, j, i, side)
        if attempts < min_attempts:
            continue
        _bump(funnel, "attempts")
        seg_avg = trimmed_avg_range(bars[: i + 1])
        if side == "long":
            extreme = min(b["l"] for b in bars[j : i + 1])
            stop = extreme - 0.1 * seg_avg
            entry = c
            target = entry + 1.5 * (entry - stop)
        else:
            extreme = max(b["h"] for b in bars[j : i + 1])
            stop = extreme + 0.1 * seg_avg
            entry = c
            target = entry - 1.5 * (stop - entry)
        res = simulate_trade(bars[i + 1 : i + 1 + lifecycle], side, entry, stop, target)
        if res:
            _bump(funnel, "signals")
            res.update({"entry_bar": i, "side": side, "baseline": "simple",
                        "entry": entry, "stop": stop, "target": target,
                        "bars_after": min(lifecycle, len(bars) - i - 1),
                        "min_attempts": min_attempts})
            hits.append(res)
            if first_only:
                return hits
    return hits[:1] if first_only else hits


def random_baseline(seg, seed=42, decision=DECISION, lifecycle=LIFECYCLE):
    bars = seg["bars"]
    # 种子必须跨进程稳定（Python 的 hash() 带随机盐，会破坏回放可复现）
    seg_seed = int(hashlib.md5(seg["id"].encode()).hexdigest()[:8], 16) % 10000
    rng = np.random.default_rng(seed + seg_seed)
    i = int(rng.integers(WARM, min(decision, len(bars))))
    side = "long" if rng.random() < 0.5 else "short"
    seg_avg = trimmed_avg_range(bars[: i + 1])
    entry = bars[i]["c"]
    if side == "long":
        stop, target = entry - seg_avg, entry + 1.5 * seg_avg
    else:
        stop, target = entry + seg_avg, entry - 1.5 * seg_avg
    res = simulate_trade(bars[i + 1 : i + 1 + lifecycle], side, entry, stop, target)
    if res:
        res.update({"entry_bar": i, "side": side, "baseline": "random",
                    "entry": entry, "stop": stop, "target": target,
                    "bars_after": min(lifecycle, len(bars) - i - 1)})
        return [res]
    return []


def funnel_stats(segs, **kw):
    """漏斗：每一环还剩多少个 bar-实例 / 多少段出了信号（全段扫完再统计）。"""
    f = {}
    hit_segs = 0
    for seg in segs:
        trades = simple_baseline(seg, funnel=f, first_only=False, **kw)
        if trades:
            hit_segs += 1
    out = {k: f.get(k, 0) for k in FUNNEL_KEYS}
    out["segments_with_signal"] = hit_segs
    out["segments"] = len(segs)
    return out
