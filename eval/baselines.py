"""两条对照基线（与主系统同费用、同回放口径）：

1. 简单基线：趋势内（EMA 斜率 + 价在 EMA 同侧）回调做出第二信号（H2/L2
   尝试计数 ≥2 且收盘越过前根极值）入场，止损在回调极值外加缓冲，固定
   1.5R 目标。每段至多一笔。
2. 随机基线：同止损结构（1× 段均幅）与 1.5R 目标，入场根与方向由种子
   随机决定。每段一笔。
"""

import numpy as np

from perception.features import ema_series, load_config
from perception.gaps import trimmed_avg_range
from perception.legs import count_entry_attempts
from replay import simulate_trade

WARM, END = 30, 170  # 决策窗（与段协议一致，末尾留 10 根截止）


def _ema_full(bars, period):
    closes = [b["c"] for b in bars]
    es = ema_series(closes, period)
    return [None] * (len(closes) - len(es)) + es


def simple_baseline(seg):
    cfg = load_config()
    bars = seg["bars"]
    emas = _ema_full(bars, cfg["ema_period"])
    for i in range(WARM, END):
        if emas[i] is None or emas[i - 5] is None:
            continue
        slope = emas[i] - emas[i - 5]
        c = bars[i]["c"]
        side = "long" if (slope > 0 and c > emas[i]) else "short" if (slope < 0 and c < emas[i]) else None
        if side is None:
            continue
        # 找当前回调起点：自 i 向前，价格在 EMA 另一侧的第一根
        j = i
        while j > WARM and (bars[j]["c"] - emas[j]) * (1 if side == "long" else -1) > 0:
            j -= 1
        if j == i:
            continue  # 没有回调
        sign = 1 if side == "long" else -1
        if not any((bars[k]["c"] - emas[k]) * sign < 0 for k in range(j, i + 1)):
            continue  # 价从未到 EMA 另一侧，不算回调
        attempts = count_entry_attempts(bars, j, i, side)
        if attempts < 2:
            continue
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
        res = simulate_trade(bars[i + 1 :], side, entry, stop, target)
        if res:
            res.update({"entry_bar": i, "side": side, "baseline": "simple",
                        "entry": entry, "stop": stop, "target": target})
            return [res]
    return []


def random_baseline(seg, seed=42):
    bars = seg["bars"]
    rng = np.random.default_rng(seed + abs(hash(seg["id"])) % 10000)
    i = int(rng.integers(WARM, END))
    side = "long" if rng.random() < 0.5 else "short"
    seg_avg = trimmed_avg_range(bars[: i + 1])
    entry = bars[i]["c"]
    if side == "long":
        stop, target = entry - seg_avg, entry + 1.5 * seg_avg
    else:
        stop, target = entry + seg_avg, entry - 1.5 * seg_avg
    res = simulate_trade(bars[i + 1 :], side, entry, stop, target)
    if res:
        res.update({"entry_bar": i, "side": side, "baseline": "random",
                    "entry": entry, "stop": stop, "target": target})
        return [res]
    return []
