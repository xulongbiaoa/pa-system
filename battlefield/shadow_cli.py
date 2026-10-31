"""滚动影子 CLI（两段式，给定时任务用）：

  advance --workdir D --symbol BTCUSDT --tf 15m [--limit 1000]
      拉最新已收盘 K 线、追加账本；若大脑未消费到最新 revision，
      把待判读包写到 D/pending_pkg.json 并打印 package_ready；否则打印 up_to_date。
  apply --workdir D --symbol BTCUSDT --tf 15m --output judge_output.json
      校验并落账一份大脑输出，打印结果 JSON。校验不过不落账。

工作目录命名与标的/周期由调用方保持一致；账本内的 bars 自带 symbol/timeframe。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .feed import TF_MS, fetch_klines
from .shadow import ShadowBook


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="battlefield.shadow_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("advance", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--workdir", required=True)
        p.add_argument("--symbol", required=True)
        p.add_argument("--tf", required=True)
        if name == "advance":
            p.add_argument("--limit", type=int, default=1000)
        else:
            p.add_argument("--output", required=True)
    args = ap.parse_args(argv)
    book = ShadowBook(args.workdir, args.symbol, args.tf, TF_MS[args.tf])

    if args.cmd == "advance":
        bars = fetch_klines(args.symbol, args.tf, args.limit)
        added = book.append_bars(bars)
        repo, session, pkg = book.pending_package()
        if pkg is None:
            print(json.dumps({"status": "up_to_date", "added_bars": added,
                              "revision": repo.kernel.revision}))
            return 0
        path = os.path.join(args.workdir, "pending_pkg.json")
        with open(path, "w") as f:
            json.dump(pkg, f, ensure_ascii=False, indent=1, default=str)
        print(json.dumps({"status": "package_ready", "added_bars": added,
                          "revision": repo.kernel.revision,
                          "brain_cursor": session.read_revision, "package": path}))
        return 0

    with open(args.output) as f:
        output = json.load(f)
    result = book.apply_output(output)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
