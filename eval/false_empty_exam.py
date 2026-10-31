#!/usr/bin/env python3
"""错误空仓考试（纲领 Build 4，2026-10-31）。

三类卷，标签来自冻结规则的事后认定（不是后来涨跌）：
  L 合法机会：branch-ab judgments2 中已写出 qualified 候选的事件
    ——原判读 + 校验认定当时卡上必须项已齐。重判不出候选 = 漏检。
  T 相似陷阱：judgments2 的 no_trade 事件，其 pending 缺项全部带
    card/branch/skeleton 出处、无一条 extra——原判读记录了真实
    缺失的必要条件。重判写出 qualified = 误放。
  F 未完成片段：L 事件把决策点前移 5 根（同图同地图、条件未走
    完）。重判写出 qualified = 误放（抢跑）。

重判用现行生产提示（prompt_builder + 战役备忘 + 分轨认定，与
branch-ab 到达提示同构），盲判：提示不含类别标签。
评分双轴分开记，永不合并成总一致率：漏检率 = L 未出手 / L；
误放率 = (T+F 出手) / (T+F)，并分班列示。

用法：python3 eval/false_empty_exam.py prep|score [outdir]
"""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "eval"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import forward_shadow as fs  # noqa: E402
import touch_ab as tab  # noqa: E402
from judge.prompt_builder import build_prompt  # noqa: E402
from judge.validate import validate_judgment  # noqa: E402
from perception.features import load_config  # noqa: E402
from render_fast import render_bars  # noqa: E402

CFG = load_config()
DEFAULT_OUT = os.path.join(ROOT, "eval", "false-empty")
BRANCH = os.path.join(ROOT, "eval", "branch-ab")
TOUCH_CHARTS = os.path.join(ROOT, "eval", "touch-ab", "charts-touch")
SHIFT = 5


def _memo(map_obj):
    return (
        "\n\n## 战役备忘（冻结地图附件，本事件开始前画定，不许重画、不许改点）\n\n"
        "下面是本事件的战役地图（决胜点、主/备假设及其 holds_if / takeover_if / void_if 条款）：\n\n"
        "```json\n" + json.dumps(map_obj, ensure_ascii=False, indent=1)
        + "\n```\n\n使用规则（硬纪律）：\n" + tab.RULE1_B
        + "2. 地图假设的 void_if 或战役作废条件已经发生时（例如价格已越过地图标注的 "
          "MM 投影且该假设的顺势分支按其条款关闭、或趋势自起点腿的投影已达），"
          "对应方向的候选不许标 qualified。\n"
        + "3. 地图只供位置与战役状态（决胜点在哪、本腿走到哪一步、哪条分支还活着）；"
          "形态、触发、成色仍以你对图的判读为准；位置与图读冲突时，位置以地图为准。\n")


def _arrival_text(ev, map_obj, bars):
    pack = fs.pack_at(bars, CFG)
    text = build_prompt(pack, bars, segment=ev["eid"], symbol=ev["symbol"])
    return text + _memo(map_obj) + tab.OVERRIDE


def _select_corpus():
    pop = {ev["eid"]: ev for ev in
           json.load(open(os.path.join(BRANCH, "population.json")))}
    L, T = [], []
    for eid, ev in pop.items():
        jp = os.path.join(BRANCH, "judgments2", eid + ".json")
        if not os.path.exists(jp):
            continue
        j = json.load(open(jp))
        if any(c.get("qualified") for c in j.get("candidates") or []):
            L.append(eid)
            continue
        pends = [p for p in j.get("pending_conditions") or []
                 if isinstance(p, dict)]
        miss = [m for p in pends for m in (p.get("missing") or [])]
        if not miss:
            continue
        types = {((m.get("basis") or {}).get("type")) for m in miss
                 if isinstance(m, dict)}
        if miss and all(isinstance(m, dict) for m in miss) \
                and types <= {"card", "branch", "skeleton"}:
            T.append((eid, len(pends), {p.get("setup") for p in pends}))
    # T 选 8：先按 setup 多样性轮取，再按 pending 数补
    T.sort(key=lambda x: -x[1])
    picked, seen = [], set()
    for eid, _, setups in T:
        if len(picked) >= 8:
            break
        if not (setups & seen):
            picked.append(eid)
            seen |= setups
    for eid, _, _ in T:
        if len(picked) >= 8:
            break
        if eid not in picked:
            picked.append(eid)
    return pop, sorted(L), picked


def prep(outdir):
    os.makedirs(os.path.join(outdir, "prompts"), exist_ok=True)
    os.makedirs(os.path.join(outdir, "charts"), exist_ok=True)
    pop, L, T = _select_corpus()
    import random
    raw = []
    corpus = []
    for eid in L:
        ev = pop[eid]
        seg = json.load(open(ev["snapshot"]))
        map_obj = json.load(open(os.path.join(BRANCH, "maps2", eid + ".json")))
        raw.append({"cls": "L", "event": eid,
                    "text": _arrival_text(ev, map_obj, seg["bars"]),
                    "chart_src": os.path.join(TOUCH_CHARTS, eid + ".png")})
        # F：同事件决策点前移 SHIFT 根
        bars_f = seg["bars"][:len(seg["bars"]) - SHIFT]
        raw.append({"cls": "F", "event": eid, "shift": SHIFT,
                    "text": _arrival_text(ev, map_obj, bars_f),
                    "chart_bars": bars_f})
    for eid in T:
        ev = pop[eid]
        seg = json.load(open(ev["snapshot"]))
        map_obj = json.load(open(os.path.join(BRANCH, "maps2", eid + ".json")))
        raw.append({"cls": "T", "event": eid,
                    "text": _arrival_text(ev, map_obj, seg["bars"]),
                    "chart_src": os.path.join(TOUCH_CHARTS, eid + ".png")})
    # 盲码：类别只存 corpus.json（判读员禁读），文件名不带类别
    random.Random(20261031).shuffle(raw)
    for i, r in enumerate(raw, 1):
        code = f"X{i:02d}"
        open(os.path.join(outdir, "prompts", code + ".md"), "w").write(r["text"])
        dst = os.path.join(outdir, "charts", code + ".png")
        if "chart_src" in r:
            shutil.copy(r["chart_src"], dst)
        else:
            render_bars(r["chart_bars"], dst)
        corpus.append({"item": code, "cls": r["cls"], "event": r["event"],
                       **({"shift": r["shift"]} if "shift" in r else {})})
    json.dump(corpus, open(os.path.join(outdir, "corpus.json"), "w"),
              ensure_ascii=False, indent=1)
    from collections import Counter
    print(json.dumps({"items": len(corpus), "by_class": dict(
        Counter(c["cls"] for c in corpus))}, ensure_ascii=False))


def score(outdir):
    corpus = json.load(open(os.path.join(outdir, "corpus.json")))
    jdir = os.path.join(outdir, "judgments")
    rep = {"judged": 0, "format_errors": [], "classes": {}}
    detail = []
    for c in corpus:
        jp = os.path.join(jdir, c["item"] + ".json")
        if not os.path.exists(jp):
            continue
        rep["judged"] += 1
        j = json.load(open(jp))
        errs = validate_judgment(j)
        if errs:
            rep["format_errors"].append({"item": c["item"], "errs": errs})
        acted = any(x.get("qualified") for x in j.get("candidates") or [])
        miss_extra_only = False
        if not acted:
            types = set()
            for p in j.get("pending_conditions") or []:
                if isinstance(p, dict):
                    for m in p.get("missing") or []:
                        if isinstance(m, dict):
                            types.add((m.get("basis") or {}).get("type"))
            miss_extra_only = bool(types) and types == {"extra"}
        detail.append({"item": c["item"], "cls": c["cls"],
                       "acted": acted, "extra_only_refusal": miss_extra_only})
        d = rep["classes"].setdefault(c["cls"], {"n": 0, "acted": 0})
        d["n"] += 1
        d["acted"] += int(acted)
    L = rep["classes"].get("L", {"n": 0, "acted": 0})
    T = rep["classes"].get("T", {"n": 0, "acted": 0})
    F = rep["classes"].get("F", {"n": 0, "acted": 0})
    rep["漏检率_L_missed"] = (round(1 - L["acted"] / L["n"], 3)
                             if L["n"] else None)
    rep["误放率_T"] = round(T["acted"] / T["n"], 3) if T["n"] else None
    rep["误放率_F"] = round(F["acted"] / F["n"], 3) if F["n"] else None
    tf = T["n"] + F["n"]
    rep["误放率_合并"] = (round((T["acted"] + F["acted"]) / tf, 3)
                         if tf else None)
    rep["detail"] = detail
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prep"
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    {"prep": prep, "score": score}[cmd](out)
