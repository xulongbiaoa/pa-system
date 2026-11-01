"""战场组装器：原始 K 线 -> 完整战场状态，全程不经过“看图识别”。

地形来源 = 机器确认摆动点（confirmed_at 纪律内置）；缺口账本挂在这些位置上。
产出的是可查询的状态与事件，不是图。判读层（brain）只读这里的状态包。
"""
from __future__ import annotations

from typing import List, Optional

from .contracts import Bar
from .queries import QueryService, make_token
from .reducers import Battlefield
from .repository import InMemoryRepository


def build_battlefield(symbol: str, timeframe: str, timeframe_ms: int,
                      bars: List[Bar]) -> InMemoryRepository:
    # 地形：minor (2,2) 分形只作位置；缺口账只开在收盘折线拐点（波段点）
    # 与强突破起点上（定版 v0.2，2026-11-01 对齐线索C《缺口篇 上》；
    # 旧 (5,5) 分形 swing_major 立账已退役——见 design/gap-booking-v02）
    kernel = Battlefield(symbol, timeframe, timeframe_ms,
                         swing_specs=[(2, 2, "swing", "SW")], zigzag=True)
    repo = InMemoryRepository(kernel)
    for b in bars:
        repo.commit_bar(b)
    return repo


def scene_package(repo: InMemoryRepository, since_revision: int = 0) -> dict:
    """给大脑的一份完整状态包：全局 scene + 双角色活动线 + 增量 changes。"""
    qs = QueryService(repo, make_token(repo))
    scene = qs.get_scene()
    last = repo.kernel.bars[-1] if repo.kernel.bars else None
    return {
        "token": make_token(repo),
        "last_bar": ({"open_time": last.open_time, "close_time": last.close_time,
                      "open": str(last.open), "high": str(last.high),
                      "low": str(last.low), "close": str(last.close)} if last else None),
        "scene": scene,
        "side_up": qs.get_side_activity("up"),
        "side_down": qs.get_side_activity("down"),
        "changes": qs.get_changes(since_revision),
    }


def summarize(package: dict) -> str:
    """把状态包压成一段人可读的战场简报（纯文本，不含任何图）。"""
    s = package["scene"]
    lines = [f"战场状态 rev={s['revision']} cursor={s['cursor']}"]
    lines.append(f"位置 {len(s['levels'])} 个；开放缺口 {len(s['open_gaps'])}；"
                 f"已关账缺口 {len(s['just_closed_gaps'])}；争夺位 {len(s['contests'])}")
    for g in s["open_gaps"]:
        lines.append(f"  开放缺口 {g['gap_id']} 向{g['direction']} 锚 {g['anchor']} "
                     f"@{g['level_key']} 已测 {g['test_count']} 次")
    for g in s["just_closed_gaps"][-5:]:
        lines.append(f"  已关账 {g['gap_id']} 向{g['direction']} 锚 {g['anchor']} 测 {g['test_count']} 次")
    for name, side in (("多方", package["side_up"]), ("空方", package["side_down"])):
        segs = side["segments"]
        lines.append(f"{name}：记录到活动={side['recorded']}，行动段 {len(segs)}，"
                     f"事件 {len(side['events'])} 条")
        for seg in segs[-3:]:
            r = seg["result"]
            if r.get("sufficient"):
                lines.append(f"  段 {seg['segment_id']} @{seg['level_key']} 净推进 {r['net_progress']} "
                             f"最大 {r['favorable_excursion']} 回吐 {r['giveback']} 用时 {r['elapsed_bars']} 根")
    dh = s["data_health"]
    lines.append(f"数据健康：缺根 {dh['missing_bars']}，修订冲突 {dh['revision_conflicts']}，"
                 f"连续性破坏 {dh['continuity_broken']}")
    return "\n".join(lines)
