"""位置来源组装（设计 v2.2 §11 / 事件器 §3）：把三类来源统一成
WatchLevel——地图点（AI 画图，source=model）、机器要塞带与机器
缺口锚（source=machine，细类看 level_id 前缀 FORT/GAP）。

事件器只报事实、不按来源改判：来源只进审计与后续归因。缺口锚
是线不是带：原始带 lo=hi=锚价，观察带取 ±0.25×段均幅（与 G1
到达几何同一口径，只是观察窗、不是执法带）。
"""

from runtime.events import WatchLevel

GAP_WATCH_FRAC = 0.25


def levels_from_map(map_doc):
    out = []
    for p in (map_doc or {}).get("points") or []:
        out.append(WatchLevel(
            level_id=p["id"], level_version=int(p.get("version", 1)),
            kind=p.get("kind", "neutral"),
            lo=p["lo"], hi=p["hi"], watch_lo=p["lo"], watch_hi=p["hi"],
            source="model"))
    return out


def levels_from_pack(pack):
    out = []
    seg_avg = (pack or {}).get("seg_avg_range") or 0.0
    fort = (pack or {}).get("fortress") or {}
    for i, b in enumerate(fort.get("bands") or []):
        out.append(WatchLevel(
            level_id=f"FORT{i}", level_version=1, kind="neutral",
            lo=b["lo"], hi=b["hi"], watch_lo=b["lo"], watch_hi=b["hi"],
            source="machine"))
    gaps = (pack or {}).get("gaps") or {}
    for i, g in enumerate(gaps.get("open") or []):
        anchor = g["anchor"]
        pad = GAP_WATCH_FRAC * seg_avg
        out.append(WatchLevel(
            level_id=f"GAP{i}:{g.get('kind', '')}@{anchor}",
            level_version=1, kind="neutral",
            lo=anchor, hi=anchor,
            watch_lo=anchor - pad, watch_hi=anchor + pad,
            source="machine"))
    return out


def build_watch_levels(map_doc=None, pack=None):
    return levels_from_map(map_doc) + levels_from_pack(pack)
