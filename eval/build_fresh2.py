"""fresh2（消融 v0.5 专用）：第二批全新段，标的与 trainer 池、fresh 第一批均零重合。

原 build_fresh 文档：消融专用全新段：标的与现有池（dev/val/test + examples）完全不重合，
窗口从没被判过、从没进过示例池。用户 2026-10-30 裁定：旧 dev 底料与
旧 gold 大面积重合且判过一轮，消融必须换全新未判段。

口径与 build_datasets 一致：480 根 = 30 预热 + 150 决策 + 300 未来；
窗口由 (symbol, interval, slot) 的 sha256 播种决定，可复现；拉取后
校验根数与时间连续性，不合格自动往前挪窗重试。
"""

import hashlib
import json
import os
import sys
import urllib.request

API = "https://data-api.binance.vision/api/v3/klines"
OUT = os.path.join(os.path.dirname(__file__), "datasets", "fresh2")
POOL = os.path.expanduser("~/workspace/trainer-app/pool.json")
SEG_LEN = 480
IMS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
# 15 个全新标的（池内 27 个标的一概不用）× 每标的两段：
# 一段 15m + 一段轮转的 1h/4h/1d
SYMBOLS = ["IMXUSDT", "STXUSDT", "GALAUSDT", "SANDUSDT", "MANAUSDT",
           "AXSUSDT", "CHZUSDT", "THETAUSDT", "ALGOUSDT", "VETUSDT",
           "XTZUSDT", "EGLDUSDT", "SNXUSDT", "CRVUSDT", "RUNEUSDT"]
FRESH1 = {"ENAUSDT", "JUPUSDT", "PYTHUSDT", "WLDUSDT", "FETUSDT", "ONDOUSDT",
          "TRXUSDT", "SHIBUSDT", "UNIUSDT", "AAVEUSDT", "HBARUSDT", "XLMUSDT",
          "ETCUSDT", "BCHUSDT", "LDOUSDT"}
SECOND = ["1h", "4h", "1d"]
RANGE = (1_717_200_000_000, 1_762_000_000_000)  # 2024-06-01 ~ 2025-10-25 UTC


def fetch(symbol, interval, end_ms):
    url = (f"{API}?symbol={symbol}&interval={interval}"
           f"&endTime={end_ms}&limit={SEG_LEN}")
    req = urllib.request.Request(url, headers={"User-Agent": "pa-system/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = json.load(r)
    bars = [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
             "l": float(k[3]), "c": float(k[4]), "v": float(k[5])}
            for k in raw]
    return bars


def contiguous(bars, interval):
    step = IMS[interval]
    return (len(bars) == SEG_LEN
            and all(bars[i + 1]["t"] - bars[i]["t"] == step
                    for i in range(len(bars) - 1)))


def first_bar_t(symbol, interval):
    url = (f"{API}?symbol={symbol}&interval={interval}"
           f"&startTime=0&limit=1")
    req = urllib.request.Request(url, headers={"User-Agent": "pa-system/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return int(json.load(r)[0][0])


def pick_window(symbol, interval, slot):
    seed = int(hashlib.sha256(
        f"{symbol}|{interval}|{slot}".encode()).hexdigest()[:12], 16)
    lo, hi = RANGE
    step = IMS[interval]
    # 上市太晚的标的（如 ONDO 1d）：种子窗可能落在历史不足 480 根处，
    # 往回挪只会更糟——先查最早一根，把可选下限抬到「上市+480 根」之后
    lo = max(lo, first_bar_t(symbol, interval) + SEG_LEN * step)
    span_slots = max(1, (hi - lo) // step)
    end = lo + (seed % span_slots) * step
    for _ in range(12):
        bars = fetch(symbol, interval, end)
        if contiguous(bars, interval):
            return bars
        end -= step  # 只挪一根，不整窗跳（整窗跳是上一版的 bug）
    raise RuntimeError(f"no contiguous window: {symbol} {interval}")


def main():
    pool_syms = {d["symbol"] for d in json.load(open(POOL))}
    assert not (set(SYMBOLS) & pool_syms), "标的与池重合"
    assert not (set(SYMBOLS) & FRESH1), "标的与 fresh 第一批重合"
    os.makedirs(OUT, exist_ok=True)
    manifest = {"splits": {"fresh": []}, "note": "ablation v0.5 fresh2, never judged before"}
    for i, sym in enumerate(SYMBOLS):
        for slot, interval in enumerate(["15m", SECOND[i % 3]]):
            bars = pick_window(sym, interval, slot)
            seg_id = f"f2-{sym}-{interval}-{bars[0]['t']}"
            seg = {"id": seg_id, "symbol": sym, "interval": interval,
                   "source": "binance", "warmup": 30, "playable": 150,
                   "future": SEG_LEN - 180,
                   "t_start": bars[0]["t"], "t_end": bars[-1]["t"],
                   "bars": bars}
            with open(os.path.join(OUT, seg_id + ".json"), "w") as f:
                json.dump(seg, f)
            digest = hashlib.sha256(
                json.dumps(bars, sort_keys=True).encode()).hexdigest()[:16]
            manifest["splits"]["fresh"].append(
                {"id": seg_id, "symbol": sym, "interval": interval,
                 "t_start": seg["t_start"], "t_end": seg["t_end"],
                 "sha256": digest})
            print("ok", seg_id)
    with open(os.path.join(OUT, "INDEX.json"), "w") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    print("fresh segments:", len(manifest["splits"]["fresh"]))


if __name__ == "__main__":
    sys.exit(main())
