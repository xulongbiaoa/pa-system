"""行情接入（外部 K 线资源 -> Bar）。翻译内核不负责采集，这里只是薄适配。

数据源：Binance 公开行情镜像 data-api.binance.vision（与前向影子同一源）。
只取已收盘 K 线：接口最后一根可能未收盘，按服务器时间过滤掉。
"""
from __future__ import annotations

import json
import urllib.request
from typing import List

from .contracts import Bar, make_bar

BASE = "https://data-api.binance.vision"

TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
         "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def parse_klines(raw: list, symbol: str, timeframe: str, now_ms: int) -> List[Bar]:
    """Binance kline 数组 -> Bar 列表（只保留 close_time <= now_ms 的已收盘根）。"""
    bars: List[Bar] = []
    for row in raw:
        open_time, close_time = int(row[0]), int(row[6])
        if close_time > now_ms:
            continue
        bars.append(make_bar(symbol, timeframe, open_time, close_time,
                             row[1], row[2], row[3], row[4],
                             source="binance-vision", received_at=now_ms))
    return bars


def fetch_klines(symbol: str, timeframe: str, limit: int = 300) -> List[Bar]:
    url = f"{BASE}/api/v3/klines?symbol={symbol}&interval={timeframe}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "pa-battlefield/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    time_url = f"{BASE}/api/v3/time"
    with urllib.request.urlopen(time_url, timeout=15) as resp:
        now_ms = int(json.loads(resp.read().decode("utf-8"))["serverTime"])
    return parse_klines(raw, symbol, timeframe, now_ms)
