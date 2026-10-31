"""前向影子批量扫盘（2026-10-31 用户指令：删 cron，改批量攒样本）。

不再一天一滴等尾部事件：Binance Vision 一次拉 1000 根已收盘 K 线，
把序列切成 480 根窗、步长 300 滑动，逐窗用与 eval/event_ab.py
mine_segment 完全同款的检测口径（build_events 要塞触及 +
build_confirm_events 缺口确认窗，扫描窗 [150, 180)、两类 10 根内
重叠取较早）挖事件。对系统而言未判读过的近期历史就是样本外：
快照只截到决策根，因果口径与既有数据集一致。

事件 id、快照与 meta 结构与 forward_shadow.scan 同构，直接进
state.queued，之后走 forward_shadow 的 trigger/mapprompt/
evmaprompt/record 既有 v2 流程。总量上限 60，按对轮转取。

用法：python3 eval/forward_batch_scan.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "eval"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_events          # noqa: E402
import build_confirm_events  # noqa: E402
import forward_shadow as fs  # noqa: E402
from perception.features import load_config  # noqa: E402

CFG = load_config()
WIN = 480            # 与 event_ab 数据集段长一致
STEP = 300           # 滑动步长（窗间重叠 180 根）
FETCH_LIMIT = 1000
MAX_NEW = 60
SCAN_FROM, SCAN_TO = 150, 180   # 与 event_ab.mine_segment 相同


def mine_window(win_bars):
    """event_ab.mine_segment 的同款逻辑，作用于一个 480 根窗。"""
    seg = {"bars": win_bars}
    found = []
    build_events.SCAN_FROM, build_events.SCAN_TO = SCAN_FROM, SCAN_TO - 1
    try:
        for ev in build_events.find_events(seg, CFG):
            found.append({"bar": ev["bar"], "kind": "fortress",
                          "levels": ev.get("levels")})
    finally:
        build_events.SCAN_FROM, build_events.SCAN_TO = 59, 179
    build_confirm_events.SCAN_FROM = SCAN_FROM
    build_confirm_events.SCAN_TO = SCAN_TO
    try:
        for ev in build_confirm_events.find_confirm_events(seg, CFG):
            found.append({"bar": ev["bar"], "kind": "gap-confirm",
                          "gap_price": ev.get("gap_price"),
                          "attempts": ev.get("attempts")})
    finally:
        build_confirm_events.SCAN_FROM, build_confirm_events.SCAN_TO = 60, 180
    found.sort(key=lambda e: e["bar"])
    # 两类 10 根内重叠取较早者
    dedup = []
    for ev in found:
        if dedup and ev["bar"] - dedup[-1]["bar"] < 10:
            continue
        dedup.append(ev)
    return dedup


def window_starts(n):
    if n < WIN:
        return []
    starts = list(range(0, n - WIN + 1, STEP))
    last = n - WIN
    if starts[-1] != last:
        starts.append(last)
    return starts


def mine_pair(bars):
    """一对 (symbol, interval) 全序事件：换算绝对下标、按 decision_t
    去重、同对间隔 ≥20 根。"""
    cands = []
    for start in window_starts(len(bars)):
        for ev in mine_window(bars[start:start + WIN]):
            abs_bar = start + ev["bar"]
            if abs_bar <= 0 or abs_bar > len(bars):
                continue
            cands.append({"abs_bar": abs_bar,
                          "decision_t": bars[abs_bar - 1]["t"],
                          "kind": ev["kind"],
                          "gap_price": ev.get("gap_price"),
                          "attempts": ev.get("attempts")})
    cands.sort(key=lambda e: e["abs_bar"])
    out, seen_t, last_bar = [], set(), None
    for ev in cands:
        if ev["decision_t"] in seen_t:
            continue
        if last_bar is not None and ev["abs_bar"] - last_bar < 20:
            continue
        seen_t.add(ev["decision_t"])
        last_bar = ev["abs_bar"]
        out.append(ev)
    return out


def main():
    st = fs.load_state()
    known = set(st["queued"]) | set(st["tracked"]) | set(st["done"])
    bars_cache = {}
    pools = {}
    report = {}
    for symbol, interval in fs.WATCH:
        bars = fs.fetch_bars(symbol, interval, limit=FETCH_LIMIT)
        bars_cache[(symbol, interval)] = bars
        evs = mine_pair(bars)
        fresh = []
        for ev in evs:
            eid = f"fw-{symbol}-{interval}-{ev['decision_t']}"
            if eid in known:
                continue
            fresh.append(dict(ev, eid=eid))
        pools[(symbol, interval)] = fresh
        report[(symbol, interval)] = {"bars": len(bars), "found": len(evs),
                                      "fresh": len(fresh)}
        print(f"{symbol} {interval}: bars={len(bars)} found={len(evs)} "
              f"fresh={len(fresh)}", flush=True)
    # 按对轮转取至 MAX_NEW（每对按时间序）
    picked = []
    order = list(fs.WATCH)
    while len(picked) < MAX_NEW and any(pools.values()):
        for pair in order:
            if pools[pair] and len(picked) < MAX_NEW:
                picked.append((pair, pools[pair].pop(0)))
    os.makedirs(fs.EVENTS_DIR, exist_ok=True)
    enqueued = {}
    for (symbol, interval), ev in picked:
        bars = bars_cache[(symbol, interval)]
        abs_bar = ev["abs_bar"]
        eid = ev["eid"]
        snap = {"id": eid, "symbol": symbol, "interval": interval,
                "bars": bars[:abs_bar]}
        path = os.path.join(fs.EVENTS_DIR, eid + ".json")
        json.dump(snap, open(path, "w"), ensure_ascii=False)
        meta = {"event": eid, "symbol": symbol, "interval": interval,
                "kind": ev["kind"], "bar": abs_bar,
                "decision_t": ev["decision_t"], "snapshot": path,
                "gap_price": ev.get("gap_price"),
                "attempts": ev.get("attempts")}
        if ev["kind"] == "fortress":
            trig = fs.compute_trigger(bars[:abs_bar], abs_bar, CFG)
            if trig:
                meta["map_bar"] = trig["map_bar"]
                meta["map_lag"] = trig["lag"]
                meta["levels"] = trig["levels"]
            else:
                meta["map_bar"] = None
                meta["trigger_missing"] = True
        st["queued"][eid] = meta
        enqueued[(symbol, interval)] = enqueued.get((symbol, interval), 0) + 1
    fs.save_state(st)
    print(json.dumps({
        "per_pair": {f"{s} {i}": {**report[(s, i)],
                                  "enqueued": enqueued.get((s, i), 0)}
                     for (s, i) in fs.WATCH},
        "total_enqueued": len(picked),
        "picked_ids": [ev["eid"] for _, ev in picked],
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
