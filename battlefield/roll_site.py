"""网站日内滚动（沙盘 data24 线，用户 2026-10-31 定版：做日内，不做连续全局账本）。

语义：每一轮 = 一个全新的日内战场——抓最近 96 根已收盘 15m（24h）整窗重建，
状态只来自本窗，上一窗的账与简报全部作废（全局信息不进日内盘）。简报每轮由
当值判读基于本窗状态包从零写（read_cursor = 本窗 revision），落账后导出并
上传 R2 sandbox/data24/，线上沙盘轮询读取。

用法：
  python3 -m battlefield.roll_site phase1
      双标的抓数建场（覆盖 bars/pkg，清空旧输出），输出两份包的路径与摘要
  python3 -m battlefield.roll_site phase2 <BTC判读.json> <ETH判读.json>
      两份判读落账 → finalize → 上传，输出 JSON 状态
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from battlefield import export_24h as e24
from battlefield.brain import build_task_package, BrainSession, RecordedAdapter
from battlefield.feed import fetch_klines

OUT = e24.OUT
SYMBOLS = ("BTCUSDT", "ETHUSDT")


def _upload(sym: str) -> str:
    import importlib.util
    cf_path = os.path.expanduser("~/workspace/custom-connectors/custom.cloudflare/bin/cf.py")
    spec = importlib.util.spec_from_file_location("cf", cf_path)
    cf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cf)
    path = os.path.join(OUT, f"{sym}.json")
    with open(path, "rb") as f:
        data = f.read()
    cf.put_object("a17ab4f171dbde6b8de90919cee1d6bc", "abu-assets",
                  f"sandbox/data24/{sym}.json", data, "application/json")
    return f"uploaded {len(data)}B"


def phase1() -> list:
    results = []
    for sym in SYMBOLS:
        bars = fetch_klines(sym, "15m", limit=100)[-e24.BARS_N:]
        with open(os.path.join(OUT, f"bars_{sym}.jsonl"), "w") as f:
            for b in bars:
                f.write(json.dumps(dataclasses.asdict(b), default=str) + "\n")
        # 日内新窗：上一窗的简报全部作废
        out_path = os.path.join(OUT, f"output_{sym}.json")
        if os.path.exists(out_path):
            os.remove(out_path)
        repo = e24.build_battlefield(sym, "15m", e24.TF_MS, bars)
        session = BrainSession(repo, RecordedAdapter([]))
        pkg = build_task_package(repo, session.read_revision)
        pkg_path = os.path.join(OUT, f"pkg_{sym}.json")
        json.dump(pkg, open(pkg_path, "w"), ensure_ascii=False, default=str)
        results.append({"symbol": sym, "bars": len(bars), "token": pkg["token"],
                        "pkg": pkg_path})
    return results


def phase2(judge_files: dict) -> list:
    results = []
    for sym in SYMBOLS:
        e24.apply(sym, judge_files[sym])
        e24.finalize(sym)
        snap = json.load(open(os.path.join(OUT, f"{sym}.json")))
        results.append({"symbol": sym, "token": snap["meta"]["token"],
                        "open_gaps": len(snap["open_gaps"]),
                        "ai_stale": snap["meta"]["ai"]["stale"],
                        "upload": _upload(sym)})
    return results


def main(argv) -> int:
    if argv and argv[0] == "phase1":
        print(json.dumps(phase1(), ensure_ascii=False))
        return 0
    if argv and argv[0] == "phase2":
        print(json.dumps(phase2({"BTCUSDT": argv[1], "ETHUSDT": argv[2]}),
                         ensure_ascii=False))
        return 0
    raise SystemExit("usage: roll_site phase1 | phase2 <btc.json> <eth.json>")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
