"""快速截断图渲染（脱浏览器）：mplfinance，口径与 render_segment.py 一致。

蜡烛（涨 #26a69a / 跌 #ef5350）+ EMA20（#2962FF），白底浅网格，
无时间轴、无标注，只画 cutoff 之前的根。Chrome 版每张约 4 秒，
本实现整批 60 张约数秒。用法：
  python3 tools/render_fast.py <segment.json> <out.png> [cutoff]
或作为库：from render_fast import render_bars; render_bars(bars, out, cutoff)
"""

import os
import sys

sys.path.insert(0, os.path.expanduser("~/workspace/pylibs"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402

_MC = mpf.make_marketcolors(up="#26a69a", down="#ef5350",
                            edge="inherit", wick="inherit", volume="in")
_STYLE = mpf.make_mpf_style(marketcolors=_MC, facecolor="white",
                            gridcolor="#eeeeee", gridstyle="-",
                            rc={"axes.edgecolor": "#cccccc",
                                "font.size": 9})


def ema20(closes):
    k = 2 / 21
    out, prev = [], None
    for c in closes:
        prev = c if prev is None else c * k + prev * (1 - k)
        out.append(prev)
    return out


def render_bars(bars, out_png, cutoff=None):
    data = bars if cutoff is None else bars[:cutoff]
    idx = pd.date_range("2020-01-01", periods=len(data), freq="D")
    df = pd.DataFrame(
        {"Open": [b["o"] for b in data], "High": [b["h"] for b in data],
         "Low": [b["l"] for b in data], "Close": [b["c"] for b in data]},
        index=idx)
    ema = pd.Series(ema20([b["c"] for b in data]), index=idx)
    ap = mpf.make_addplot(ema, color="#2962FF", width=0.9)
    fig, axes = mpf.plot(df, type="candle", style=_STYLE, addplot=ap,
                         figsize=(15, 8), returnfig=True,
                         axisoff=False, tight_layout=True)
    axes[0].set_xticks([])
    axes[0].set_xlabel("")
    fig.savefig(out_png, dpi=100)
    matplotlib.pyplot.close(fig)
    return out_png


def main():
    import json
    seg = json.load(open(sys.argv[1]))
    cutoff = int(sys.argv[3]) if len(sys.argv) > 3 else None
    render_bars(seg["bars"], sys.argv[2], cutoff)
    print("rendered", sys.argv[2])


if __name__ == "__main__":
    main()
