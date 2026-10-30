"""阶段1：把 trainer 数据池切成 dev / val / test 三个互斥集合。

切分规则（架构方案）：按时间与品种双重隔离——同一数据集只进一个集合；
按周期分层后以固定模式 3:1:1 分配（dev:val:test）。每段沿用 trainer
协议：30 根预热 + 150 根决策窗 + 300 根未来（共 480 根，池内每组 500）。
输出 seg JSON + INDEX.json（含每段 bars 的 sha256，可复现校验）。
"""

import hashlib
import json
import os
from collections import Counter

POOL = os.path.expanduser("~/workspace/trainer-app/pool.json")
OUT = os.path.join(os.path.dirname(__file__), "datasets")
PATTERN = ["dev", "dev", "dev", "val", "test"]
SEG_LEN = 480


def main():
    pool = json.load(open(POOL))
    groups = {}
    for d in pool:
        groups.setdefault(d["interval"], []).append(d)
    manifest = {"splits": {}, "pattern": PATTERN, "seg_len": SEG_LEN}
    counts = Counter()
    for interval, ds in sorted(groups.items()):
        ds.sort(key=lambda d: (d["symbol"], d["bars"][0]["t"]))
        for i, d in enumerate(ds):
            split = PATTERN[i % len(PATTERN)]
            bars = d["bars"][:SEG_LEN]
            seg = {
                "id": d["id"],
                "symbol": d["symbol"],
                "interval": d["interval"],
                "source": d.get("source"),
                "warmup": 30,
                "playable": 150,
                "future": SEG_LEN - 180,
                "t_start": bars[0]["t"],
                "t_end": bars[-1]["t"],
                "bars": bars,
            }
            path = os.path.join(OUT, split, f"{d['id']}.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(seg, f)
            digest = hashlib.sha256(
                json.dumps(bars, sort_keys=True).encode()
            ).hexdigest()[:16]
            manifest["splits"].setdefault(split, []).append(
                {
                    "id": d["id"],
                    "symbol": d["symbol"],
                    "interval": d["interval"],
                    "t_start": seg["t_start"],
                    "t_end": seg["t_end"],
                    "sha256": digest,
                }
            )
            counts[split] += 1
    with open(os.path.join(OUT, "INDEX.json"), "w") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    print("split counts:", dict(counts), "total:", sum(counts.values()))


if __name__ == "__main__":
    main()
