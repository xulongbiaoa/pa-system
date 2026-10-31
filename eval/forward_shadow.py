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
from judge.campaign_prompt import build_map_prompt  # noqa: E402
from judge.prompt_builder import build_prompt  # noqa: E402
from render_fast import render_bars  # noqa: E402

FWD = os.path.join(ROOT, "eval", "forward")
STATE_PATH = os.path.join(FWD, "state.json")
LEDGER_PATH = os.path.join(FWD, "ledger.jsonl")
EVENTS_DIR = os.path.join(FWD, "events")
JUDGE_DIR = os.path.join(FWD, "judgments")
MAPS_DIR = os.path.join(FWD, "maps")
PROMPTS_MAP_DIR = os.path.join(FWD, "prompts-map")
CHARTS_MAP_DIR = os.path.join(FWD, "charts-map")
PROMPTS_EVMAP_DIR = os.path.join(FWD, "prompts-evmap")
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



def compute_trigger(bars, B, cfg):
    """v2 事件触发画图（2026-10-31 用户裁定：影子直升 v2，不等实验门卫）。

    bars 已截到决策根（len == B），B 为决策根 1-based 计数。
    被测点位 = levels_of(决策根特征包) 中被决策根振幅触及的**全部**
    点位（缺口锚与要塞带同为决胜点，不分种类——levels_of 的 gap 点位
    lo==hi，detect_events 标 fortress 的事件实际可能只测到锚线）。
    预警带 = 各点位向外扩 1.0×段均幅；触发根取「最后一段接近」的
    起点：自决策根前一根向前找最后一个「连续 3 根收盘全在预警带
    外」的位置 j，T = j+1；找不到取窗内第一根进入预警带的收盘根；
    再没有取 B-5 对应的下标 B-6。map_bar 下限 clamp 到 45。
    """
    packB = build_events.pack_at(bars[:B], cfg)
    avg = packB["seg_avg_range"]
    tol = 0.25 * avg
    dec = bars[B - 1]
    levels = [lv for lv in build_events.levels_of(packB)
              if dec["l"] <= lv["hi"] + tol and dec["h"] >= lv["lo"] - tol]
    if not levels:
        return None
    zones = [(lv["lo"] - avg, lv["hi"] + avg) for lv in levels]

    def in_zone(k):
        return any(lo <= bars[k]["c"] <= hi for lo, hi in zones)

    lo_k, hi_k = max(29, B - 61), B - 2
    T_idx, fallback = None, None
    for j in range(hi_k, lo_k - 1, -1):
        if j >= 2 and not (in_zone(j) or in_zone(j - 1) or in_zone(j - 2)):
            T_idx, fallback = j + 1, "last_outside_run"
            break
    if T_idx is None:
        for k in range(lo_k, hi_k + 1):
            if in_zone(k):
                T_idx, fallback = k, "first_in_zone"
                break
    if T_idx is None:
        T_idx, fallback = B - 6, "b_minus_5"
    map_bar = T_idx + 1
    clamped = False
    if map_bar < 45:
        map_bar, clamped = 45, True
    return {"map_bar": map_bar, "lag": B - map_bar, "levels": levels,
            "avg": avg, "fallback": fallback, "clamped": clamped}


def _apply_trigger(meta, seg, cfg):
    """把 compute_trigger 结果写回 meta（trigger 子命令 / mapprompt 共用）。"""
    bars = seg["bars"]
    B = meta.get("bar") or len(bars)
    trig = compute_trigger(bars[:B], B, cfg)
    if trig:
        meta["map_bar"] = trig["map_bar"]
        meta["map_lag"] = trig["lag"]
        meta["levels"] = trig["levels"]
        meta["trigger_fallback"] = trig["fallback"]
        meta.pop("trigger_missing", None)
    else:
        meta["map_bar"] = None
        meta["trigger_missing"] = True
    return trig


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
            if ev.get("kind") == "fortress":
                trig = compute_trigger(bars[:bar_idx], bar_idx, cfg)
                if trig:
                    meta["map_bar"] = trig["map_bar"]
                    meta["map_lag"] = trig["lag"]
                    meta["levels"] = trig["levels"]
                else:
                    meta["map_bar"] = None
                    meta["trigger_missing"] = True
            st["queued"][eid] = meta
            new_events.append(meta)
    save_state(st)
    print(json.dumps({"resolved": resolved, "new_events": new_events,
                      "tracked_open": len(st["tracked"]),
                      "queued_unjudged": [e for e in st["queued"]
                                          if st["queued"][e].get("status") is None]},
                     ensure_ascii=False, indent=1))



def trigger(eid):
    """给已排队事件补算触发根，写回 meta 保存。"""
    cfg = load_config()
    st = load_state()
    meta = st["queued"].get(eid)
    if meta is None:
        print(json.dumps({"error": f"event {eid} not queued"}, ensure_ascii=False))
        sys.exit(1)
    seg = json.load(open(meta["snapshot"]))
    trig = _apply_trigger(meta, seg, cfg)
    save_state(st)
    if not trig:
        print(json.dumps({"event": eid, "error": "trigger_missing",
                          "detail": "决策根未触及任何决胜点位，算不出触发根"},
                         ensure_ascii=False))
        sys.exit(1)
    print(json.dumps({"event": eid, "map_bar": trig["map_bar"],
                      "lag": trig["lag"], "levels": trig["levels"],
                      "avg": trig["avg"], "fallback": trig["fallback"],
                      "clamped": trig["clamped"]},
                     ensure_ascii=False, indent=1))


def mapprompt(eid):
    """生成地图提示（触发根截断）+ 触发根图，不判读。"""
    cfg = load_config()
    st = load_state()
    meta = st["queued"].get(eid)
    if meta is None:
        print(json.dumps({"error": f"event {eid} not queued"}, ensure_ascii=False))
        sys.exit(1)
    seg = json.load(open(meta["snapshot"]))
    if not meta.get("map_bar"):
        trig = _apply_trigger(meta, seg, cfg)
        save_state(st)
        if not trig:
            print(json.dumps({"event": eid, "error": "trigger_missing",
                              "detail": "算不出触发根，无法生成地图提示"},
                             ensure_ascii=False))
            sys.exit(1)
    map_bar = meta["map_bar"]
    bars = seg["bars"][:map_bar]
    pack = build_events.pack_at(bars, cfg)
    text = build_map_prompt(pack, bars)
    text = text.replace("第 90 根", f"第 {map_bar} 根")
    os.makedirs(PROMPTS_MAP_DIR, exist_ok=True)
    os.makedirs(CHARTS_MAP_DIR, exist_ok=True)
    ppath = os.path.join(PROMPTS_MAP_DIR, eid + ".md")
    open(ppath, "w").write(text)
    cpath = os.path.join(CHARTS_MAP_DIR, eid + ".png")
    render_bars(bars, cpath)
    print(json.dumps({"event": eid, "map_bar": map_bar,
                      "lag": meta.get("map_lag"),
                      "map_prompt": ppath, "chart": cpath},
                     ensure_ascii=False, indent=1))


def evmaprompt(eid):
    """生成到达判读提示 = AUTO 全文 + 战役备忘（须先有 maps/<eid>.json）。"""
    cfg = load_config()
    st = load_state()
    meta = st["queued"].get(eid)
    if meta is None:
        print(json.dumps({"error": f"event {eid} not queued"}, ensure_ascii=False))
        sys.exit(1)
    maps_path = os.path.join(MAPS_DIR, eid + ".json")
    if not os.path.exists(maps_path):
        print(json.dumps({"event": eid, "error": "map_missing",
                          "detail": f"{maps_path} 不存在，先判读地图并落盘"},
                         ensure_ascii=False))
        sys.exit(1)
    seg = json.load(open(meta["snapshot"]))
    map_obj = json.load(open(maps_path))
    pack = pack_at(seg["bars"], cfg)
    text = build_prompt(pack, seg["bars"], segment=eid, symbol=meta["symbol"])
    memo = (
        "\n\n## 战役备忘（冻结地图附件，本事件开始前画定，不许重画、不许改点）\n\n"
        "下面是本事件的战役地图（决胜点、主/备假设及其 holds_if / takeover_if / void_if 条款）：\n\n"
        "```json\n" + json.dumps(map_obj, ensure_ascii=False, indent=1) + "\n```\n\n"
        "使用规则（硬纪律）：\n"
        "1. 每个候选必须在 candidate 中写 point_id，点名上面地图中的一个决胜点；"
        "决策根收盘价不在该点 [lo, hi] ±0.25×段均幅（附件数字中的段均幅）内时，"
        "该机会只许写进 pending_conditions，不许标 qualified。\n"
        "2. 地图假设的 void_if 或战役作废条件已经发生时（例如价格已越过地图标注的 "
        "MM 投影且该假设的顺势分支按其条款关闭、或趋势自起点腿的投影已达），"
        "对应方向的候选不许标 qualified。\n"
        "3. 地图只供位置与战役状态（决胜点在哪、本腿走到哪一步、哪条分支还活着）；"
        "形态、触发、成色仍以你对图的判读为准；位置与图读冲突时，位置以地图为准。\n")
    os.makedirs(PROMPTS_EVMAP_DIR, exist_ok=True)
    path = os.path.join(PROMPTS_EVMAP_DIR, eid + ".md")
    open(path, "w").write(text + memo)
    print(json.dumps({"event": eid, "evmap_prompt": path}, ensure_ascii=False))


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
    # v2 执法触发口径：fortress 事件、或 meta 已带 map_bar、或已有 maps
    # 文件——满足其一即走 v2，不许因被测点位是缺口锚而回退 AUTO 口径。
    maps_path = os.path.join(MAPS_DIR, eid + ".json")
    v2_active = (meta.get("kind") == "fortress" or meta.get("map_bar")
                 or os.path.exists(maps_path))
    if v2_active and not os.path.exists(maps_path):
        meta["status"] = "map_missing"
        save_state(st)
        print(json.dumps({"event": eid, "error": "map_missing",
                          "detail": f"{maps_path} 不存在，v2 口径不许回退 AUTO 落账"},
                         ensure_ascii=False))
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
    # 与 event_ab.run_arm 同款组装：side/setup/context 在候选层，不在
    # plan 内，须注入后再裁决（2026-10-31 批量轮首个 qualified 候选
    # 撞出：缺 side 时 adjudicate KeyError，此前影子从未有候选过门）。
    plan.update({"side": c["side"], "setup": c.get("setup"),
                 "context": pack["trend"]["label"]})
    if v2_active:
        map_obj = json.load(open(maps_path))
        pts = {p["id"]: p for p in map_obj.get("points") or []}
        pid = c.get("point_id")
        close = seg["bars"][-1]["c"]
        avg = pack.get("seg_avg_range") or 0
        tol = 0.25 * avg
        reason = None
        if not pid:
            reason = "qualified 候选缺 point_id"
        elif pid not in pts:
            reason = f"point_id {pid} 不在地图决胜点中"
        else:
            pt = pts[pid]
            if not (pt["lo"] - tol <= close <= pt["hi"] + tol):
                reason = (f"决策收盘 {close} 不在点 {pid} "
                          f"[{pt['lo']}, {pt['hi']}] ±0.25×段均幅({avg}) 内")
        if reason:
            meta["status"] = "judged_violation"
            meta["violation"] = reason
            save_state(st)
            print(json.dumps({"event": eid, "verdict": "violation",
                              "reason": reason}, ensure_ascii=False))
            return
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
    elif cmd == "trigger":
        trigger(sys.argv[2])
    elif cmd == "mapprompt":
        mapprompt(sys.argv[2])
    elif cmd == "evmaprompt":
        evmaprompt(sys.argv[2])
    elif cmd == "status":
        status()
    else:
        print("usage: forward_shadow.py scan|record <event_id> <judgment.json>"
              "|trigger <event_id>|mapprompt <event_id>|evmaprompt <event_id>|status")
