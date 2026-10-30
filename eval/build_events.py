"""消融修正 A+B：多决策点事件化 + 逐点截断图。

病根（g1-ablation-v0.1 附记）：每段只审第 180 根一个瞬间，随机点
极少撞上到达点。本脚本在段内用**因果前缀**机械标出「到点事件」：
某根 K 的振幅触及当时敞开缺口锚或要塞带（±0.25×段均幅）即记一次
到达；连续触及算一个事件（离开 3 根才重新武装）；每段上限 4 个。
事件定义只用位置维与该根之前的数据——不看方向、不看未来。

每个事件产出：截断特征包提示（judge/prompt_builder）+ 截断图
（tools/render_segment，只画事件根之前），供判断层图文双通道盲判。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from perception.features import build_feature_pack, load_config  # noqa: E402
from judge.prompt_builder import build_prompt  # noqa: E402
import render_segment as rs  # noqa: E402

DS = os.path.join(os.path.dirname(__file__), "datasets", "fresh")
OUT = os.path.join(os.path.dirname(__file__), "ablation-events")
SCAN_FROM = 59          # 决策根下标（0-based）：至少 60 根历史才认点
SCAN_TO = 179           # 原决策窗末根
REARM = 3               # 离开决胜点 3 根重新武装
MAX_EVENTS = 12  # 收集上限；最终选取见 select_events
SELECT_PER_SEGMENT = 2
SELECT_SPACING = 20   # 同段两事件至少隔 20 根（同一场战斗不重复取样）
TOL_MULT = 0.25
ESTABLISH_LAG = 5   # 点位先于价格到达至少 5 根而存在


def pack_at(bars, cfg):
    p0 = build_feature_pack(bars, [], cfg)
    anchors = [{"price": s["anchor"], "source": "swing-major"}
               for s in p0["swings"]["major"]]
    return build_feature_pack(bars, anchors, cfg)


def levels_of(pack):
    lv = []
    for g in pack["gaps"]["open"]:
        lv.append({"kind": "gap", "lo": g["price"], "hi": g["price"],
                   "trapped": g["trapped"], "attempts": g["attempts"],
                   "opened_at": g.get("opened_at")})
    for b in pack["fortress"]["bands"]:
        # 巨带是区域不是决胜点：带宽超过 2 倍段均幅的，「触及」没有
        # 到达含义（价格常年住在里面），不计入事件点位；锚数 <3 的
        # 弱簇同样不算决胜点。
        if b["hi"] - b["lo"] > 2.0 * pack["seg_avg_range"] or b["anchors"] < 3:
            continue
        lv.append({"kind": "fortress", "lo": b["lo"], "hi": b["hi"],
                   "anchors": b["anchors"]})
    return lv


def level_key(lv, tol):
    """点位身份（同址容差内视为同一点位）：缺口按锚价、要塞按带边。"""
    q = max(tol, 1e-9)
    return (lv["kind"], round(lv["lo"] / q), round(lv["hi"] / q))


def select_events(events):
    """采样选取（与结果无关、只看时序）：时序第一个 + 其后至少隔
    SELECT_SPACING 根的下一个，每段至多 SELECT_PER_SEGMENT 个。
    已知局限：偏向每段较早的到达（首达偏差），报告须声明。"""
    picked = []
    for ev in events:
        if not picked or ev["bar"] - picked[-1]["bar"] >= SELECT_SPACING:
            picked.append(ev)
        if len(picked) >= SELECT_PER_SEGMENT:
            break
    return picked


def find_events(seg, cfg):
    bars = seg["bars"]
    events, in_ep, away = [], False, 0
    spent = set()  # 同一点位全段只记一次到达（重复测试是同一样本重滚）
    # 从第 30 根起先热身跟踪在点/离点状态（不登记）：否则扫描一开局
    # 价格正住在带里会被误记成「到达」（第一版 bar 60 伪事件的病根）。
    for d in range(29, SCAN_TO + 1):
        pack = pack_at(bars[:d + 1], cfg)
        tol = TOL_MULT * pack["seg_avg_range"]
        bar = bars[d]
        # 点位须「先在、价后到」：缺口锚须至少 5 根前已开账，要塞带须
        # 在 5 根前的前缀包里已存在（同址）。否则带是刚在价格脚下
        # 生出来的，触及是假象不是到达（bar 60 伪事件的真病根）。
        prev = pack_at(bars[:d + 1 - ESTABLISH_LAG], cfg) if d + 1 - ESTABLISH_LAG >= 30 else None
        prev_bands = [(b["lo"], b["hi"]) for b in prev["fortress"]["bands"]] if prev else []

        def established(lv):
            if lv["kind"] == "gap":
                return lv.get("opened_at") is not None and lv["opened_at"] <= d + 1 - ESTABLISH_LAG
            return any(abs(lv["lo"] - lo) <= tol and abs(lv["hi"] - hi) <= tol
                       for lo, hi in prev_bands)

        def traveled(lv):
            # 赶路才算到达：触及前 5 根内，收盘须曾离点位 ≥1 倍均幅，
            # 且上一根收盘还在触及带之外——在点位边上蹭来蹭去不算。
            mid = (lv["lo"] + lv["hi"]) / 2
            far = any(abs(bars[k]["c"] - mid) >= pack["seg_avg_range"]
                      for k in range(max(0, d - 5), d))
            prev_out = (bars[d - 1]["c"] > lv["hi"] + tol
                        or bars[d - 1]["c"] < lv["lo"] - tol)
            return far and prev_out

        hit = [lv for lv in levels_of(pack)
               if bar["l"] <= lv["hi"] + tol and bar["h"] >= lv["lo"] - tol
               and established(lv) and traveled(lv)
               and level_key(lv, tol) not in spent]
        if hit and not in_ep and d >= SCAN_FROM:
            events.append({"bar": d + 1, "levels": hit,
                           "close": bar["c"], "tol": tol})
            for lv in hit:
                spent.add(level_key(lv, tol))
            in_ep, away = True, 0
            if len(events) >= MAX_EVENTS:
                break
        elif hit:
            away = 0
        else:
            away += 1
            if away >= REARM:
                in_ep = False
    return select_events(events)


def main():
    cfg = load_config()
    os.makedirs(os.path.join(OUT, "prompts"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "charts"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "judgments"), exist_ok=True)
    manifest = []
    for name in sorted(os.listdir(DS)):
        if not name.endswith(".json") or name == "INDEX.json":
            continue
        seg = json.load(open(os.path.join(DS, name)))
        evs = find_events(seg, cfg)
        rs.bars_of = lambda _id, s=seg: s["bars"]
        for ev in evs:
            eid = f"{seg['id']}@b{ev['bar']}"
            pack = pack_at(seg["bars"][:ev["bar"]], cfg)
            text = build_prompt(pack, seg["bars"][:ev["bar"]],
                                segment=eid, symbol=seg["symbol"])
            with open(os.path.join(OUT, "prompts", eid + ".md"), "w") as f:
                f.write(text)
            rs.render(seg["id"], os.path.join(OUT, "charts", eid + ".png"),
                      ev["bar"])
            manifest.append({"event": eid, "segment": seg["id"],
                             "symbol": seg["symbol"],
                             "interval": seg["interval"], "bar": ev["bar"],
                             "close": ev["close"], "levels": ev["levels"]})
            print("event", eid, [lv["kind"] for lv in ev["levels"]])
        if not evs:
            print("no-event segment:", seg["id"])
    with open(os.path.join(OUT, "events.json"), "w") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    print("total events:", len(manifest))


if __name__ == "__main__":
    main()
