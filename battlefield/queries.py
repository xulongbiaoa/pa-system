"""查询层（W05 / 方案 §10）+ 提案写入校验（W06 契约的程序侧）。

每次查询绑定 snapshot token（symbol|timeframe|r<revision>|<cursor>），
不能混合多个时刻的查询结果。真实查询 as_known_at(T) 不返回确认/观察发生在 T 之后的内容。
模型只能写入假设/观察计划提案，且引用必须可核验；无写事实通道。
"""
from __future__ import annotations

from typing import Optional

from .actions import Segment, compare_actions
from .repository import InMemoryRepository


def make_token(repo: InMemoryRepository) -> str:
    k = repo.kernel
    return f"{k.symbol}|{k.timeframe}|r{k.revision}|{k.cursor}"


def _parse_token(token: str):
    parts = token.split("|")
    if len(parts) != 4 or not parts[2].startswith("r"):
        raise ValueError(f"snapshot token 不合法: {token}")
    return parts[0], parts[1], int(parts[2][1:]), int(parts[3])


class QueryService:
    def __init__(self, repo: InMemoryRepository, token: str):
        symbol, tf, revision, cursor = _parse_token(token)
        k = repo.kernel
        if (symbol, tf) != (k.symbol, k.timeframe):
            raise ValueError("token 与仓库标的/周期不一致")
        state = repo.state_at_revision(revision)
        if state is None:
            raise ValueError(f"token 指向不存在的 revision: {revision}")
        if state["cursor"] != cursor:
            raise ValueError("token cursor 与该 revision 投影不一致")
        self.repo = repo
        self.revision = revision
        self.cursor = cursor
        self.state = state

    # ---------- 场景与变化 ----------
    def get_scene(self) -> dict:
        s = self.state
        return {"revision": s["revision"], "cursor": s["cursor"],
                "levels": s["levels"],
                "open_gaps": [g for g in s["gaps"] if g["status"] == "open"],
                "just_closed_gaps": [g for g in s["gaps"] if g["status"] == "closed"],
                "targets": s["targets"], "contests": s["contests"],
                "directional_activity": s["directional_activity"],
                "unresolved": s["unresolved"], "data_health": s["data_health"],
                "active_hypotheses": s["active_hypotheses"],
                "watch_plans": s["watch_plans"],
                "candidate_proposals": s["candidate_proposals"]}

    # 事件的观察镜头：actor=角色行为，terrain=战场变化，terrain+actor=两者
    # （缺口立账/关账既是角色的战果，也是舞台上阵地的生灭）。只在查询副本上标注，
    # 不改事件日志本身。推演引用时据此区分“被行为触发”还是“被战场变化触发”。
    TERRAIN_EVENTS = ("LEVEL_CONFIRMED", "LEVEL_TOUCHED", "RETURN_TO_BAND",
                      "LEFT_BAND_UP", "LEFT_BAND_DOWN", "TARGET_TOUCHED", "DATA_GAP")
    DUAL_EVENTS = ("GAP_OPENED", "GAP_CLOSED")

    @classmethod
    def event_lens(cls, event_type: str) -> str:
        if event_type in cls.DUAL_EVENTS:
            return "terrain+actor"
        if event_type in cls.TERRAIN_EVENTS:
            return "terrain"
        return "actor"

    def get_changes(self, since_revision: int) -> dict:
        if since_revision > self.revision:
            raise ValueError("since_revision 晚于绑定快照")
        start_seq = self.repo.rev_last_seq.get(since_revision, 0)
        end_seq = self.repo.rev_last_seq.get(self.revision, 0)
        evs = []
        for e in self.repo.kernel.events:
            if start_seq < e.sequence <= end_seq:
                d = e.to_dict()
                d["lens"] = self.event_lens(e.type)
                evs.append(d)
        return {"from_revision": since_revision, "to_revision": self.revision, "events": evs}

    def scene_as_known_at(self, t: int) -> dict:
        """真实查询：只返回 T 时刻已知的内容（确认时间 <= T 的对象/事件）。"""
        best = None
        for rev, state in self.repo.snapshots.items():
            if state["cursor"] is not None and state["cursor"] <= t:
                if best is None or rev > best[0]:
                    best = (rev, state)
        if best is None:
            return {"as_known_at": t, "revision": None, "levels": [], "events": []}
        rev, state = best
        levels = []
        for lv in state["levels"]:
            full = self._level_full(lv["level_key"])
            if full is not None and full.confirmed_at <= t:
                levels.append(lv)
        end_seq = self.repo.rev_last_seq.get(rev, 0)
        evs = [e.to_dict() for e in self.repo.kernel.events
               if e.sequence <= end_seq and e.confirmed_at <= t]
        return {"as_known_at": t, "revision": rev, "levels": levels, "events": evs}

    def _level_full(self, level_key: str):
        rt = self.repo.kernel.levels.get(level_key)
        return rt.level if rt else None

    # ---------- 历史与证据 ----------
    def get_history(self, object_id: str) -> dict:
        evs = []
        for e in self.repo.kernel.events:
            if e.sequence > self.repo.rev_last_seq.get(self.revision, 0):
                break
            if e.level_key == object_id or object_id in (
                    e.payload.get("gap_id"), e.payload.get("test_id"),
                    e.payload.get("target_id"), e.payload.get("segment_id")):
                evs.append(e.to_dict())
        return {"object_id": object_id, "events": evs}

    def inspect_evidence(self, object_id: str) -> dict:
        """对象 -> 修改事件 -> 原始 bar 的展开链；引用不存在直接报错，不许充数。"""
        obj = None
        for coll in ("levels", "gaps", "targets", "segments"):
            for item in self.state[coll]:
                keys = [item.get(k) for k in
                        ("level_key", "gap_id", "target_id", "segment_id")]
                if object_id in keys:
                    obj = {"collection": coll, **item}
                    break
            if obj:
                break
        if obj is None:
            raise ValueError(f"证据链不存在: {object_id}")
        hist = self.get_history(object_id)
        bar_ids = {e["bar_id"] for e in hist["events"]}
        bars = []
        for bid in sorted(bar_ids):
            b = self.repo.bars_by_id.get(bid)
            if b is not None and b.close_time <= self.cursor:
                bars.append({"bar_id": bid, "open": str(b.open), "high": str(b.high),
                             "low": str(b.low), "close": str(b.close),
                             "open_time": b.open_time, "close_time": b.close_time})
        return {"object": obj, "events": hist["events"], "bars": bars}

    def read_bars(self, from_time: Optional[int] = None, to_time: Optional[int] = None):
        out = []
        for b in sorted(self.repo.bars_by_id.values(), key=lambda x: x.open_time):
            if b.close_time > self.cursor:
                continue  # 绑定快照之后的数据不可见
            if from_time is not None and b.open_time < from_time:
                continue
            if to_time is not None and b.open_time > to_time:
                continue
            out.append({"bar_id": b.id, "open_time": b.open_time, "close_time": b.close_time,
                        "open": str(b.open), "high": str(b.high),
                        "low": str(b.low), "close": str(b.close)})
        return out

    # ---------- 对照 ----------
    def compare(self, segment_a: str, segment_b: str) -> dict:
        segs = {s.segment_id: s for s in self.repo.kernel.segments.values()}
        if segment_a not in segs or segment_b not in segs:
            raise ValueError("对照的 segment 不存在")
        a, b = segs[segment_a], segs[segment_b]
        return compare_actions(a, b, self.repo.bars_by_id,
                               same_timeframe=True,
                               same_level=(a.level_key == b.level_key))

    # ---------- 单方连续活动（切到小视角也不丢线） ----------
    # 只有“行动类”事件算一方的作为；LEFT_BAND/RETURN/TOUCHED 是价格与地形的位置
    # 关系（价格在带下方不等于空方做了什么），不计入单方活动线。
    SIDE_ACTION_EVENTS = ("ATTEMPT_STARTED", "SEPARATED", "GAP_OPENED", "GAP_CLOSED",
                          "TEST_STARTED", "TEST_ENDED", "RECLAIMED")

    def get_side_activity(self, direction: str) -> dict:
        """某一方在本周期内的连续状态：按时间序的全部事件 + 每段行动的结果向量。

        视角（全局/局部）只是同一状态的窗口，这条线不因缩放而断。
        没有记录到活动时返回 recorded=False —— 是“未观测到”，不是“力量为零”（方案 §6.5）。
        """
        if direction not in ("up", "down"):
            raise ValueError(f"direction 必须是 up/down: {direction}")
        end_seq = self.repo.rev_last_seq.get(self.revision, 0)
        evs = [e.to_dict() for e in self.repo.kernel.events
               if e.sequence <= end_seq and e.direction == direction
               and e.type in self.SIDE_ACTION_EVENTS]
        segs = []
        for s in self.repo.kernel.segments.values():
            if s.direction == direction:
                segs.append({"segment_id": s.segment_id, "level_key": s.level_key,
                             "open": s.open, "result": s.result(self.repo.bars_by_id)})
        return {"direction": direction, "recorded": bool(evs or segs),
                "events": evs, "segments": segs}

    # ---------- 条件核对（观察计划用） ----------
    def check_conditions(self, plan: dict) -> dict:
        satisfied, missing = [], []
        last_bar = None
        bars = self.read_bars()
        if bars:
            last_bar = bars[-1]
        for cond in plan.get("conditions", []):
            ok = self._check_one(cond, last_bar)
            (satisfied if ok else missing).append(cond)
        return {"plan_id": plan.get("plan_id"), "satisfied": satisfied, "missing": missing}

    def _check_one(self, cond: dict, last_bar) -> bool:
        t = cond.get("type")
        s = self.state
        if t == "gap_open":
            return any(g["gap_id"] == cond.get("gap_id") and g["status"] == "open"
                       for g in s["gaps"])
        if t == "gap_closed":
            return any(g["gap_id"] == cond.get("gap_id") and g["status"] == "closed"
                       for g in s["gaps"])
        if t == "test_count_at_least":
            return any(g["level_key"].startswith(cond.get("level_id", "")) and
                       g["test_count"] >= int(cond.get("count", 0)) for g in s["gaps"])
        if t == "attempt_active":
            return any(l["level_key"].startswith(cond.get("level_id", "")) and
                       l["attempt_dir"] == cond.get("direction") for l in s["levels"])
        if t == "target_touched":
            return any(x["target_id"] == cond.get("target_id") and x["touched"]
                       for x in s["targets"])
        return False


# ---------- 提案写入（模型唯一写通道） ----------

_KNOWN_PREFIXES = ("SW-", "GAP-", "SEG-", "T", "ev-")


def _validate_refs(kernel, refs) -> None:
    known = set(kernel.levels.keys()) | set(kernel.gaps.keys()) | \
        set(kernel.targets.keys()) | set(kernel.segments.keys()) | \
        {e.event_id for e in kernel.events} | set(kernel.bars_by_id.keys())
    for r in refs:
        if r not in known and not any(r.startswith(p) and r in known for p in _KNOWN_PREFIXES):
            raise ValueError(f"引用不可核验: {r}")


def propose_hypothesis(repo: InMemoryRepository, hypothesis: dict) -> dict:
    """假设提案：必须带支持与反证引用，引用逐个核验。只写提案分区，不碰事实。"""
    refs = list(hypothesis.get("support_refs", [])) + list(hypothesis.get("counter_refs", []))
    if not refs:
        raise ValueError("假设提案必须至少带一条可核验引用")
    _validate_refs(repo.kernel, refs)
    entry = {"kind": "hypothesis", "status": "proposed", **hypothesis}
    repo.kernel.hypotheses.append(entry)
    return entry


def propose_watch_plan(repo: InMemoryRepository, plan: dict) -> dict:
    """观察计划提案：四段链（观察位置/等待行为/入场触发/取消条件）字段必须齐。"""
    for field_name in ("watch_level", "watch_behavior", "entry_trigger", "cancel_if"):
        if not plan.get(field_name):
            raise ValueError(f"观察计划缺四段链字段: {field_name}")
    _validate_refs(repo.kernel, [plan["watch_level"]])
    entry = {"kind": "watch_plan", "status": "proposed", **plan}
    repo.kernel.watch_plans.append(entry)
    return entry
