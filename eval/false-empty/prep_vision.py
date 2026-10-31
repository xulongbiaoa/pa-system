#!/usr/bin/env python3
"""视觉考试套件生成（2026-10-31 视觉判读 A/B）。

把错误空仓考试 24 题各自渲染成干净图面 PNG（截到决策根为止、
含决策根）：只许蜡烛 + EMA20 + 价格轴，渲染管线与 forward
charts-map 同一口径（tools/render_fast.render_bars）。不叠任何
感知标注（无摆动点/缺口/要塞带标记），图面不含标的名与类别。

bars 口径与 false_empty_exam.prep 完全一致：L/T 用 segment 全量
bars（决策根 = 最后一根），F 用 seg bars 去掉末尾 SHIFT=5 根。

产物：
  charts-vision/X*.png        判读员唯一图面输入
  vision-manifest.json        协调者专用（判读员禁读）：每题 bars
                              根数、决策根 OHLC、段均幅、PNG 路径，
                              供计分对照与价格精度核对。

用法：python3 eval/false-empty/prep_vision.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "eval"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import forward_shadow as fs  # noqa: E402
from perception.features import load_config  # noqa: E402
from render_fast import render_bars  # noqa: E402

BASE = os.path.join(ROOT, "eval", "false-empty")
BRANCH = os.path.join(ROOT, "eval", "branch-ab")
SHIFT = 5
CFG = load_config()


def main():
    corpus = json.load(open(os.path.join(BASE, "corpus.json")))
    pop = {ev["eid"]: ev for ev in
           json.load(open(os.path.join(BRANCH, "population.json")))}
    outdir = os.path.join(BASE, "charts-vision")
    os.makedirs(outdir, exist_ok=True)
    manifest = []
    for c in corpus:
        ev = pop[c["event"]]
        seg = json.load(open(ev["snapshot"]))
        bars = seg["bars"]
        if c["cls"] == "F":
            bars = bars[:len(bars) - SHIFT]
        png = os.path.join(outdir, c["item"] + ".png")
        render_bars(bars, png)
        pack = fs.pack_at(bars, CFG)
        d = bars[-1]
        manifest.append({
            "item": c["item"], "n_bars": len(bars),
            "decision_bar": {"o": d["o"], "h": d["h"], "l": d["l"],
                             "c": d["c"], "t": d["t"]},
            "seg_avg_range": pack["seg_avg_range"],
            "chart": os.path.relpath(png, ROOT),
        })
        print(c["item"], "bars", len(bars), "seg_avg",
              pack["seg_avg_range"], "->", png)
    json.dump(manifest, open(os.path.join(BASE, "vision-manifest.json"), "w"),
              ensure_ascii=False, indent=1)
    print("manifest:", len(manifest), "items")


if __name__ == "__main__":
    main()
