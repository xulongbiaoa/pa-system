"""W09 战场可视化数据导出：页面与 AI 查询读同一份状态。

从 shadow 账本重放恢复战场（ShadowBook.rebuild），再经 QueryService
取 scene / changes / 双角色活动线——与大脑判读完全相同的查询层，
不在导出里另算任何缺口或攻守。产物 = battlefield/web/data/<SYM>.json。

用法：python3 -m battlefield.export_web [SYM ...]（默认 BTCUSDT ETHUSDT）
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from battlefield.queries import QueryService, make_token
from battlefield.shadow import ShadowBook

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DATA = os.path.join(ROOT, "battlefield", "web", "data")
TF_MS = 900_000


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _bar_ms(bar_id: str):
    try:
        return int(str(bar_id).rsplit("/", 1)[-1])
    except (ValueError, IndexError):
        return None


def export_symbol(sym: str) -> dict:
    book = ShadowBook(os.path.join(ROOT, "shadow", f"{sym}-15m"), sym, "15m", TF_MS)
    repo, session = book.rebuild()
    token = make_token(repo)
    qs = QueryService(repo, token)
    scene = qs.get_scene()
    changes = qs.get_changes(0)
    bars = book._read_bars()
    outputs = book._read_outputs()

    last_out = outputs[-1] if outputs else None
    ai_cursor = last_out.get("read_cursor") if last_out else None
    state_rev = scene["revision"]

    events = []
    for e in changes["events"][-300:]:
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
                "direction": r.get("direction"), "net_progress": _num(r.get("net_progress")),
                "favorable": _num(r.get("favorable_excursion")), "giveback": _num(r.get("giveback")),
                "giveback_ratio": _num(r.get("giveback_ratio")), "elapsed_bars": r.get("elapsed_bars"),
            })
        return {"recorded": sa["recorded"], "events_count": len(sa["events"]), "segments": segs}

    snap = {
        "meta": {
            "symbol": sym, "timeframe": "15m", "token": token,
            "state_revision": state_rev, "cursor_close_ms": scene["cursor"],
            "bars_count": len(bars), "generated_at_ms": int(time.time() * 1000),
            "data_health": scene["data_health"],
            "ai": {
                "outputs": len(outputs), "last_read_cursor": ai_cursor,
                "last_action": last_out.get("action") if last_out else None,
                "status": "completed" if last_out else "none",
                "stale": (ai_cursor is not None and ai_cursor < state_rev),
            },
            "source": "shadow ledger replay + QueryService（与 AI 判读同源）",
        },
        "bars": [{"t": b.open_time, "o": _num(b.open), "h": _num(b.high),
                  "l": _num(b.low), "c": _num(b.close)} for b in bars],
        "levels": [{"level_key": lv["level_key"], "kind": lv["kind"],
                    "lo": _num(lv["lo"]), "hi": _num(lv["hi"]),
                    "watch_lo": _num(lv["watch_lo"]), "watch_hi": _num(lv["watch_hi"])}
                   for lv in scene["levels"]],
        "open_gaps": [{"gap_id": g["gap_id"], "level_key": g["level_key"],
                       "direction": g["direction"], "anchor": _num(g["anchor"]),
                       "test_count": g["test_count"],
                       "opened_ms": _bar_ms(g["opened_bar"]),
                       "tests": [{"started_ms": _bar_ms(t.get("started_bar", "")),
                                  "ended_ms": _bar_ms(t.get("ended_bar", ""))}
                                 for t in g["tests"]]}
                      for g in scene["open_gaps"]],
        "closed_gaps_recent": [{"gap_id": g["gap_id"], "direction": g["direction"],
                                "anchor": _num(g["anchor"]), "test_count": g["test_count"]}
                               for g in scene["just_closed_gaps"][-10:]],
        "events": events,
        "hypotheses": scene["active_hypotheses"],
        "watch_plans": scene["watch_plans"],
        "brain_outputs": outputs,
        "sides": {"up": side("up"), "down": side("down")},
        "contests_count": len(scene["contests"]),
    }

    # AS_KNOWN 切片：按每份大脑输出的 read_cursor 取当时已知地形/事件（queries.scene_as_known_at）
    as_known = []
    bars_by_rev = {}
    for i, b in enumerate(bars):
        bars_by_rev[i + 1] = b.close_time
    for out in outputs:
        rc = out.get("read_cursor")
        t = bars_by_rev.get(rc)
        if t is None:
            continue
        ak = qs.scene_as_known_at(t)
        as_known.append({
            "read_cursor": rc, "cursor_close_ms": t,
            "revision": ak.get("revision"),
            "levels": ak.get("levels", []),
            "events_tail": ak.get("events", [])[-120:],
        })
    snap["as_known"] = as_known
    os.makedirs(WEB_DATA, exist_ok=True)
    path = os.path.join(WEB_DATA, f"{sym}.json")
    with open(path, "w") as f:
        json.dump(snap, f, ensure_ascii=False, default=str)
    return {"symbol": sym, "path": path, "bytes": os.path.getsize(path),
            "revision": state_rev, "token": token}


def main(argv=None) -> int:
    syms = argv if argv else ["BTCUSDT", "ETHUSDT"]
    for sym in syms:
        print(export_symbol(sym))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
