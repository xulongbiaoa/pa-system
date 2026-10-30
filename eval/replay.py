"""回放与统计：以 R 为单位；同根内止损优先（trainer 口径）。

simulate_trade 在入场后的 K 线序列上逐根走：先判止损、再判目标（第一
目标），都没碰到则窗口末收盘出场。费用按入场市价 0.05% + 出场 0.05%
计入净 R；fee_mult 用于费用加倍敏感性。
"""

import numpy as np

FEE = 0.0005


def simulate_trade(bars_after, side, entry, stop, target, fee_mult=1.0):
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    exit_price = bars_after[-1]["c"] if bars_after else entry
    exit_bar = len(bars_after) - 1
    for i, b in enumerate(bars_after):
        if side == "long":
            if b["l"] <= stop:
                exit_price, exit_bar = stop, i
                break
            if b["h"] >= target:
                exit_price, exit_bar = target, i
                break
        else:
            if b["h"] >= stop:
                exit_price, exit_bar = stop, i
                break
            if b["l"] <= target:
                exit_price, exit_bar = target, i
                break
    gross = (exit_price - entry) if side == "long" else (entry - exit_price)
    fees = (entry + exit_price) * FEE * fee_mult
    return {
        "r": (gross - fees) / risk,
        "exit_price": exit_price,
        "exit_bar": exit_bar,
        "win": gross - fees > 0,
    }


def summarize(trades, seed=42):
    rs = np.array([t["r"] for t in trades], dtype=float)
    if len(rs) == 0:
        return {"n": 0}
    wins = [t for t in trades if t["win"]]
    max_streak = streak = 0
    for t in trades:
        streak = 0 if t["win"] else streak + 1
        max_streak = max(max_streak, streak)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(2000):
        sample = rng.choice(rs, size=len(rs), replace=True)
        boots.append(sample.mean())
    lo, hi = np.percentile(boots, [2.5, 97.5])
    enough = len(rs) >= 30  # 统计底线：样本不足不许下「已证明」结论
    proven = bool(enough and lo > 0)
    if not enough:
        note = f"样本不足（n={len(rs)}<30），不下结论"
    elif lo > 0:
        note = ""
    else:
        note = "尚未证明优势（CI 包含或低于 0）"
    return {
        "n": int(len(rs)),
        "win_rate": round(len(wins) / len(rs), 4),
        "mean_r": round(float(rs.mean()), 4),
        "median_r": round(float(np.median(rs)), 4),
        "mean_r_ci95": [round(float(lo), 4), round(float(hi), 4)],
        "max_consec_losses": int(max_streak),
        "proven_edge": proven,
        "note": note,
    }
