#!/usr/bin/env python3
"""等待对象化（纲领 Build 3，2026-10-31）：pending 不再随判读蒸发。

判读产生 pending_conditions 后，按其四段链登记为等待对象存入
eval/forward/waits.json：冻结条件集（missing 原文）、观察位置带
（优先取 basis=branch 引用的地图点位带，其次事件被测 levels）、
watch 原文、注册时点。批量轮收尾跑 scan：用新 bars 机械核两件
事——价格回到观察带（recheck → 标 due）与取消事件（被接受粗
口径 / 生命周期到期）。行为与触发的核对不在机械层做：due 只
是把候选送回重判的信号，重判沿用同一张冻结地图与冻结条件集
（dispatch 由批量流程执行，本模块只产 due 清单）。

红线：scan 只许按注册时冻结的带与条件核对；不许在 scan 阶段
新增、放宽或收紧任何条件。假设调整只许因新反证、且由重判的
判读员在 uncertainty 里记录原因。

用法：
  python3 eval/forward_waits.py register   # 从已判读事件登记新 waits
  python3 eval/forward_waits.py scan       # 机械核 open waits，打印汇总
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forward_shadow as fs  # noqa: E402
from judge.pa_cli import pack_at  # noqa: E402

FWD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forward")
WAITS_PATH = os.path.join(FWD, "waits.json")
HORIZON = fs.LIFECYCLE  # 注册后最多跟踪 300 根，超期 expired


def _load_waits():
    if os.path.exists(WAITS_PATH):
        return json.load(open(WAITS_PATH))
    return {}


def _save_waits(w):
    tmp = WAITS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(w, f, ensure_ascii=False, indent=1)
    os.replace(tmp, WAITS_PATH)


def _bands_for(eid, meta, pending):
    """观察位置带：basis=branch 引用的地图点位优先；否则事件 levels。"""
    for miss in pending.get("missing") or []:
        if isinstance(miss, dict):
            b = miss.get("basis") or {}
            if b.get("type") == "branch" and b.get("ref"):
                mp = os.path.join(FWD, "maps", eid + ".json")
                if os.path.exists(mp):
                    m = json.load(open(mp))
                    for p in m.get("points") or []:
                        if p.get("id") == b["ref"]:
                            return [{"lo": p["lo"], "hi": p["hi"],
                                     "src": f"map:{b['ref']}"}]
    return [{"lo": lv["lo"], "hi": lv["hi"], "src": f"level:{lv.get('kind')}"}
            for lv in meta.get("levels") or []]


def build_waits(state, judg_dir):
    """从 state.queued 中 judged_no_trade 且有 pending 的事件构造 waits。

    返回 {wait_id: wait}（不落盘）。已 tracked 的事件不登记（已有仓位
    语义，不是等待）。pending 为字符串旧格式的整条跳过（无 setup 可分）。
    """
    out = {}
    for eid, meta in (state.get("queued") or {}).items():
        if meta.get("status") != "judged_no_trade":
            continue
        jp = os.path.join(judg_dir, eid + ".json")
        if not os.path.exists(jp):
            continue
        j = json.load(open(jp))
        for pending in j.get("pending_conditions") or []:
            if not isinstance(pending, dict) or not pending.get("setup"):
                continue
            wid = f"{eid}::{pending['setup']}"
            bands = _bands_for(eid, meta, pending)
            if not bands:
                continue
            out[wid] = {
                "wait_id": wid, "event": eid,
                "symbol": meta.get("symbol"), "interval": meta.get("interval"),
                "setup": pending["setup"],
                "bands": bands,
                "frozen_missing": pending.get("missing") or [],
                "watch": pending.get("watch") or "",
                "status": "open",
                "registered_decision_t": meta.get("decision_t"),
                "last_checked_t": meta.get("decision_t"),
                "due": None, "closed": None, "history": [],
            }
    return out


def scan_wait(wait, bars):
    """对一根根新 bars（注册时点之后、时间升序）机械核对。

    返回 (transition, info)：transition ∈ due / cancelled / expired /
    None（继续等）。取消粗口径：收盘越过观察带远侧（带外 1.0×段均幅
    以远）连续 2 根 = 被接受（proxy，落账注明）。段均幅用注册事件
    快照的 seg_avg_range，由调用方放入 wait['_avg']（不落盘字段）。
    """
    avg = wait.get("_avg") or 0
    lo = min(b["lo"] for b in wait["bands"])
    hi = max(b["hi"] for b in wait["bands"])
    beyond = 0
    n = 0
    departed = False
    for bar in bars:
        n += 1
        if n > HORIZON:
            return "expired", {"bars_seen": n}
        # 两段式 recheck（2026-10-31 首扫教训）：事件本就选在价格
        # 触带处，注册后第一根触带就标 due 等于没筛选（首扫 215 中
        # 177 due）。必须先「离开」——整根收在带外（不与带重叠）——
        # 再「回到」带内，才算等的那次测试到来。
        touches = any(bar["l"] <= b["hi"] and bar["h"] >= b["lo"]
                      for b in wait["bands"])
        if not departed:
            if not touches:
                departed = True
        elif touches:
            return "due", {"t": bar["t"], "close": bar["c"]}
        if avg and (bar["c"] > hi + avg or bar["c"] < lo - avg):
            beyond += 1
            if beyond >= 2:
                return "cancelled", {"t": bar["t"], "close": bar["c"],
                                     "proxy": "accepted_beyond_band_2close"}
        else:
            beyond = 0
    return None, {"bars_seen": n}


def register():
    st = fs.load_state()
    waits = _load_waits()
    built = build_waits(st, os.path.join(FWD, "judgments"))
    new = {k: v for k, v in built.items() if k not in waits}
    waits.update(new)
    _save_waits(waits)
    print(json.dumps({"registered_new": len(new), "total": len(waits)},
                     ensure_ascii=False))
    return waits


def scan():
    st = fs.load_state()
    waits = _load_waits()
    summary = {"open": 0, "due": [], "cancelled": [], "expired": []}
    cache = {}
    for wid, w in waits.items():
        if w["status"] != "open":
            continue
        summary["open"] += 1
        key = (w["symbol"], w["interval"])
        if key not in cache:
            cache[key] = fs.fetch_bars(w["symbol"], w["interval"],
                                       limit=1000)
        meta = (st.get("queued") or {}).get(w["event"]) or {}
        snap = meta.get("snapshot")
        if snap and os.path.exists(snap):
            seg = json.load(open(snap))
            pack, _ = pack_at(seg, len(seg["bars"]))
            w["_avg"] = pack["seg_avg_range"]
        bars = [b for b in cache[key] if b["t"] > (w["last_checked_t"] or 0)]
        bars.sort(key=lambda b: b["t"])
        tr, info = scan_wait(w, bars)
        w.pop("_avg", None)
        if bars:
            w["last_checked_t"] = bars[-1]["t"]
        if tr == "due":
            w["status"] = "due"
            w["due"] = info
            summary["due"].append(wid)
        elif tr in ("cancelled", "expired"):
            w["status"] = tr
            w["closed"] = info
            summary[tr].append(wid)
        w["history"].append({"scan_t": w["last_checked_t"], "result": tr})
    _save_waits(waits)
    print(json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    {"register": register, "scan": scan}[cmd]()
