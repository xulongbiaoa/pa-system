"""仓位建议：凯利公式 + 证据闸门（只建议，不否决；上限仍在 H3）。

用户 2026-10-30 提出「最大风险不该固定，应该用凯利公式确认」。方向对——1%
是拍的。但凯利不能**直接替换**上限，三条理由都能量化：

1. **凯利吃的是真 p，我们只有 p̂。** 金标准 n=2（1 胜 1 负）算出的全凯利是
   32.4% 单笔风险；换成 Wilson 95% 下界（p_lo≈0.095）则是**负值 → 0**。同一
   组数据，凯利给出「满仓」和「不做」两个极端，中间没有稳定答案。用 n=2 的
   p̂ 定仓位，不是科学，是放大器。
2. **凯利假设单笔损失就是押上的那部分。** 止损被穿（插针、跳空、滑点）时
   损失可以超过 1R，左尾比凯利模型厚。这类系统必须先有一个与「优势估计」
   无关的生存上限。
3. **凯利最大化长期对数增长，不保证活着到长期。** 全凯利在真实路径上有相
   当大概率经历 50% 回撤；参数本身有估计误差时，理论上的增长最优分数还要
   再打折（MacLean–Thorp–Ziemba 的分数凯利结论）。

因此本模块分三层，各管一件事：

- **L1 上限**（H3，`RISK_FRAC_MAX=1%`）：生存顶，与证据无关，永不放宽。
- **L2 凯利建议**：只在证据够的格子里出数，用**下界**算、再乘分数系数。
- **L3 证据闸门**：n<30 或下界凯利 ≤0 → 直接 0。这与「样本不足不下结论」
  是同一条纪律的两种写法，不是新增门槛。

台账粒度天然对得上：H6 用的 (setup, 语境) 格子就是凯利该用的单元。代价是
6×3=18 个格子、每格 30 笔才点亮，短期内凯利基本不会生效——这正是老实的
答案：**证据没到，任何仓位都是猜**。
"""

RISK_CAP = 0.01     # 与 gate.risk_rules.RISK_FRAC_MAX 同源
FRACTIONAL = 0.25   # 分数凯利：默认 1/4，参数不确定时留安全边际
MIN_N = 30          # 与 replay.summarize 的统计底线一致
Z = 1.96


def wilson_interval(wins, n, z=Z):
    """胜率的 Wilson 区间（小样本下比正态近似稳，n=0 也能给）。"""
    if n <= 0:
        return 0.0, 1.0
    if wins < 0 or wins > n:
        raise ValueError(f"样本数非法：wins={wins}, n={n}")
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z / denom * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return max(0.0, center - margin), min(1.0, center + margin)


def kelly_fraction(p, b):
    """二项凯利：f* = p − (1−p)/b，b = 净盈亏比（赢的 R / 输的 R）。

    f*<0 表示负优势，下注量为 0（不做空「不下注」这件事）。
    """
    if b is None or b <= 0 or p is None:
        return 0.0
    return max(0.0, p - (1 - p) / b)


def suggest(wins, n, b, cap=RISK_CAP, fractional=FRACTIONAL, min_n=MIN_N, z=Z):
    """返回仓位建议与判定依据。b 用**已实现**的净盈亏比（台账口径）。

    输出里同时给 p̂ 版与下界版的全凯利，让「估计误差有多致命」可见：
    两者差距就是「这笔仓位有多少是猜出来的」。
    """
    p_hat = (wins / n) if n else 0.0
    if n < 0 or wins < 0 or wins > n:
        raise ValueError(f"样本数非法：wins={wins}, n={n}（wins 不得大于 n）")
    p_lo, p_hi = wilson_interval(wins, n, z)
    k_naive = kelly_fraction(p_hat, b)
    k_lo = kelly_fraction(p_lo, b)
    k_hi = kelly_fraction(p_hi, b)
    out = {
        "n": n, "wins": wins, "p_hat": round(p_hat, 4),
        "p_lo": round(p_lo, 4), "p_hi": round(p_hi, 4), "b": b,
        "kelly_naive": round(k_naive, 4),
        "kelly_lo": round(k_lo, 4), "kelly_hi": round(k_hi, 4),
        "fractional": fractional, "cap": cap,
    }
    if n < min_n:
        out.update({"f_raw": 0.0, "f_applied": 0.0, "binding": "evidence",
                    "reason": f"样本不足（n={n}<{min_n}），凯利不可用 → 0"})
        return out
    f_raw = k_lo * fractional
    if f_raw <= 0:
        out.update({"f_raw": 0.0, "f_applied": 0.0, "binding": "evidence",
                    "reason": f"下界凯利 ≤0（p_lo={out['p_lo']}，b={b}），负优势 → 0"})
        return out
    f_applied = min(f_raw, cap)
    binding = "cap" if f_raw > cap else "kelly"
    out.update({
        "f_raw": round(f_raw, 4), "f_applied": round(f_applied, 4),
        "binding": binding,
        "reason": (f"下界凯利 {round(k_lo, 4)} × {fractional} = {round(f_raw, 4)}"
                   + (f"，触上限 {cap}" if binding == "cap" else "")),
    })
    return out
