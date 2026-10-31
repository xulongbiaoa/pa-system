"""执行轴盲考 v2 计分（考试本地脚本，非生产代码）。

回放口径与 v1 一致（毛口径、不计费）：
- 入场成交：计划入场价 > 决策收盘（多）→ stop 单，后续首根 h>=入场价 成交；
  入场价 < 决策收盘（多）→ 限价单，须穿越（l<入场价）才成交；
  入场价 == 决策收盘 → 市价，视为已成交。空头镜像。
- 成交后（含成交根）：同根止损优先；先触目标=+目标R，先触止损=-1R；
  结构化 void 收盘越线 → 按该收盘平仓计 R；日终两者未触 = 0R（附浮动R）。
- scale 出场：按生产配比（1/2, 1/4, 1/4）对各目标档独立回放后加权。
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def replay_one(future, side, entry, stop, target, decision_close, void=None):
    """返回 dict: filled, r, exit_reason, float_r（未成交/未出场时）。"""
    risk = abs(entry - stop)
    if risk <= 0:
        return {"filled": False, "exit_reason": "bad_risk"}
    # --- 成交判定 ---
    fill_i = None
    if entry == decision_close:
        fill_i = -1  # 市价：决策点已成交，用决策收盘作入场价
    for i, b in enumerate(future):
        if fill_i is not None:
            break
        if side == "long":
            if entry > decision_close and b["h"] >= entry:
                fill_i = i
            elif entry < decision_close and b["l"] < entry:
                fill_i = i
        else:
            if entry < decision_close and b["l"] <= entry:
                fill_i = i
            elif entry > decision_close and b["h"] > entry:
                fill_i = i
    if fill_i is None:
        return {"filled": False, "exit_reason": "unfilled"}
    start = max(fill_i, 0)
    for j in range(start, len(future)):
        b = future[j]
        if side == "long":
            if b["l"] <= stop:
                return {"filled": True, "r": -1.0, "exit_reason": "stop",
                        "exit_bar": j + 1}
            if b["h"] >= target:
                return {"filled": True,
                        "r": round((target - entry) / risk, 4),
                        "exit_reason": "target", "exit_bar": j + 1}
        else:
            if b["h"] >= stop:
                return {"filled": True, "r": -1.0, "exit_reason": "stop",
                        "exit_bar": j + 1}
            if b["l"] <= target:
                return {"filled": True,
                        "r": round((entry - target) / risk, 4),
                        "exit_reason": "target", "exit_bar": j + 1}
        if void and isinstance(void, dict) and "level" in void:
            lv, sd = void["level"], void.get("side")
            if (sd == "below" and b["c"] < lv) or (sd == "above" and b["c"] > lv):
                px = b["c"]
                r = (px - entry) / risk if side == "long" else (entry - px) / risk
                return {"filled": True, "r": round(r, 4),
                        "exit_reason": "void", "exit_bar": j + 1}
    last = future[-1]["c"]
    fr = (last - entry) / risk if side == "long" else (entry - last) / risk
    return {"filled": True, "r": 0.0, "exit_reason": "day_end",
            "float_r": round(fr, 4)}


def replay_plan(future, plan, side, decision_close):
    targets = list(plan.get("targets") or [])
    if not targets:
        return {"filled": False, "exit_reason": "no_target"}
    void = plan.get("void")
    if (plan.get("exit_mode") == "scale" and len(targets) >= 2):
        chosen = [targets[0], targets[1], targets[-1]] if len(targets) > 2 else targets
        fracs = [0.5, 0.25, 0.25] if len(chosen) == 3 else [0.5, 0.5]
        tot, parts = 0.0, []
        for frac, tgt in zip(fracs, chosen):
            t = replay_one(future, side, plan["entry"], plan["stop"], tgt,
                           decision_close, void)
            if not t.get("filled"):
                return {"filled": False, "exit_reason": t["exit_reason"],
                        "exit_mode": "scale"}
            tot += frac * t["r"]
            parts.append(t)
        return {"filled": True, "r": round(tot, 4), "exit_reason": "scale",
                "tranches": parts, "exit_mode": "scale"}
    t = replay_one(future, side, plan["entry"], plan["stop"], targets[0],
                   decision_close, void)
    t["exit_mode"] = "full"
    return t


def main():
    key = json.load(open(os.path.join(HERE, "answer-key.json")))["points"]
    out = {}
    for dp, ref in sorted(key.items()):
        seg = json.load(open(os.path.join(HERE, f"seg-{ref['date']}.json")))
        bars = seg["bars"]
        cut = ref["signal_bar"]
        future = bars[cut:]
        dclose = bars[cut - 1]["c"]
        ref_plan = {"entry": ref["entry"], "stop": ref["stop"],
                    "targets": [ref["target"]]}
        ref_r = replay_plan(future, ref_plan, ref["side"], dclose)
        row = {"date": ref["date"], "signal_bar": cut,
               "brooks": {**ref, "replay": ref_r}}
        jp = os.path.join(HERE, f"{dp}-judgment.json")
        if os.path.exists(jp):
            j = json.load(open(jp))
            cands = [c for c in j.get("candidates", []) if c.get("qualified")]
            if cands:
                c = cands[0]
                plan = dict(c["plan"])
                # 与生产 runner 同口径并入 side（adjudicate/replay 需要）
                br = replay_plan(future, plan, c["side"], dclose)
                row["blind"] = {"decision": "trade", "side": c["side"],
                                "setup": c["setup"], "plan": plan,
                                "replay": br}
            else:
                row["blind"] = {"decision": "no_trade",
                                "no_trade_reason": j.get("no_trade_reason"),
                                "pending": j.get("pending_conditions"),
                                "uncertainty": j.get("uncertainty")}
        out[dp] = row
        b = row.get("blind", {})
        print(dp, ref["date"], "bar", cut, ref["side"],
              "| Brooks R:", ref_r.get("r"), ref_r.get("exit_reason"),
              "| blind:", b.get("decision"), b.get("side", ""),
              (b.get("replay") or {}).get("r", ""), b.get("no_trade_reason", ""))
    json.dump(out, open(os.path.join(HERE, "scoring.json"), "w"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
