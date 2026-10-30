"""数值精度：常规量级保留 6 位小数；小量级（<0.01，如 1e-5 的低价标的）
改用 10 位有效数字，避免 round(x, 6) 把段均幅、EMA 等压成 0。"""


def r6(x):
    if x is None:
        return None
    ax = abs(x)
    if ax == 0 or ax >= 0.01:
        return round(x, 6)
    return float(f"{x:.10g}")
