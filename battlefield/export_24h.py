"""沙盘 24h 数据：15m × 96 根（24 小时）新鲜战场，与影子全史账本分开。

用户 2026-10-31 定版口径：沙盘只要 15min、24 小时。
流程（与影子种子同模式）：
  prepare  抓 96 根已收盘 15m → 建战场 → 落 bars + 待判包 pkg_<SYM>.json
  apply    读判读员输出 output_<SYM>.json，经 BrainSession 契约校验落账
  finalize 重建战场 + 回放大脑输出 → 导出与 export_web 同形的快照
           到 battlefield/web/data24/<SYM>.json（沙盘页专用）
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from battlefield.brain import BrainSession, RecordedAdapter, build_task_package
from battlefield.feed import fetch_klines
from battlefield.queries import QueryService, make_token
from battlefield.runner import build_battlefield

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "battlefield", "web", "data24")
TF_MS = 900_000
BARS_N = 96


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _bar_ms(bar_id):
    try:
        return int(str(bar_id).rsplit("/", 1)[-1])
    except (ValueError, IndexError):
        return None


def _load_bars(sym):
    import dataclasses
    path = os.path.join(OUT, f"bars_{sym}.jsonl")
    rows = [json.loads(l) for l in open(path)]
    from battlefield.contracts import Bar
    from decimal import Decimal
    bars = []
    for d in rows:
        bars.append(Bar(symbol=sym, timeframe="15m",
                        open_time=int(d["open_time"]), close_time=int(d["close_time"]),
                        open=Decimal(str(d["open"])), high=Decimal(str(d["high"])),
                        low=Decimal(str(d["low"])), close=Decimal(str(d["close"])),
                        source=d.get("source", "binance-vision"),
                        received_at=int(d.get("received_at", 0)),
                        data_revision=int(d.get("data_revision", 1))))
    return bars


def prepare(sym: str):
    os.makedirs(OUT, exist_ok=True)
    import dataclasses
    bars = fetch_klines(sym, "15m", limit=100)[-BARS_N:]
    with open(os.path.join(OUT, f"bars_{sym}.jsonl"), "w") as f:
        for b in bars:
            f.write(json.dumps(dataclasses.asdict(b), default=str) + "\n")
    repo = build_battlefield(sym, "15m", TF_MS, bars)
    session = BrainSession(repo, RecordedAdapter([]))
    pkg = build_task_package(repo, session.read_revision)
    json.dump(pkg, open(os.path.join(OUT, f"pkg_{sym}.json"), "w"), ensure_ascii=False, default=str)
    print(sym, "bars:", len(bars), "rev:", pkg["snapshot_revision"], "token:", pkg["token"])


def _rebuild_with_outputs(sym: str, tolerant: bool = False):
    """日内整窗语义：账本只由本窗 bars 构成，输出在整窗建完后按序回放
    （read_cursor == 本窗 revision，旧的严格校验即正确语义）。
    tolerant 参数保留兼容签名，日内模式下不使用。"""
    bars = _load_bars(sym)
    repo = build_battlefield(sym, "15m", TF_MS, bars)
    session = BrainSession(repo, RecordedAdapter([]))
    out_path = os.path.join(OUT, f"output_{sym}.json")
    outputs = []
    if os.path.exists(out_path):
        outputs = [json.loads(l) for l in open(out_path) if l.strip()]
    applied = []
    for out in outputs:
        session.adapter = RecordedAdapter([out])
        res = session.run_once()
        if res["status"] != "ok":
            raise RuntimeError(f"{sym} 大脑输出校验不过: {res}")
        applied.append(out)
    session.applied_count = len(applied)
    session.total_outputs = len(outputs)
    return repo, session, applied


def apply(sym: str, judge_file: str):
    out = json.load(open(judge_file))
    repo = build_battlefield(sym, "15m", TF_MS, _load_bars(sym))
    session = BrainSession(repo, RecordedAdapter([]))
    # 先回放已有输出，再落新的一份
    out_path = os.path.join(OUT, f"output_{sym}.json")
    if os.path.exists(out_path):
        for prev in [json.loads(l) for l in open(out_path) if l.strip()]:
            session.adapter = RecordedAdapter([prev])
            r = session.run_once()
            if r["status"] != "ok":
                raise RuntimeError(f"回放旧输出失败: {r}")
    session.adapter = RecordedAdapter([out])
    res = session.run_once()
    if res["status"] != "ok":
        raise RuntimeError(f"新输出校验不过: {res}")
    with open(out_path, "a") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(sym, "applied:", res)


def finalize(sym: str, tolerant: bool = False):
    repo, session, outputs = _rebuild_with_outputs(sym, tolerant=tolerant)
    token = make_token(repo)
    qs = QueryService(repo, token)
    scene = qs.get_scene()
    changes = qs.get_changes(0)
    bars = _load_bars(sym)
    last_out = outputs[-1] if outputs else None
    ai_cursor = last_out.get("read_cursor") if last_out else None

    # 事件切片：缺口生命周期事件全量保留（时间线要用），其余取最近 300 条
    LIFECYCLE = ("GAP_OPENED", "GAP_CLOSED", "TEST_STARTED", "TEST_ENDED")
    all_events = changes["events"]
    picked = [e for e in all_events if e["type"] in LIFECYCLE]
    picked += [e for e in all_events if e["type"] not in LIFECYCLE][-300:]
    picked_ids = {id(e) for e in picked}
    picked = [e for e in all_events if id(e) in picked_ids]
    events = []
    for e in picked:
        events.append({
            "event_id": e["event_id"], "type": e["type"], "lens": e.get("lens"),
            "level_key": e.get("level_key"), "direction": e.get("direction"),
            "bar_open_ms": _bar_ms(e.get("bar_id", "")),
            "event_time": e.get("event_time"), "confirmed_at": e.get("confirmed_at"),
            "payload": e.get("payload") or {},
        })

    def side(name):
        sa = qs.get_side_activity(name)
        segs = []
        for s in sa["segments"][-6:]:
            r = s["result"]
            segs.append({
                "segment_id": s["segment_id"], "level_key": s["level_key"], "open": s["open"],
                "direction": r.get("direction"), "p0": _num(r.get("p0")),
                "net_progress": _num(r.get("net_progress")),
                "favorable": _num(r.get("favorable_excursion")), "giveback": _num(r.get("giveback")),
                "giveback_ratio": _num(r.get("giveback_ratio")), "elapsed_bars": r.get("elapsed_bars"),
            })
        return {"recorded": sa["recorded"], "events_count": len(sa["events"]), "segments": segs}

    snap = {
        "meta": {
            "symbol": sym, "timeframe": "15m", "token": token,
            "state_revision": scene["revision"], "cursor_close_ms": scene["cursor"],
            "bars_count": len(bars), "generated_at_ms": int(time.time() * 1000),
            "data_health": scene["data_health"],
            "window": "15m × 24h（日内整窗）",
            "book_bars": len(bars),
            "ai": {"outputs": len(outputs),
                   "outputs_total": getattr(session, "total_outputs", len(outputs)),
                   "last_read_cursor": ai_cursor,
                   "last_action": last_out.get("action") if last_out else None,
                   "status": "completed" if last_out else "none",
                   "stale": (ai_cursor is not None and ai_cursor < scene["revision"])
                            or getattr(session, "applied_count", len(outputs)) < getattr(session, "total_outputs", len(outputs))},
            "source": "24h 新鲜战场（feed → runner → QueryService）",
        },
        "bars": [{"t": b.open_time, "o": _num(b.open), "h": _num(b.high),
                  "l": _num(b.low), "c": _num(b.close)} for b in bars[-128:]],
        "levels": [{"level_key": lv["level_key"], "kind": lv["kind"],
                    "lo": _num(lv["lo"]), "hi": _num(lv["hi"]),
                    "watch_lo": _num(lv["watch_lo"]), "watch_hi": _num(lv["watch_hi"])}
                   for lv in scene["levels"]],
        "open_gaps": [{"gap_id": g["gap_id"], "level_key": g["level_key"],
                       "direction": g["direction"], "anchor": _num(g["anchor"]),
                       "test_count": g["test_count"], "opened_ms": _bar_ms(g["opened_bar"]),
                       "tests": [{"started_ms": _bar_ms(t.get("started_bar", "")),
                                  "ended_ms": _bar_ms(t.get("ended_bar", ""))}
                                 for t in g["tests"]]}
                      for g in scene["open_gaps"]],
        "closed_gaps_recent": [{"gap_id": g["gap_id"], "direction": g["direction"],
                                "anchor": _num(g["anchor"]), "test_count": g["test_count"]}
                               for g in scene["just_closed_gaps"][-10:]],
        "events": events,
        # 假设/计划取内核活表（state_dict 快照在最后一根落账时生成，会漏掉其后落账的大脑输出；
        # build_task_package 同口径读 k.hypotheses/k.watch_plans）
        "hypotheses": repo.kernel.hypotheses,
        "watch_plans": repo.kernel.watch_plans,
        "brain_outputs": outputs,
        "candidate_proposals": scene["candidate_proposals"],
        "sides": {"up": side("up"), "down": side("down")},
        "contests_count": len(scene["contests"]),
        "as_known": [],
    }
    path = os.path.join(OUT, f"{sym}.json")
    json.dump(snap, open(path, "w"), ensure_ascii=False, default=str)
    print(sym, "finalized:", path, os.path.getsize(path), "bytes, token", token,
          "open_gaps:", len(snap["open_gaps"]))


def main(argv) -> int:
    cmd, sym = argv[0], argv[1]
    if cmd == "prepare":
        prepare(sym)
    elif cmd == "apply":
        apply(sym, argv[2])
    elif cmd == "finalize":
        finalize(sym)
    else:
        raise SystemExit(f"unknown cmd {cmd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
