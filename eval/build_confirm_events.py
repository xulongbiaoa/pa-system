"""确认窗事件采样（消融 v0.4）：回补到达 + 失败确认，两段式决策点。

v0.3 普查：51 个账本事件的 53 份 G1 挂起里，R3（到达行为）缺失 50 次
——事件定在触及根时，回补失败的行为按定义还没发生（它出现在到达后
1–3 根）。本采样把决策点后移到失败的第一根机械证据：

- 到达：同 v0.3（价格赶路后触及敞开缺口锚，缺口至少早 5 根开账）。
- 确认窗：到达后 CONFIRM_WINDOW 根内，第一根「收盘回到锚的来路一侧
  且越过锚 ≥tol」的 K= 决策根（回补未遂的机械足迹）。窗内无确认
  → 不成事件（回补或成功销账、或漂移，G1 形态未成形）。

仍为纯因果机械选取（只用决策根及之前数据），与 v0.3 的区别仅在
决策时刻的定义；估计对象随之变为「机械确认的回补失败时刻」。
分层标记沿用：attempts（到达时既往未遂次数）、overlap（采样侧宽口径）。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from perception.features import load_config  # noqa: E402
from judge import prompt_builder  # noqa: E402
from build_events import pack_at  # noqa: E402
from build_gap_events import has_overlap  # noqa: E402
from render_fast import render_bars  # noqa: E402

ROOT = os.path.dirname(__file__)
DS = os.path.join(ROOT, "datasets", "fresh")
OUT = os.path.join(ROOT, "ablation-confirm-events")
TOL_MULT = 0.25
SCAN_FROM = 60
SCAN_TO = 180
CONFIRM_WINDOW = 5
SELECT_PER_SEGMENT = 2
SELECT_SPACING = 20
ESTABLISH_LAG = 5


def find_confirm_events(seg, cfg):
    bars = seg["bars"]
    events, spent = [], set()
    d = 30
    while d < SCAN_TO:
        pack = pack_at(bars[:d + 1], cfg)
        tol = TOL_MULT * pack["seg_avg_range"]
        bar = bars[d]
        arrival = None
        for g in pack["gaps"]["open"]:
            if g.get("opened_at") is None or g["opened_at"] > d + 1 - ESTABLISH_LAG:
                continue
            key = round(g["price"] / tol) if tol else 0
            if key in spent:
                continue
            if not (bar["l"] <= g["price"] + tol and bar["h"] >= g["price"] - tol):
                continue
            far = any(abs(bars[k]["c"] - g["price"]) >= pack["seg_avg_range"]
                      for k in range(max(0, d - 5), d))
            prev_out = (bars[d - 1]["c"] > g["price"] + tol
                        or bars[d - 1]["c"] < g["price"] - tol)
            if far and prev_out:
                arrival = (g, key)
                break
        if arrival is None or d < SCAN_FROM:
            d += 1
            continue
        g, key = arrival
        spent.add(key)
        # 来路一侧：到达前一根收盘在锚哪侧，价格就从哪侧来
        origin_above = bars[d - 1]["c"] > g["price"]
        confirm = None
        for j in range(d + 1, min(d + 1 + CONFIRM_WINDOW, SCAN_TO)):
            c = bars[j]["c"]
            if origin_above and c < g["price"] - tol:
                confirm = j
                break
            if not origin_above and c > g["price"] + tol:
                confirm = j
                break
        if confirm is not None:
            events.append({"bar": confirm + 1, "arrival_bar": d + 1,
                           "gap_price": g["price"],
                           "trapped": g["trapped"],
                           "attempts": g.get("attempts", 0),
                           "overlap": has_overlap(pack, g, tol)})
            d = confirm + 1
        else:
            d += 1
    picked = []
    for ev in events:
        if not picked or ev["bar"] - picked[-1]["bar"] >= SELECT_SPACING:
            picked.append(ev)
        if len(picked) >= SELECT_PER_SEGMENT:
            break
    return picked


def main():
    cfg = load_config()
    for sub in ("prompts", "charts", "judgments"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    manifest = []
    for name in sorted(os.listdir(DS)):
        if not name.endswith(".json") or name == "INDEX.json":
            continue
        seg = json.load(open(os.path.join(DS, name)))
        sid = name[:-5]
        for ev in find_confirm_events(seg, cfg):
            eid = f"{sid}@b{ev['bar']}"
            pack = pack_at(seg["bars"][:ev["bar"]], cfg)
            text = prompt_builder.build_prompt(
                pack, seg["bars"][:ev["bar"]], segment=eid,
                symbol=seg["symbol"])
            with open(os.path.join(OUT, "prompts", eid + ".md"), "w") as f:
                f.write(text)
            render_bars(seg["bars"],
                        os.path.join(OUT, "charts", eid + ".png"),
                        cutoff=ev["bar"])
            manifest.append({"event": eid, "segment": sid, "bar": ev["bar"],
                             "arrival_bar": ev["arrival_bar"],
                             "gap_price": ev["gap_price"],
                             "trapped": ev["trapped"],
                             "attempts": ev["attempts"],
                             "overlap": ev["overlap"]})
            print("event", eid, "arrival", ev["arrival_bar"],
                  "gap", ev["gap_price"], "attempts", ev["attempts"])
    with open(os.path.join(OUT, "events.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print("total events:", len(manifest))


if __name__ == "__main__":
    main()
