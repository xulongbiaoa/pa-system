"""逐根扫描 + 去重叠：把「一段一决策」换成「一根一决策」，并量出真实样本预算。

## 为什么需要这个模块

金标准/试点是「一段一决策」：30 段最多出 30 个判断，其中只有 2 段有完整
计划（6.7%）。按这个产能，台账任何一格都填不到 n=30（见 eval/ledger.py 的
分格成本表）。直觉上的解法是「逐根扫描」——一段 480 根就有 480 个决策点。

## 但逐根扫描会把 n 吹大 8.7 倍

`baselines.simple_baseline(first_only=False)` 已经能扫全程，50 段原始信号
96 个。问题是一旦信号成立，后面连续几十根都还成立——37 笔的段其实是
同一个 setup 在重叠窗口上重复计数。按「上一笔未离场则不算新样本」去重叠后
只剩 11 笔（压缩 8.7 倍），且**这不是偶然**：

    段长 480 = 30 预热 + 150 决策窗 + 300 未来窗
    生命周期 300 > 决策窗 150

决策窗比生命周期短，所以**一段最多容得下一笔不重叠的交易**。逐根扫描在现有
段协议下根本提高不了独立样本数——它只是把同一笔交易数了很多遍。

## 所以真正要提高的是段数，不是扫描密度

本模块的输出就是那个换算：每段多少笔独立交易 → 每格 n=30 需要多少段。

用法：`python eval/scan.py`（打印预算表，不写文件）；加 `--write` 才把
基线扫描结果落到 knowledge/ledger/baseline_scan.json，且**标 source=baseline**。
基线台账只能当「AI 要跨过的参照线」，不能当 AI 自己的 (p, b) 用。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from baselines import LIFECYCLE, simple_baseline  # noqa: E402
from perception.features import build_feature_pack, load_config  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
SPLITS = ("dev", "val", "test")
SETUP_OF_SIDE = {"long": "A1", "short": "A2"}  # 机械基线 = A1/A2 的机械形态
OUT = os.path.join(ROOT, "knowledge", "ledger", "baseline_scan.json")


def load_pool(splits=SPLITS):
    segs = []
    for split in splits:
        d = os.path.join(ROOT, "eval", "datasets", split)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(".json"):
                continue
            seg = json.load(open(os.path.join(d, name)))
            seg["id"] = name[:-5]
            segs.append(seg)
    return segs


def scan_segment(seg, min_attempts=2, lifecycle=LIFECYCLE, cfg=None):
    """逐根扫描一段，返回**去重叠**后的交易（含 setup / context / order_type）。

    去重叠规则：上一笔的离场根之后才接受下一个信号。这样每笔交易的结局窗
    互不重叠，n 才能当独立样本数用。
    """
    cfg = cfg or load_config()
    hits = simple_baseline(seg, min_attempts=min_attempts, lifecycle=lifecycle,
                           first_only=False)
    out, last_exit = [], -1
    for t in hits:
        if t["entry_bar"] < last_exit:
            continue
        last_exit = t["entry_bar"] + 1 + t["exit_bar"]
        pack = build_feature_pack(seg["bars"][: t["entry_bar"] + 1], [], cfg)
        t = dict(t)
        t.update({
            "segment": seg["id"],
            "setup": SETUP_OF_SIDE[t["side"]],
            "context": pack["trend"]["label"],
            "order_type": "market",
        })
        out.append(t)
    return out


def scan_pool(segs, cfg=None, **kw):
    cfg = cfg or load_config()
    trades = []
    for seg in segs:
        trades.extend(scan_segment(seg, cfg=cfg, **kw))
    return trades


def budget(trades, total_segments, target_n=30, cells=2):
    """样本预算：现有独立交易数 → 每格填到 target_n 需要多少段 / 多少根 K 线。

    cells = 要分别填满的格子数（默认 2：A1/A2 各一格）。
    total_segments 必须是**扫描过的全部段数**，不是「有信号的段数」——用后者
    会把每段产出率算高（11 笔 / 6 段 = 1.83，而真实是 11 / 50 = 0.22）。
    """
    n = len(trades)
    per_cell = n / cells if cells else 0.0
    need_segs = (target_n / per_cell) * total_segments if per_cell else None
    return {
        "trades": n,
        "total_segments": total_segments,
        "trades_per_segment": round(n / total_segments, 4) if total_segments else None,
        "cells": cells,
        "trades_per_cell": round(per_cell, 2),
        "segments_needed_per_cell": None if need_segs is None else round(need_segs),
        "bars_needed_per_cell": None if need_segs is None else round(need_segs * 480),
    }


def _stats(trades):
    rs = [t["r"] for t in trades]
    if not rs:
        return {"n": 0}
    wins = [r for r in rs if r > 0]
    losses = [-r for r in rs if r <= 0]
    b = (sum(wins) / len(wins)) / (sum(losses) / len(losses)) if wins and losses else None
    return {
        "n": len(rs),
        "win_rate": round(len(wins) / len(rs), 4),
        "mean_r": round(sum(rs) / len(rs), 4),
        "b": None if b is None else round(b, 4),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="逐根扫描 + 去重叠 + 样本预算")
    ap.add_argument("--write", action="store_true", help="把基线扫描结果落盘")
    ap.add_argument("--min-attempts", type=int, default=2)
    args = ap.parse_args(argv)
    segs = load_pool()
    cfg = load_config()
    raw = sum(len(simple_baseline(s, min_attempts=args.min_attempts,
                                  first_only=False)) for s in segs)
    trades = scan_pool(segs, min_attempts=args.min_attempts, cfg=cfg)
    print("段数 %d ｜ 原始信号 %d ｜ 去重叠后 %d（压缩 %.1f 倍）" % (
        len(segs), raw, len(trades), raw / max(len(trades), 1)))
    print("整体:", _stats(trades))
    for setup in sorted({t["setup"] for t in trades}):
        sub = [t for t in trades if t["setup"] == setup]
        print("  %s: %s  语境分布 %s" % (
            setup, _stats(sub),
            {k: sum(1 for t in sub if t["context"] == k)
             for k in sorted({t["context"] for t in sub})}))
    b = budget(trades, len(segs), cells=2)
    print("预算: 每段 %.2f 笔 → 每格现有 %.2f 笔 → 每格 n=30 需 %s 段（%s 根 K 线）" % (
        b["trades_per_segment"], b["trades_per_cell"],
        b["segments_needed_per_cell"], b["bars_needed_per_cell"]))
    print("注意：基线不做语境过滤（实测有 A1 多单落在「下降」标签语境里），"
          "它的 by_context 分层只能当参照，不能直接喂 H6 停牌判断。")
    if args.write:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        json.dump({"source": "baseline", "note": "机械基线扫描，非 AI 判断层样本",
                   "trades": trades, "budget": b},
                  open(OUT, "w"), ensure_ascii=False, indent=1)
        print("written:", OUT)
    return trades


if __name__ == "__main__":
    main()
