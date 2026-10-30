"""前向影子（阶段 7，2026-10-31 用户裁定开工）。

目的：在**未来真实数据**上攒样本外样本——消融五轮的教训是历史段越用
越薄、拦截系统在历史采样下攒不出成交样本（审计打架 #5）。影子只做
标注与测量：不下单、不碰钱包。

流程（每日一轮，由 cron agent 驱动）：
  1. scan：拉各 watch 的最新已收盘 K 线 → 解析在跟踪的计划（300 根
     生命周期走完或止损/目标/void 触发即落账）→ 在尾部 45 根内用两
     个事件器（要塞触及 / 缺口确认窗，常量临时改指尾部）找新事件 →
     事件快照（只含决策根及以前的 bars，杜绝前视）落 events/。
  2. agent 判读新事件（pa_cli prompt + 图），judgment 存 judgments/。
  3. record：validate + gate（annotation 模式）→ 过门的计划进 tracked
     跟踪；拒/空仓留档在 state。
  4. 落账只进 ledger.jsonl 与 state.json；周五由周回顾汇总。

事件 id：fw-<SYMBOL>-<interval>-<decision bar open time>。
"""

import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "eval"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from perception.features import load_config                     # noqa: E402
from judge.validate import validate_judgment                    # noqa: E402
from gate.risk_rules import adjudicate                          # noqa: E402
from gate.flags import build_flags                              # noqa: E402
from eval.replay import simulate_plan                           # noqa: E402
from eval.pilot_run import merge_candidate_terms                # noqa: E402
from build_events import pack_at                                # noqa: E402
import build_events                                             # noqa: E402
import build_confirm_events                                     # noqa: E402

FWD = os.path.join(ROOT, "eval", "forward")
STATE_PATH = os.path.join(FWD, "state.json")
LEDGER_PATH = os.path.join(FWD, "ledger.jsonl")
EVENTS_DIR = os.path.join(FWD, "events")
JUDGE_DIR = os.path.join(FWD, "judgments")
API = "https://data-api.binance.vision/api/v3/klines"
WATCH = [("BTCUSDT", "15m"), ("BTCUSDT", "1h"),
         ("ETHUSDT", "15m"), ("ETHUSDT", "1h"),
         ("SOLUSDT", "15m"), ("SOLUSDT", "1h"),
         ("DOGEUSDT", "15m"), ("DOGEUSDT", "1h"),
         ("XRPUSDT", "15m"), ("XRPUSDT", "1h"),
         ("LINKUSDT", "15m"), ("LINKUSDT", "1h")]
FETCH_N = 500
TAIL = 45            # 只收尾部 45 根内的新事件
LIFECYCLE = 300


def fetch_bars(symbol, interval, limit=FETCH_N, start_ms=None):
    url = f"{API}?symbol={symbol}&interval={interval}&limit={limit}"
    if start_ms:
        url += f"&startTime={start_ms}"
    rows = None
    for attempt in range(3):            # 快速连拉会撞 400/429，带退避重试
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pa-forward/1.0"})
            rows = json.loads(urllib.request.urlopen(req, timeout=30).read())
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    time.sleep(0.3)                     # 喂数节奏，别把公开端点打爆
    now_ms = int(time.time() * 1000)
    bars = []
    for r in rows:
        if int(r[6]) > now_ms:      # 未收盘的当根不要
            continue
        bars.append({"t": int(r[0]), "o": float(r[1]), "h": float(r[2]),
                     "l": float(r[3]), "c": float(r[4])})
    return bars


def load_state():
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH))
    return {"queued": {}, "tracked": {}, "done": {}}


def save_state(st):
    os.makedirs(FWD, exist_ok=True)
    json.dump(st, open(STATE_PATH, "w"), ensure_ascii=False, indent=1)


def append_ledger(row):
    with open(LEDGER_PATH, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve_tracked(st, cache):
    """跟踪计划解析：未来 bars 达到 300 或已触发出场才落账。"""
    resolved = []
    for eid, tr in list(st["tracked"].items()):
        bars = fetch_bars(tr["symbol"], tr["interval"], limit=400,
                          start_ms=tr["decision_t"])
        future = [b for b in bars if b["t"] > tr["decision_t"]][:LIFECYCLE]
        if not future:
            continue
        t = simulate_plan(future, tr["plan"], tr["side"], window=LIFECYCLE)
        if not t.get("filled", True):
            if len(future) >= LIFECYCLE:
                row = {"event": eid, "outcome": "unfilled", **tr_summary(tr)}
                finish(st, eid, row)
                resolved.append(row)
            continue
        if t["exit_reason"] == "window_end" and len(future) < LIFECYCLE:
            continue                    # 还在生命周期内，继续跟踪
        row = {"event": eid, "outcome": "traded", "r": t["r"],
               "exit_reason": t["exit_reason"], "exit_bar": t["exit_bar"],
               "exit_mode": t.get("exit_mode"), **tr_summary(tr)}
        finish(st, eid, row)
        resolved.append(row)
    return resolved


def tr_summary(tr):
    return {"symbol": tr["symbol"], "interval": tr["interval"],
            "setup": tr["plan"].get("setup"), "side": tr["side"],
            "entry": tr["plan"].get("entry")}


def finish(st, eid, row):
    append_ledger(row)
    st["done"][eid] = row
    st["tracked"].pop(eid, None)


def detect_events(symbol, interval, bars, cfg):
    """尾部事件检测：两个事件器的扫描窗临时改指尾部。"""
    seg = {"bars": bars}
    n = len(bars)
    out = []
    build_events.SCAN_FROM = n - TAIL
    build_events.SCAN_TO = n - 2
    try:
        for ev in build_events.find_events(seg, cfg):
            ev = dict(ev, kind="fortress")
            out.append(ev)
    finally:
        build_events.SCAN_FROM, build_events.SCAN_TO = 59, 179
    build_confirm_events.SCAN_FROM = n - TAIL
    build_confirm_events.SCAN_TO = n - 1
    try:
        for ev in build_confirm_events.find_confirm_events(seg, cfg):
            ev = dict(ev, kind="gap-confirm")
            out.append(ev)
    finally:
        build_confirm_events.SCAN_FROM, build_confirm_events.SCAN_TO = 60, 180
    return out


def scan():
    cfg = load_config()
    st = load_state()
    cache = {}
    resolved = resolve_tracked(st, cache)
    new_events = []
    for symbol, interval in WATCH:
        bars = cache.get((symbol, interval)) or fetch_bars(symbol, interval)
        cache[(symbol, interval)] = bars
        for ev in detect_events(symbol, interval, bars, cfg):
            bar_idx = ev["bar"]
            if bar_idx <= 0 or bar_idx > len(bars):
                continue
            decision_t = bars[bar_idx - 1]["t"]
            eid = f"fw-{symbol}-{interval}-{decision_t}"
            if eid in st["queued"] or eid in st["tracked"] or eid in st["done"]:
                continue
            snap = {"id": eid, "symbol": symbol, "interval": interval,
                    "bars": bars[:bar_idx]}
            os.makedirs(EVENTS_DIR, exist_ok=True)
            path = os.path.join(EVENTS_DIR, eid + ".json")
            json.dump(snap, open(path, "w"), ensure_ascii=False)
            meta = {"event": eid, "symbol": symbol, "interval": interval,
                    "kind": ev.get("kind"), "bar": bar_idx,
                    "decision_t": decision_t, "snapshot": path,
                    "gap_price": ev.get("gap_price"),
                    "attempts": ev.get("attempts")}
            st["queued"][eid] = meta
            new_events.append(meta)
    save_state(st)
    print(json.dumps({"resolved": resolved, "new_events": new_events,
                      "tracked_open": len(st["tracked"]),
                      "queued_unjudged": [e for e in st["queued"]
                                          if st["queued"][e].get("status") is None]},
                     ensure_ascii=False, indent=1))


def record(eid, judgment_path):
    cfg = load_config()
    st = load_state()
    meta = st["queued"].get(eid)
    if meta is None:
        print(json.dumps({"error": f"event {eid} not queued"}, ensure_ascii=False))
        return
    seg = json.load(open(meta["snapshot"]))
    j = json.load(open(judgment_path))
    errs = validate_judgment(j)
    if errs:
        meta["status"] = "format_error"
        meta["errors"] = errs
        save_state(st)
        print(json.dumps({"event": eid, "format_errors": errs}, ensure_ascii=False))
        return
    cands = [c for c in j.get("candidates", []) if c.get("qualified")]
    if not cands:
        meta["status"] = "judged_no_trade"
        meta["pendings"] = j.get("pending_conditions")
        save_state(st)
        print(json.dumps({"event": eid, "verdict": "no_trade"}, ensure_ascii=False))
        return
    c = cands[0]
    plan = dict(c["plan"])
    merge_candidate_terms(plan, c)
    pack = pack_at(seg["bars"], cfg)
    verdict = adjudicate(plan, pack, bars_left=LIFECYCLE,
                         feature_refs=c.get("feature_refs", []),
                         flags=build_flags(plan, pack),
                         ledger=None, mode="annotation")
    if verdict["verdict"] == "reject":
        meta["status"] = "judged_rejected"
        meta["hard_hits"] = verdict["hard_hits"]
        save_state(st)
        print(json.dumps({"event": eid, "verdict": "reject",
                          "hard_hits": verdict["hard_hits"]}, ensure_ascii=False))
        return
    st["tracked"][eid] = {"plan": plan, "side": c["side"],
                          "symbol": meta["symbol"], "interval": meta["interval"],
                          "decision_t": meta["decision_t"]}
    meta["status"] = "tracked"
    save_state(st)
    print(json.dumps({"event": eid, "verdict": "tracked",
                      "setup": plan.get("setup"), "side": c["side"],
                      "entry": plan.get("entry")}, ensure_ascii=False))


def status():
    st = load_state()
    done = list(st["done"].values())
    traded = [d for d in done if d.get("outcome") == "traded"]
    print(json.dumps({
        "queued_unjudged": sum(1 for m in st["queued"].values()
                               if m.get("status") is None),
        "tracked_open": len(st["tracked"]),
        "resolved_total": len(done),
        "traded": len(traded),
        "sum_r": round(sum(d.get("r", 0) for d in traded), 4),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "scan":
        scan()
    elif cmd == "record":
        record(sys.argv[2], sys.argv[3])
    elif cmd == "status":
        status()
    else:
        print("usage: forward_shadow.py scan|record <event_id> <judgment.json>|status")
