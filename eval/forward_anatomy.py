"""前向影子出手率解剖（2026-10-31 首跑，用户指令「先解剖出手率」）。

对 eval/forward 已落账的全部判读做机械漏斗统计，不派判读员：
- no_trade_reason 分布、候选总数与构成（setup/side/qualified）；
- pending_conditions 按 setup 计数，missing 文本按关键词粗分桶
  （一条 missing 只计一桶、按位置→触发→定价→成色→腿数→语境顺序
  优先命中，桶间有概念重叠，数字只作量级参考）；
- 在带率机械复核：fortress 事件决策收盘是否落入本地图任一点位
  [lo,hi] ±0.25×段均幅（与 record 点名执法同一容差）。

用法：python3 eval/forward_anatomy.py
"""

import collections
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "eval"))

from judge.pa_cli import pack_at  # noqa: E402

FWD = os.path.join(ROOT, "eval", "forward")


def bucket(text):
    t = text or ""
    if re.search(r"位置|距P|不在.*内|带外|未到达|没到|未落入|赶路", t):
        return "位置(收盘不在点位带内/未到达)"
    if re.search(r"触发|信号K|未收|未齐|未成立|没出|未现|未形成", t):
        return "触发未齐(分支条件差一步)"
    if re.search(r"RR|净RR|1\.5|首目标.*近|目标.*近|封顶", t):
        return "定价(RR/目标太近)"
    if re.search(r"成色|CLV|实体|影线|重叠|质量", t):
        return "成色(信号K质量)"
    if re.search(r"腿|第二腿|两腿|衰竭", t):
        return "腿数/结构未齐"
    if re.search(r"语境|背景|趋势.*达|MM.*达|成熟", t):
        return "语境(背景关)"
    return "其它/未归类"


def main():
    st = json.load(open(os.path.join(FWD, "state.json")))
    meta = st["queued"]
    ntr, cand_setup, cand_side, pend_setup, miss_b = (collections.Counter()
                                                      for _ in range(5))
    n_cand = n_qual = gapc = 0
    inband = {"tracked": [0, 0], "no_trade": [0, 0]}
    paths = sorted(glob.glob(os.path.join(FWD, "judgments", "*.json")))
    for path in paths:
        eid = os.path.basename(path)[:-5]
        j = json.load(open(path))
        m = meta.get(eid) or {}
        if m.get("kind") == "gap-confirm":
            gapc += 1
        ntr[j.get("no_trade_reason") or "(有候选)"] += 1
        for c in j.get("candidates") or []:
            n_cand += 1
            cand_setup[c.get("setup")] += 1
            cand_side[c.get("side")] += 1
            if c.get("qualified"):
                n_qual += 1
        for p in j.get("pending_conditions") or []:
            if isinstance(p, dict):
                pend_setup[p.get("setup")] += 1
                for miss in p.get("missing") or []:
                    miss_b[bucket(miss if isinstance(miss, str) else
                                  json.dumps(miss, ensure_ascii=False))] += 1
        mp = os.path.join(FWD, "maps", eid + ".json")
        sp = m.get("snapshot")
        if os.path.exists(mp) and sp and os.path.exists(sp):
            seg = json.load(open(sp))
            bars = seg["bars"]
            pack, _ = pack_at(seg, len(bars))
            avg, close = pack["seg_avg_range"], bars[-1]["c"]
            mobj = json.load(open(mp))
            hit = any(p["lo"] - 0.25 * avg <= close <= p["hi"] + 0.25 * avg
                      for p in mobj.get("points") or [])
            key = "tracked" if m.get("status") == "tracked" else "no_trade"
            inband[key][0] += hit
            inband[key][1] += 1
    print(json.dumps({
        "judged": len(paths), "gap_confirm_judged": gapc,
        "no_trade_reason": dict(ntr),
        "candidates": n_cand, "qualified": n_qual,
        "cand_by_setup": dict(cand_setup), "cand_by_side": dict(cand_side),
        "pending_by_setup": dict(pend_setup),
        "pending_missing_buckets": dict(miss_b),
        "inband": inband,
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
