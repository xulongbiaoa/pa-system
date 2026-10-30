"""摆动点：收盘折线上的拐点（缺口节「两种锚」口径）。

拐点在收盘折线上认（close 的局部极值，窗口内唯一），锚价取拐点那根 K 的
影线极值（高点取 h、低点取 l）。同向连续拐点只保留更极端的一个，保证
输出严格高低交替。bars 为 [{'t','o','h','l','c','v'}, ...]。
"""


def find_swings(bars, window):
    closes = [b["c"] for b in bars]
    n = len(bars)
    raw = []
    for i in range(window, n - window):
        seg = closes[i - window : i + window + 1]
        c = closes[i]
        if c == max(seg) and seg.count(c) == 1:
            raw.append({"bar": i, "kind": "H", "close": c, "anchor": bars[i]["h"]})
        elif c == min(seg) and seg.count(c) == 1:
            raw.append({"bar": i, "kind": "L", "close": c, "anchor": bars[i]["l"]})
    out = []
    for s in raw:
        if out and out[-1]["kind"] == s["kind"]:
            prev = out[-1]
            if (s["kind"] == "H" and s["anchor"] > prev["anchor"]) or (
                s["kind"] == "L" and s["anchor"] < prev["anchor"]
            ):
                out[-1] = s
            continue
        out.append(s)
    return out
