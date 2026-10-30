"""回放与统计：以 R 为单位；同根内止损优先（trainer 口径）。

simulate_trade 在入场后的 K 线序列上逐根走：先判止损、再判目标（第一
目标），都没碰到则窗口末收盘出场。

费用口径（2026-10-30 复核后统一）：一律读 perception/config.json 的 fees，
入场按该下单方式的费率（市价 0.05% / 限价 0.02%）、出场 0.05%。原先本模块
硬编码 FEE=0.0005，与 H1 用的 config 费率是两套账——限价单在裁决层按 0.02%
承诺 RR、在这里按 0.05% 结算，承诺与结算不同口径。

统计部分只用标准库（bootstrap + 线性插值分位），不再依赖 numpy：评估链路
原先因 numpy 缺失整体跑不起来，而它只需要一个均值置信区间。
"""

import random

from perception.features import load_config

_FEES = None


def _fees(fees=None):
    """费用配置：显式传入优先，否则读 config（缓存一次）。"""
    global _FEES
    if fees is not None:
        return fees
    if _FEES is None:
        _FEES = load_config()["fees"]
    return _FEES


def void_hit(void, close):
    """前提失效判定（结构化 void 的唯一原语）：收盘越过 level 即失效。

    void = {"level": float, "side": "above"|"below"}：side=above 表示
    收盘 > level 失效（空单前提被收回上方等），side=below 表示
    收盘 < level 失效（多单收盘破起点/回落突破位内侧等）。
    判据只看收盘——与全系统「穿越以收盘计」的口径一致。
    """
    if not void:
        return False
    lvl = void.get("level")
    if lvl is None:
        return False
    return close > lvl if void.get("side") == "above" else close < lvl


def simulate_trade(bars_after, side, entry, stop, target, fee_mult=1.0,
                   fees=None, entry_fee=None, void=None):
    fees = _fees(fees)
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    exit_price = bars_after[-1]["c"] if bars_after else entry
    exit_bar = len(bars_after) - 1
    exit_reason = "window_end"
    for i, b in enumerate(bars_after):
        if side == "long":
            if b["l"] <= stop:
                exit_price, exit_bar, exit_reason = stop, i, "stop"
                break
            if b["h"] >= target:
                exit_price, exit_bar, exit_reason = target, i, "target"
                break
        else:
            if b["h"] >= stop:
                exit_price, exit_bar, exit_reason = stop, i, "stop"
                break
            if b["l"] <= target:
                exit_price, exit_bar, exit_reason = target, i, "target"
                break
        # 前提失效是收盘判定：同根内止损/目标（盘中先发生）优先，
        # 都没触发才在收盘判 void，失效即按收盘价出场（市价出口径计费）。
        if void_hit(void, b["c"]):
            exit_price, exit_bar, exit_reason = b["c"], i, "void"
            break
    gross = (exit_price - entry) if side == "long" else (entry - exit_price)
    fin = fees["market_in"] if entry_fee is None else entry_fee
    cost = (entry * fin + exit_price * fees["out"]) * fee_mult
    return {
        "r": (gross - cost) / risk,
        "exit_price": exit_price,
        "exit_bar": exit_bar,
        "exit_reason": exit_reason,
        "win": gross - cost > 0,
    }


INTERVAL_MINUTES = {"15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240,
                    "6h": 360, "12h": 720, "1d": 1440, "1w": 10080}


def bars_for_days(interval, days=7):
    """自然时间口径换算：N 天 = 多少根（仅作评估对照口径，未定版）。"""
    m = INTERVAL_MINUTES.get(interval)
    return int(days * 1440 / m) if m else None


def simulate_limit_trade(bars_after, side, limit_price, stop, target,
                         window=300, fee_mult=1.0, fees=None, void=None):
    """限价单回放（2026-10-30 用户口径）：
    - 成交从严：价格必须穿越限价（买单 bar 低点 < 限价；卖单 bar 高点 >
      限价），仅触及不算成交——防「砸穿才成交」的好单被系统性高估；
    - 生命周期锚在决策点：成交只消耗窗口的前段，离场仍在决策点后
      window 根内判定；
    - 未成交不丢弃：返回 filled=False / exit_reason='unfilled'，调用方
      必须留档单独统计（未成交率本身是样本选择偏差的度量）；
    - 入场费按限价费率（fees['limit_in']），与 H1 的净 RR 同口径。
    """
    fees = _fees(fees)
    seg = bars_after[:window]
    fill_bar = None
    for i, b in enumerate(seg):
        if side == "long" and b["l"] < limit_price:
            fill_bar = i
            break
        if side == "short" and b["h"] > limit_price:
            fill_bar = i
            break
        # 成交前先判前提：收盘已越过 void 线，挂单作废（留档单独统计，
        # 与未成交同级）——前提死了的单子不许等它成交。
        if void_hit(void, b["c"]):
            return {"filled": False, "exit_reason": "void_before_fill",
                    "fill_bar": None, "void_bar": i}
    if fill_bar is None:
        return {"filled": False, "exit_reason": "unfilled", "fill_bar": None}
    t = simulate_trade(seg[fill_bar:], side, limit_price, stop, target,
                       fee_mult=fee_mult, fees=fees,
                       entry_fee=fees["limit_in"], void=void)
    if t is None:
        return {"filled": False, "exit_reason": "unfilled", "fill_bar": None}
    t.update({"filled": True, "fill_bar": fill_bar,
              "exit_bar": fill_bar + t["exit_bar"]})
    return t


def _percentile(sorted_vals, q):
    """线性插值分位（与 numpy.percentile 默认口径一致），纯标准库。"""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def summarize(trades, seed=42):
    rs = [float(t["r"]) for t in trades]
    if not rs:
        return {"n": 0}
    wins = [t for t in trades if t["win"]]
    max_streak = streak = 0
    for t in trades:
        streak = 0 if t["win"] else streak + 1
        max_streak = max(max_streak, streak)
    rng = random.Random(seed)
    boots = []
    n = len(rs)
    for _ in range(2000):
        boots.append(sum(rng.choice(rs) for _ in range(n)) / n)
    boots.sort()
    lo, hi = _percentile(boots, 0.025), _percentile(boots, 0.975)
    enough = n >= 30  # 统计底线：样本不足不许下「已证明」结论
    proven = bool(enough and lo > 0)
    if not enough:
        note = f"样本不足（n={n}<30），不下结论"
    elif lo > 0:
        note = ""
    else:
        note = "尚未证明优势（CI 包含或低于 0）"
    srt = sorted(rs)
    med = (_percentile(srt, 0.5))
    return {
        "n": int(n),
        "win_rate": round(len(wins) / n, 4),
        "mean_r": round(sum(rs) / n, 4),
        "median_r": round(med, 4),
        "mean_r_ci95": [round(float(lo), 4), round(float(hi), 4)],
        "max_consec_losses": int(max_streak),
        "proven_edge": proven,
        "note": note,
    }


def _scale_fracs(n_targets):
    """分批出场配比（2026-10-31 用户裁定开启）：T1 出 1/2、T2 出 1/4、
    余 1/4 跟末目标；2 个目标 = 各半；1 个目标 = 全出（与 full 等价）。
    依据 Brooks 分批口径（v21 s92 第一目标至少出一半；v36 s21 配比）。"""
    if n_targets <= 1:
        return [1.0]
    if n_targets == 2:
        return [0.5, 0.5]
    return [0.5, 0.25, 0.25]


def _one_tranche(bars_after, plan, side, target, window, fee_mult, void):
    ot = (plan or {}).get("order_type") or "market"
    if ot == "limit":
        t = simulate_limit_trade(
            bars_after, side, plan["entry"], plan["stop"], target,
            window=window, fee_mult=fee_mult, void=void)
        t["order_type"] = "limit"
        return t
    t = simulate_trade(bars_after[:window], side, plan["entry"], plan["stop"],
                       target, fee_mult=fee_mult, void=void)
    if t is None:
        return {"filled": False, "exit_reason": "no_bars", "order_type": "market"}
    t["order_type"] = "market"
    t["filled"] = True
    return t


def simulate_plan(bars_after, plan, side, window=300, fee_mult=1.0):
    """按计划的 order_type 与 exit_mode 分派回放。

    exit_mode（2026-10-31 开启分批出场）：
    - "full"（缺省）：全仓在首目标结算（2026-10-30 定版口径不变）。
    - "scale"：目标 ≥2 时分批——各档共用同一入场/止损/void/窗口，
      每档独立模拟到自己的目标，总 R = 配比加权。各档共用止损、
      不移保本（简化口径，记账在此）。限价未成交 = 全单未成交。

    返回 dict 一定带 order_type 与 exit_mode；限价未成交时 filled=False、无 R。
    """
    void = (plan or {}).get("void")
    targets = list((plan or {}).get("targets") or [])
    mode = (plan or {}).get("exit_mode") or "full"
    if mode != "scale" or len(targets) < 2:
        t = _one_tranche(bars_after, plan, side, targets[0], window, fee_mult, void)
        t["exit_mode"] = "full"
        return t
    fracs = _scale_fracs(len(targets))
    chosen = [targets[0], targets[1], targets[-1]] if len(targets) > 2 else targets
    tranches = []
    for frac, tgt in zip(fracs, chosen):
        t = _one_tranche(bars_after, plan, side, tgt, window, fee_mult, void)
        if not t.get("filled", True):
            return {"filled": False, "exit_reason": t.get("exit_reason"),
                    "order_type": t["order_type"], "exit_mode": "scale"}
        t["frac"] = frac
        t["target"] = tgt
        tranches.append(t)
    r = sum(t["frac"] * t["r"] for t in tranches)
    return {
        "r": r,
        "win": r > 0,
        "exit_price": tranches[-1]["exit_price"],
        "exit_bar": max(t["exit_bar"] for t in tranches),
        "exit_reason": "scale:" + ",".join(t["exit_reason"] for t in tranches),
        "order_type": tranches[0]["order_type"],
        "exit_mode": "scale",
        "filled": True,
        "tranches": [{"frac": t["frac"], "target": t["target"], "r": t["r"],
                      "exit_reason": t["exit_reason"],
                      "exit_bar": t["exit_bar"]} for t in tranches],
    }
