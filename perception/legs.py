"""腿与 H/L 计数。

腿以反向摆动点为界：没有反向摆动点的一串同向推进永远是一条腿（单腿
口径，不许在一腿内部切第二腿）。H/L 计数：在回调区内，一次「尝试」=
做出新的回调极值之后，第一次有 K 线越过前一根的同向极值（做多方向看
高点）；未做新极值前的重复越界不重复计数。
"""


def legs_from_swings(swings):
    legs = []
    for a, b in zip(swings, swings[1:]):
        legs.append(
            {
                "from_bar": a["bar"],
                "to_bar": b["bar"],
                "dir": "up" if b["anchor"] > a["anchor"] else "down",
                "start": a["anchor"],
                "end": b["anchor"],
                "height": abs(b["anchor"] - a["anchor"]),
            }
        )
    return legs


def count_entry_attempts(bars, start, end, direction):
    """数 bars[start..end] 回调区内的**扩张型**入场尝试（direction='long'
    数 H，'short' 数 L）。

    语义限定：一次新尝试必须**先做出新的回调极值**（做多看新低）再反抽，
    即「回撤在扩张」。所以「第二腿是更高低点」的两腿回调在这里只算 1 次
    ——这不是 bug，是定义；要数腿请用 count_pullback_legs。
    """
    attempts = 0
    need_new_extreme = True
    if direction == "long":
        extreme = bars[start]["l"]
        for i in range(start + 1, end + 1):
            b = bars[i]
            if b["l"] < extreme:
                extreme = b["l"]
                need_new_extreme = True
            if need_new_extreme and b["h"] > bars[i - 1]["h"]:
                attempts += 1
                need_new_extreme = False
    else:
        extreme = bars[start]["h"]
        for i in range(start + 1, end + 1):
            b = bars[i]
            if b["h"] > extreme:
                extreme = b["h"]
                need_new_extreme = True
            if need_new_extreme and b["l"] < bars[i - 1]["l"]:
                attempts += 1
                need_new_extreme = False
    return attempts


def count_pullback_legs(swings, from_bar, to_bar, sep_kind):
    """回调内部的**结构腿数**（A1/A2 卡「回踩已走出第二腿」的计量）。

    与 count_entry_attempts 的分工（2026-10-30 定）：那个数「扩张型尝试」，
    必须先创新低；这里数**腿**——两腿回调的第二腿允许是更高的低点，只要
    中间的反弹在结构上成立。卡片原话是「数腿看结构不看根数」，所以这里
    不加幅度门槛：一根反向摆动只要被摆动识别器认成拐点、且其后还有同向
    推进，就算一级腿。刻意不设 min_retrace —— 多一个拍出来的常数，就多
    一个没人能辩护的自由度。

    口径：[from_bar, to_bar] 内，与回调方向相反的摆动（下行回调看 H）是
    分界；首点之前的极值不算，末点之后没有同向推进的分界也不算（那是
    回调结束的反抽，不是一级腿）。返回 1 = 单腿，2 = 两腿。
    """
    pts = [s for s in swings if from_bar <= s["bar"] <= to_bar]
    if len(pts) < 2:
        return 1
    legs, run = 1, None
    for idx, p in enumerate(pts):
        if p["kind"] == sep_kind:
            has_follow = any(q["kind"] != sep_kind for q in pts[idx + 1:])
            if run is not None and has_follow:
                legs += 1
        else:
            run = p["anchor"] if run is None else min(run, p["anchor"])
    return legs
