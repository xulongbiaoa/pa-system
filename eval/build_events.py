"""消融修正 A+B：多决策点事件化 + 逐点截断图。

病根（g1-ablation-v0.1 附记）：每段只审第 180 根一个瞬间，随机点
极少撞上到达点。本脚本在段内用**因果前缀**机械标出「到点事件」：
某根 K 的振幅触及当时敞开缺口锚或要塞带（±0.25×段均幅）即记一次
到达；连续触及算一个事件（离开 3 根才重新武装）；每段上限 4 个。
事件定义只用位置维与该根之前的数据——不看方向、不看未来。

每个事件产出：截断特征包提示（judge/prompt_builder）+ 截断图
（tools/render_segment，只画事件根之前），供判断层图文双通道盲判。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from perception.features import build_feature_pack, load_config  # noqa: E402
from judge.prompt_builder import build_prompt  # noqa: E402
import render_segment as rs  # noqa: E402

DS = os.path.join(os.path.dirname(__file__), "datasets", "fresh")
OUT = os.path.join(os.path.dirname(__file__), "ablation-events")
SCAN_FROM = 59          # 决策根下标（0-based）：至少 60 根历史才认点
SCAN_TO = 179           # 原决策窗末根
REARM = 3               # 离开决胜点 3 根重新武装
MAX_EVENTS = 4
TOL_MULT = 0.25


def pack_at(bars, cfg):
    p0 = build_feature_pack(bars, [], cfg)
    anchors = [{"price": s["anchor"], "source": "swing-major"}
               for s in p0["swings"]["major"]]
    return build_feature_pack(bars, anchors, cfg)


def levels_of(pack):
    lv = []
    for g in pack["gaps"]["open"]:
        lv.append({"kind": "gap", "lo": g["price"], "hi": g["price"],
                   "trapped": g["trapped"], "attempts": g["attempts"]})
    for b in pack["fortress"]["bands"]:
        lv.append({"kind": "fortress", "lo": b["lo"], "hi": b["hi"],
                   "anchors": b["anchors"]})
    return lv


def find_events(seg, cfg):
    bars = seg["bars"]
    events, in_ep, away = [], False, 0
    for d in range(SCAN_FROM, SCAN_TO + 1):
        pack = pack_at(bars[:d + 1], cfg)
        tol = TOL_MULT * pack["seg_avg_range"]
        bar = bars[d]
        hit = [lv for lv in levels_of(pack)
               if bar["l"] <= lv["hi"] + tol and bar["h"] >= lv["lo"] - tol]
        if hit and not in_ep:
            events.append({"bar": d + 1, "levels": hit,
                           "close": bar["c"], "tol": tol})
            in_ep, away = True, 0
            if len(events) >= MAX_EVENTS:
                break
        elif hit:
            away = 0
        else:
            away += 1
            if away >= REARM:
                in_ep = False
    return events


def main():
    cfg = load_config()
    os.makedirs(os.path.join(OUT, "prompts"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "charts"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "judgments"), exist_ok=True)
    manifest = []
    for name in sorted(os.listdir(DS)):
        if not name.endswith(".json") or name == "INDEX.json":
            continue
        seg = json.load(open(os.path.join(DS, name)))
        evs = find_events(seg, cfg)
        rs.bars_of = lambda _id, s=seg: s["bars"]
        for ev in evs:
            eid = f"{seg['id']}@b{ev['bar']}"
            pack = pack_at(seg["bars"][:ev["bar"]], cfg)
            text = build_prompt(pack, seg["bars"][:ev["bar"]],
                                segment=eid, symbol=seg["symbol"])
            with open(os.path.join(OUT, "prompts", eid + ".md"), "w") as f:
                f.write(text)
            rs.render(seg["id"], os.path.join(OUT, "charts", eid + ".png"),
                      ev["bar"])
            manifest.append({"event": eid, "segment": seg["id"],
                             "symbol": seg["symbol"],
                             "interval": seg["interval"], "bar": ev["bar"],
                             "close": ev["close"], "levels": ev["levels"]})
            print("event", eid, [lv["kind"] for lv in ev["levels"]])
        if not evs:
            print("no-event segment:", seg["id"])
    with open(os.path.join(OUT, "events.json"), "w") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    print("total events:", len(manifest))


if __name__ == "__main__":
    main()
