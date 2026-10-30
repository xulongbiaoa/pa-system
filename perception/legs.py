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
    """数 bars[start..end] 回调区内的入场尝试次数（direction='long' 数 H，
    'short' 数 L）。"""
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
