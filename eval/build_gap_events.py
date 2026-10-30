"""账本事件采样（消融 v0.3）：价格回补敞开缺口锚的到达事件。

与 v0.2 泛要塞触及的区别：事件只认缺口锚——G1 的 R1 账本方向在采样
框里先成立，判读只需审 R2 落点叠加与 R3 到达行为。纯因果、只用位置
维；防伪沿用 v0.2：缺口须至少早 5 根开账、赶路才算到达、同一缺口
全段只记一次、每段至多 2 个且间隔 ≥20 根（纯时序选取）。

分层标记（写入 events.json，供结果分层，不参与选取）：
- attempts：事件时该缺口的既往回补未遂次数（≥1 = 二次回补分层）。
- overlap：落点是否有独立第二锚同址（要塞带 / MM 候选 / 异源摆动点）。

图渲染走 tools/render_fast.py（mplfinance，脱浏览器）。
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
from render_fast import render_bars  # noqa: E402

ROOT = os.path.dirname(__file__)
DS = os.path.join(ROOT, "datasets", "fresh")
OUT = os.path.join(ROOT, "ablation-gap-events")
TOL_MULT = 0.25
SCAN_FROM = 60
SCAN_TO = 180
MAX_EVENTS = 12
SELECT_PER_SEGMENT = 2
SELECT_SPACING = 20
ESTABLISH_LAG = 5
REARM = 3


def has_overlap(pack, gap, tol):
    p = gap["price"]
    for b in pack["fortress"]["bands"]:
        if b["lo"] - tol <= p <= b["hi"] + tol:
            return True
    for m in pack.get("mm", {}).get("candidates", []):
        if abs(m.get("target", 1e18) - p) <= tol:
            return True
    for s in pack["swings"]["major"]:
        # 与缺口锚同址的摆动点多半是缺口的来源（同源），不算第二锚
        if abs(s["anchor"] - p) <= tol and abs(s["anchor"] - p) > tol * 0.5:
            return True
    return False


def find_gap_events(seg, cfg):
    bars = seg["bars"]
    events, spent = [], set()
    in_ep, away = False, REARM
    for d in range(30, SCAN_TO):
        pack = pack_at(bars[:d + 1], cfg)
        tol = TOL_MULT * pack["seg_avg_range"]
        bar = bars[d]
        hit = []
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
                hit.append((g, key, tol))
        if hit and not in_ep and d >= SCAN_FROM:
            g, key, tol0 = hit[0]
            events.append({
                "bar": d + 1, "gap_price": g["price"],
                "trapped": g["trapped"], "attempts": g.get("attempts", 0),
                "overlap": has_overlap(pack, g, tol0),
                "close": bar["c"]})
            spent.add(key)
            in_ep, away = True, 0
            if len(events) >= MAX_EVENTS:
                break
        elif hit:
            away = 0
        else:
            away += 1
            if away >= REARM:
                in_ep = False
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
        for ev in find_gap_events(seg, cfg):
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
                             "gap_price": ev["gap_price"],
                             "trapped": ev["trapped"],
                             "attempts": ev["attempts"],
                             "overlap": ev["overlap"]})
            print("event", eid, "gap", ev["gap_price"],
                  "trapped", ev["trapped"], "attempts", ev["attempts"],
                  "overlap", ev["overlap"])
    with open(os.path.join(OUT, "events.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print("total events:", len(manifest))


if __name__ == "__main__":
    main()
