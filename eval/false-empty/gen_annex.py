#!/usr/bin/env python3
"""混合臂数字附件生成（2026-10-31 混合臂考试）。

对错误空仓考试 24 题逐题生成数字附件（annex/X*.md）：数据取自
与文本臂同源的决策根特征包——bars 截断口径与 false_empty_exam
.prep / prep_vision 完全一致（L/T 全量、F 前移 SHIFT 根），特征
包用 fs.pack_at(bars, CFG) 在决策根重算。

附件只含位置与价格事实：开账缺口锚（锚价/锚类型/被套侧/开账根
/回补尝试/最大套牢深度）、要塞带（上下沿/锚数/带形态/被测与收
盘穿越次数/踩踏标记）、major 摆动锚（根号/高低/锚价/收盘）、
决策根 OHLC、段均幅。不含任何定性结论：不写趋势标签、不写语
境判断、不给 setup 建议、不附 OHLC 表、不塞特征包原始 JSON。

生成时与 vision-manifest.json 交叉校验（根数、决策根 OHLC、
段均幅逐题一致），不一致即报错退出。

用法：python3 eval/false-empty/gen_annex.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "eval"))

import forward_shadow as fs  # noqa: E402
from perception.features import load_config  # noqa: E402

BASE = os.path.join(ROOT, "eval", "false-empty")
BRANCH = os.path.join(ROOT, "eval", "branch-ab")
SHIFT = 5
CFG = load_config()


def fmt(x):
    """价格格式与 vision-manifest 的 JSON 数值同风格。"""
    if x is None:
        return "—"
    if isinstance(x, float) and x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return str(x)


def annex_text(item, bars, pack):
    n = len(bars)
    d = bars[-1]
    lines = []
    lines.append(f"# 数字附件 · {item}（位置与价位认证）")
    lines.append("")
    lines.append("> 本附件只认证位置与价位：下列锚价、带与摆动点均由决策根")
    lines.append("> 特征包按现行感知口径算出，是图上坐标的索引。语境、结构、")
    lines.append("> 到达、收回一律看图判——本附件不作任何定性判断、不给")
    lines.append("> setup 建议。")
    lines.append("")
    lines.append(f"- 图面根数：共 {n} 根，决策根 = 第 {n} 根（最右一根，已收盘）。")
    lines.append(f"- 决策根 OHLC：O={fmt(d['o'])}，H={fmt(d['h'])}，"
                 f"L={fmt(d['l'])}，C={fmt(d['c'])}")
    lines.append(f"- 段均幅：{fmt(pack['seg_avg_range'])}")
    lines.append("")
    lines.append("## 开账缺口锚（决策时未销账）")
    lines.append("")
    gaps = pack["gaps"]["open"]
    if gaps:
        lines.append("| 锚价 | 锚类型 | 被套侧 | 开账根 | 回补尝试次数 | 最大套牢深度 |")
        lines.append("|---|---|---|---|---|---|")
        for g in gaps:
            src = {"origin": "突破起点锚",
                   "swing-major": "摆动点锚"}.get(g["source"], g["source"])
            trapped = {"long": "多头", "short": "空头"}.get(
                g["trapped"], g["trapped"])
            lines.append(
                f"| {fmt(g['price'])} | {src} | {trapped} | "
                f"第 {g['opened_at'] + 1} 根 | {g['attempts']} | "
                f"{fmt(g['depth'])} |")
    else:
        lines.append("无。")
    lines.append("")
    lines.append("## 要塞带（摆动锚聚类带）")
    lines.append("")
    bands = pack["fortress"]["bands"]
    if bands:
        lines.append("| 带下沿 | 带上沿 | 锚数 | 带形态 | 被测次数 | 收盘穿越次数 | 踩踏 |")
        lines.append("|---|---|---|---|---|---|---|")
        for b in bands:
            shape = "单线（远边未定）" if b["far_undefined"] else "完整带"
            lines.append(
                f"| {fmt(b['lo'])} | {fmt(b['hi'])} | {b['anchors']} | "
                f"{shape} | {b['tests']} | {b['crosses']} | "
                f"{'是' if b['trampled'] else '否'} |")
    else:
        lines.append("无。")
    lines.append("")
    lines.append("## 主要摆动锚（major）")
    lines.append("")
    swings = pack["swings"]["major"]
    if swings:
        lines.append("| 根号 | 高/低 | 锚价（影线极值） | 该根收盘 |")
        lines.append("|---|---|---|---|")
        for s in swings:
            kind = "高点" if s["kind"] == "H" else "低点"
            lines.append(
                f"| 第 {s['bar'] + 1} 根 | {kind} | {fmt(s['anchor'])} | "
                f"{fmt(s['close'])} |")
    else:
        lines.append("无。")
    lines.append("")
    return "\n".join(lines)


def main():
    corpus = json.load(open(os.path.join(BASE, "corpus.json")))
    manifest = {m["item"]: m for m in
                json.load(open(os.path.join(BASE, "vision-manifest.json")))}
    pop = {ev["eid"]: ev for ev in
           json.load(open(os.path.join(BRANCH, "population.json")))}
    outdir = os.path.join(BASE, "annex")
    os.makedirs(outdir, exist_ok=True)
    for c in corpus:
        ev = pop[c["event"]]
        seg = json.load(open(ev["snapshot"]))
        bars = seg["bars"]
        if c["cls"] == "F":
            bars = bars[:len(bars) - SHIFT]
        pack = fs.pack_at(bars, CFG)
        # 与 vision-manifest 交叉校验（同源一致性）
        m = manifest[c["item"]]
        d = bars[-1]
        assert len(bars) == m["n_bars"], (c["item"], "n_bars")
        for k in ("o", "h", "l", "c"):
            assert d[k] == m["decision_bar"][k], (c["item"], k)
        assert pack["seg_avg_range"] == m["seg_avg_range"], \
            (c["item"], "seg_avg_range")
        path = os.path.join(outdir, c["item"] + ".md")
        open(path, "w").write(annex_text(c["item"], bars, pack))
        print(c["item"], "gaps", len(pack["gaps"]["open"]),
              "bands", len(pack["fortress"]["bands"]),
              "swings", len(pack["swings"]["major"]), "->", path)
    print("annex done:", len(corpus), "items")


if __name__ == "__main__":
    main()
