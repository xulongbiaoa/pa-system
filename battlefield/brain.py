"""单一大脑判读层（W06 / 方案 §10，2026-10-31 用户定性“一个全局大脑”后定案）。

设计定案：不再分 MAP / ARRIVAL 两个任务。一个判读任务同时读
- 全局：get_scene（地形/开放缺口/目标/争夺/假设/观察计划）；
- 局部：自上次 read cursor 以来的 get_changes（最近交战与事件）。
假设由这一个大脑集中维护（add / confirm / challenge / supersede，带修订历史）。

硬契约：
- 输出必须回显 read_cursor == 本次快照 revision，不符 = 过期评估（StaleAssessment），不落任何写入；
- 一切引用先全量核验、后统一落盘（校验不过 = 契约错误，不写一半）；
- 模型不可用/超时是系统结果（model_unavailable），绝不记成策略无机会，cursor 不推进；
- 候选只进 candidate_proposals 提案分区，不是事实、不是订单，gate 在本层之外；
- 本层没有任何写事实的通道：只能写假设/观察计划/候选三个提案分区。
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Callable, List, Optional

from .queries import QueryService, _validate_refs, make_token, propose_watch_plan
from .repository import InMemoryRepository

ACTIONS = ("WATCH", "WAIT_BEHAVIOR", "PROPOSE_CANDIDATE", "CANCEL",
           "INFORMATION_INSUFFICIENT")
HYP_OPS = ("add", "confirm", "challenge", "supersede")

# 供应商无关协议版本：供应商/SDK/模型名/凭据都不进入本层。
ADAPTER_PROTOCOL_VERSION = "battlefield.model-adapter/v1"
PACKAGE_SCHEMA_VERSION = "battlefield.task-package/v1"
OUTPUT_SCHEMA_VERSION = "battlefield.brain-output/v1"
MAX_OUTPUT_BYTES = 128 * 1024
MAX_HYPOTHESIS_OPS = 32
MAX_REFS = 64
MAX_TEXT_CHARS = 8_000
MAX_SHORT_TEXT_CHARS = 2_000
MAX_REF_CHARS = 256


class ModelUnavailable(Exception):
    """模型不可用/超时：系统结果，不是策略结论。"""


class ModelRateLimited(ModelUnavailable):
    """模型供应商限流。"""


class ModelNetworkError(ModelUnavailable):
    """模型调用网络失败。"""


class ModelAPIError(ModelUnavailable):
    """模型供应商 API 失败。"""


class StaleAssessment(Exception):
    """输出回显的 read_cursor 与快照不符：过期评估，丢弃不落盘。"""


class ModelContractError(ValueError):
    """输出违反契约（动作枚举/引用/字段）：契约错误，不落盘。"""


def adapter_model_id(adapter) -> str:
    return str(getattr(adapter, "model_id", None) or adapter.__class__.__name__)


def _provider_status_code(exc: BaseException) -> Optional[int]:
    for obj in (exc, getattr(exc, "response", None)):
        if obj is None:
            continue
        for attr in ("status_code", "status", "code"):
            value = getattr(obj, attr, None)
            if isinstance(value, int):
                return value
    return None


def invoke_adapter(adapter, package: dict) -> dict:
    """统一适配器调用边界：把可识别的供应商失败归一为 ModelUnavailable。

    未识别的普通异常不吞：那通常是适配器自身 bug，应在开发/测试阶段暴露；
    真实供应商桥接应把 SDK 异常翻译为 ModelUnavailable 的子类，或带 HTTP
    状态码交给这里归类。无论成功失败，这里都不记录请求头或凭据。
    """
    try:
        return adapter(package)
    except ModelUnavailable:
        raise
    except TimeoutError as exc:
        raise ModelUnavailable(f"模型调用超时: {exc}") from exc
    except (ConnectionError, OSError) as exc:
        raise ModelNetworkError(f"模型调用网络失败: {type(exc).__name__}: {exc}") from exc
    except Exception as exc:
        status = _provider_status_code(exc)
        if status == 429:
            raise ModelRateLimited(f"模型供应商限流: HTTP {status}") from exc
        if status == 408:
            raise ModelUnavailable(f"模型调用超时: HTTP {status}") from exc
        if status is not None and status >= 500:
            raise ModelAPIError(f"模型供应商 API 失败: HTTP {status}") from exc
        if "timeout" in exc.__class__.__name__.lower():
            raise ModelUnavailable(f"模型调用超时: {exc}") from exc
        raise


class RecordedAdapter:
    """录制回放适配器：按序返回预录输出（深拷贝），耗尽即 ModelUnavailable。"""

    model_id = "recorded"

    def __init__(self, outputs: List[dict], model_id: str = "recorded"):
        self._outputs = list(outputs)
        self.model_id = model_id

    def __call__(self, package: dict) -> dict:
        if not self._outputs:
            raise ModelUnavailable("录制输出已耗尽")
        return copy.deepcopy(self._outputs.pop(0))


class CallableAdapter:
    """把任意 package->output callable 包成统一协议适配器。"""

    def __init__(self, fn: Callable[[dict], dict], model_id: str = "callable"):
        self._fn = fn
        self.model_id = model_id

    def __call__(self, package: dict) -> dict:
        return invoke_adapter(self._fn, package)


class MockAdapter:
    """离线冒烟适配器：只证明输入/契约/落账链路，不冒充真实 AI 判读。"""

    model_id = "mock"

    def __call__(self, package: dict) -> dict:
        return {
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "read_cursor": package["snapshot_revision"],
            "action": "WATCH",
            "hypothesis_ops": [],
            "watch_plan": None,
            "candidate": None,
        }


def output_digest(output) -> str:
    try:
        raw = json.dumps(output, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str).encode("utf-8")
    except (TypeError, ValueError):
        raw = repr(output).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def output_summary(output) -> dict:
    """只留可观测摘要，不把模型全文复制进运行日志/状态索引。"""
    if not isinstance(output, dict):
        return {"type": type(output).__name__}
    hyp_ops = output.get("hypothesis_ops") or []
    return {
        "action": output.get("action"),
        "hypothesis_ops": len(hyp_ops) if isinstance(hyp_ops, list) else None,
        "has_watch_plan": output.get("watch_plan") is not None,
        "has_candidate": output.get("candidate") is not None,
        "digest": output_digest(output),
    }


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_GAP_RE = None
_T_RE = None
_CN_RE = None


def _check_test_labels(k, hyp_ops, plan, candidate) -> None:
    """测试编号一致性（用户 2026-10-31 点名）：简报文本里点名某缺口时，出现的
    T 编号与「第N次」必须属于该缺口的规范编号集——已发生的 1..test_count，
    加预告下一次 test_count+1。编号由事件（TEST_STARTED 的 test_index）生成，
    模型不许自由编写；越界即契约错误、整份不落盘。按句归属（多缺口同句从严）。"""
    import re
    global _GAP_RE, _T_RE, _CN_RE
    if _GAP_RE is None:
        _GAP_RE = re.compile(r"GAP-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
        _T_RE = re.compile(r"(?<![A-Za-z0-9])T(\d+)(?!\d)")
        _CN_RE = re.compile(r"第([一二三四五六七八九十])次")
    texts: list = []
    for op in hyp_ops or []:
        texts += [op.get("text") or "", op.get("reason") or ""]
    if plan:
        texts += [plan.get(f) or "" for f in
                  ("watch_level", "watch_behavior", "entry_trigger", "cancel_if")]
    if candidate:
        texts += [v for v in candidate.values() if isinstance(v, str)]
    allowed_by_gap = {gid: set(range(1, g.test_count + 2))
                      for gid, g in k.gaps.items()}
    for text in texts:
        for sent in re.split(r"[。；;！!？?\n]", text):
            mentioned = [g for g in _GAP_RE.findall(sent) if g in allowed_by_gap]
            if not mentioned:
                continue
            nums = [int(m) for m in _T_RE.findall(sent)]
            nums += [_CN_NUM[m] for m in _CN_RE.findall(sent)]
            for n in nums:
                for gid in mentioned:
                    if n not in allowed_by_gap[gid]:
                        raise ModelContractError(
                            f"测试编号越界: {gid} 已测 {len(allowed_by_gap[gid]) - 1} 次，"
                            f"合法编号 {sorted(allowed_by_gap[gid])}，文本写了 T{n}")

def _check_str(value, field: str, max_chars: int, *, required: bool = False) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str):
        raise ModelContractError(f"{field} 必须是字符串")
    if required and not value:
        raise ModelContractError(f"{field} 不能为空")
    if len(value) > max_chars:
        raise ModelContractError(f"{field} 超长: {len(value)} > {max_chars}")


def _check_ref_list(value, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ModelContractError(f"{field} 必须是数组")
    if len(value) > MAX_REFS:
        raise ModelContractError(f"{field} 数量超限: {len(value)} > {MAX_REFS}")
    for i, ref in enumerate(value):
        _check_str(ref, f"{field}[{i}]", MAX_REF_CHARS, required=True)


def _validate_output_schema(output) -> None:
    """输出结构/schema 校验：先于引用与业务语义，避免超长或错型输出进入落盘层。"""
    if not isinstance(output, dict):
        raise ModelContractError("输出必须是对象")
    try:
        raw = json.dumps(output, ensure_ascii=False, default=str).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ModelContractError(f"输出不可序列化: {exc}") from exc
    if len(raw) > MAX_OUTPUT_BYTES:
        raise ModelContractError(f"输出超大: {len(raw)} > {MAX_OUTPUT_BYTES} bytes")
    schema = output.get("schema_version")
    if schema is not None and schema != OUTPUT_SCHEMA_VERSION:
        raise ModelContractError(f"输出 schema_version 不符: {schema}")
    read_cursor = output.get("read_cursor")
    if not isinstance(read_cursor, int) or isinstance(read_cursor, bool):
        raise ModelContractError("read_cursor 必须是整数")
    _check_str(output.get("action"), "action", 64, required=True)

    hyp_ops = output.get("hypothesis_ops", [])
    if hyp_ops is None:
        hyp_ops = []
    if not isinstance(hyp_ops, list):
        raise ModelContractError("hypothesis_ops 必须是数组")
    if len(hyp_ops) > MAX_HYPOTHESIS_OPS:
        raise ModelContractError(
            f"hypothesis_ops 数量超限: {len(hyp_ops)} > {MAX_HYPOTHESIS_OPS}")
    for i, op in enumerate(hyp_ops):
        if not isinstance(op, dict):
            raise ModelContractError(f"hypothesis_ops[{i}] 必须是对象")
        _check_str(op.get("op"), f"hypothesis_ops[{i}].op", 32, required=True)
        _check_str(op.get("hyp_id"), f"hypothesis_ops[{i}].hyp_id", MAX_REF_CHARS)
        _check_str(op.get("text"), f"hypothesis_ops[{i}].text", MAX_TEXT_CHARS)
        _check_str(op.get("reason"), f"hypothesis_ops[{i}].reason", MAX_SHORT_TEXT_CHARS)
        _check_ref_list(op.get("support_refs", []), f"hypothesis_ops[{i}].support_refs")
        _check_ref_list(op.get("counter_refs", []), f"hypothesis_ops[{i}].counter_refs")

    plan = output.get("watch_plan")
    if plan is not None:
        if not isinstance(plan, dict):
            raise ModelContractError("watch_plan 必须是对象或 null")
        _check_str(plan.get("plan_id"), "watch_plan.plan_id", 64)
        for f in ("watch_level", "watch_behavior", "entry_trigger", "cancel_if"):
            _check_str(plan.get(f), f"watch_plan.{f}", MAX_TEXT_CHARS)
        _check_str(plan.get("watch_level"), "watch_plan.watch_level",
                   MAX_REF_CHARS, required=True)

    candidate = output.get("candidate")
    if candidate is not None:
        if not isinstance(candidate, dict):
            raise ModelContractError("candidate 必须是对象或 null")
        _check_ref_list(candidate.get("refs", []), "candidate.refs")
        for key, value in candidate.items():
            if isinstance(value, str):
                _check_str(value, f"candidate.{key}", MAX_TEXT_CHARS)


def _check_refs(kernel, refs) -> None:
    """引用核验：queries 的 ValueError 在大脑层统一转成契约错误。"""
    try:
        _validate_refs(kernel, refs)
    except ValueError as exc:
        raise ModelContractError(str(exc)) from exc


# ---------- 有界判读包预算（bounded/v1） ----------
# 根因纪律：账本是永久事实层，可以无限增长；判读包是每轮决策输入，必须
# 有界。完整 scene/累计事件不进默认包——历史走 history_summary 索引 +
# evidence 按 ID 取证；引用校验仍对全量账本执行，不因包精简而放松。
PKG_BARS = 96                 # 当前局面：最近 96 根
PKG_SIDE_EVENTS = 60          # 每侧最近行动事件
PKG_SIDE_SEGMENTS = 12        # 每侧最近段（另加全部 open 段）
PKG_CLOSED_GAPS = 24          # 最近关闭缺口（总数见 history_summary）
PKG_GAP_TESTS = 8             # 每座缺口保留的最近 tests
PKG_LEVELS_NEAR = 40          # 现价附近地形（另加全部开放缺口宿主 level）
PKG_CHANGES_EVENTS = 500      # 增量事件上限（生命周期事件优先）
PKG_CONCLUDED_HYPS = 12       # 历史摘要里的已结论假设
PACKAGE_MAX_BYTES = 1_000_000  # 包体硬预算（UTF-8 序列化）
_LIFECYCLE_TYPES = ("GAP_OPENED", "GAP_CLOSED", "TEST_STARTED", "TEST_ENDED")
_ACTIVE_HYP_STATUS = ("active", "challenged")
_ACTIVE_PLAN_STATUS = ("proposed", "active")


def _pkg_size(pkg: dict) -> int:
    return len(json.dumps(pkg, ensure_ascii=False, default=str).encode("utf-8"))


def _bar_ms(bar_id: str) -> int:
    try:
        return int(str(bar_id).rsplit("/", 1)[-1])
    except (TypeError, ValueError):
        return 0


def _trim_gap_tests(gap: dict, cap: int, omitted: list) -> dict:
    tests = gap.get("tests") or []
    if len(tests) <= cap:
        return gap
    omitted.append({"field": f"gap_tests:{gap.get('gap_id')}", "kept": cap,
                    "total": len(tests), "policy": "最近 tests 优先，总数见 test_count"})
    return {**gap, "tests": tests[-cap:], "tests_omitted": len(tests) - cap}


def _gap_event_index(repo) -> dict:
    """gap_id -> {opened_event_id, closed_event_id}（摘要追溯来源用）。"""
    idx: dict = {}
    for e in repo.kernel.events:
        gid = (e.payload or {}).get("gap_id")
        if not gid:
            continue
        slot = idx.setdefault(gid, {})
        if e.type == "GAP_OPENED":
            slot["opened_event_id"] = e.event_id
        elif e.type == "GAP_CLOSED":
            slot["closed_event_id"] = e.event_id
    return idx


def build_task_package(repo: InMemoryRepository, since_revision: int) -> dict:
    """组装单次判读的有界输入（bounded/v1）：当前局面（最近 96 根、当前
    有效地形、开放缺口、活跃假设/计划）+ 自 since_revision 的增量变化
    （有上限）+ 历史摘要索引。账本本体不进包；旧细节按 ID 走 evidence
    取证。每次裁剪都在 omitted 里留痕，不静默截断。"""
    token = make_token(repo)
    qs = QueryService(repo, token)
    k = repo.kernel
    last = k.bars[-1] if k.bars else None
    last_close = float(last.close) if last else None
    bars_all = qs.read_bars()

    caps = {"side_events": PKG_SIDE_EVENTS, "side_segments": PKG_SIDE_SEGMENTS,
            "closed_gaps": PKG_CLOSED_GAPS, "levels_near": PKG_LEVELS_NEAR,
            "changes_events": PKG_CHANGES_EVENTS}

    def assemble(caps: dict) -> dict:
        scene = qs.get_scene()
        omitted: list = []

        # --- 地形：开放缺口宿主 level 全保留 + 现价最近 levels_near 个 ---
        levels_all = scene["levels"]
        gap_level_keys = {g["level_key"] for g in scene["open_gaps"]}
        others = [lv for lv in levels_all if lv["level_key"] not in gap_level_keys]
        if last_close is not None:
            def _dist(lv):
                lo, hi = float(lv["lo"]), float(lv["hi"])
                return 0.0 if lo <= last_close <= hi else min(
                    abs(last_close - lo), abs(last_close - hi))
            others.sort(key=_dist)
        near_keys = {lv["level_key"] for lv in others[:caps["levels_near"]]}
        keep_keys = gap_level_keys | near_keys
        levels = [lv for lv in levels_all if lv["level_key"] in keep_keys]
        if len(levels) < len(levels_all):
            omitted.append({"field": "scene.levels", "kept": len(levels),
                            "total": len(levels_all),
                            "policy": "开放缺口宿主 + 现价最近优先，其余按 ID 取证"})
        contests_all = scene["contests"]
        contests = [c for c in contests_all if c["level_key"] in keep_keys]
        if len(contests) < len(contests_all):
            omitted.append({"field": "scene.contests", "kept": len(contests),
                            "total": len(contests_all),
                            "policy": "只留入选地形上的争夺记录"})

        # --- 缺口：开放全保留（tests 有界）；关闭只留最近若干 ---
        open_gaps = [_trim_gap_tests(g, PKG_GAP_TESTS, omitted)
                     for g in scene["open_gaps"]]
        closed_all = scene["just_closed_gaps"]
        closed_sorted = sorted(
            closed_all, key=lambda g: _bar_ms(g.get("closed_bar") or ""))
        closed = closed_sorted[-caps["closed_gaps"]:] if caps["closed_gaps"] else []
        closed = [_trim_gap_tests(g, PKG_GAP_TESTS, omitted) for g in closed]
        if len(closed) < len(closed_all):
            omitted.append({"field": "scene.just_closed_gaps", "kept": len(closed),
                            "total": len(closed_all),
                            "policy": "最近关闭优先，旧缺口生命周期见 history_summary"})

        # --- 双侧活动：事件/段只留最近，open 段全保留 ---
        sides = {}
        side_totals = {}
        for name in ("up", "down"):
            sa = qs.get_side_activity(name)
            evs_all, segs_all = sa["events"], sa["segments"]
            evs = evs_all[-caps["side_events"]:] if caps["side_events"] else []
            seg_tail = segs_all[-caps["side_segments"]:] if caps["side_segments"] else []
            seg_ids = {s["segment_id"] for s in seg_tail}
            merged = [(i, s) for i, s in enumerate(segs_all)
                      if s["segment_id"] in seg_ids or s.get("open")]
            merged.sort(key=lambda x: x[0])
            # open 段全保留但有硬顶：open 段随历史堆积时按最近优先封顶
            seg_hard_cap = min(60, caps["side_segments"] + 48)
            if len(merged) > seg_hard_cap:
                omitted.append({"field": f"sides.{name}.segments_open", "kept": seg_hard_cap,
                                "total": len(merged), "policy": "open 段过多，最近优先硬顶"})
                merged = merged[-seg_hard_cap:]
            segs = [s for _, s in merged]
            side_totals[name] = {"events": len(evs_all), "segments": len(segs_all)}
            if len(evs) < len(evs_all):
                omitted.append({"field": f"side_{name}.events", "kept": len(evs),
                                "total": len(evs_all), "policy": "最近优先，旧事件按 ID 取证"})
            if len(segs) < len(segs_all):
                omitted.append({"field": f"side_{name}.segments", "kept": len(segs),
                                "total": len(segs_all), "policy": "最近 + open 段优先"})
            sides[name] = {**sa, "events": evs, "segments": segs}
        da = scene.get("directional_activity") or {}
        da_slim = {name: {"segments_total": len(ids or []),
                          "recent_segment_ids": (ids or [])[-20:]}
                   for name, ids in da.items()}

        # --- 假设/计划：活跃进正文，已结论进摘要 ---
        hyps_all = k.hypotheses
        hyps_active = [h for h in hyps_all
                       if h.get("status") in _ACTIVE_HYP_STATUS]
        hyps_concluded = [h for h in hyps_all
                          if h.get("status") not in _ACTIVE_HYP_STATUS]
        plans_all = k.watch_plans
        plans_active = [p for p in plans_all
                        if p.get("status") in _ACTIVE_PLAN_STATUS]

        # --- 增量变化：生命周期事件优先，其余最近优先 ---
        changes_full = qs.get_changes(since_revision)
        evs = changes_full["events"]
        if len(evs) > caps["changes_events"]:
            life = [e for e in evs if e["type"] in _LIFECYCLE_TYPES]
            rest = [e for e in evs if e["type"] not in _LIFECYCLE_TYPES]
            keep_rest = rest[-(caps["changes_events"] - len(life)):] \
                if len(life) < caps["changes_events"] else []
            keep_ids = {id(e) for e in life + keep_rest}
            trimmed = [e for e in evs if id(e) in keep_ids]
            omitted.append({"field": "changes.events", "kept": len(trimmed),
                            "total": len(evs),
                            "policy": "生命周期事件全保留，其余最近优先"})
            changes = {**changes_full, "events": trimmed}
        else:
            changes = changes_full

        # --- 历史摘要：索引不是事实，带来源事件 ID 可追溯 ---
        ev_index = _gap_event_index(repo)
        closed_recent = []
        for g in closed_sorted[-PKG_CLOSED_GAPS:]:
            ids = ev_index.get(g["gap_id"], {})
            closed_recent.append({
                "gap_id": g["gap_id"], "level_key": g["level_key"],
                "direction": g["direction"], "anchor": str(g["anchor"]),
                "test_count": g["test_count"],
                "opened_bar": g.get("opened_bar"), "closed_bar": g.get("closed_bar"),
                "opened_event_id": ids.get("opened_event_id"),
                "closed_event_id": ids.get("closed_event_id"),
            })
        history_summary = {
            "ledger_revision": k.revision,
            "closed_gaps_total": len(closed_all),
            "closed_gaps_recent": closed_recent,
            "hypotheses_concluded_recent": [
                {"hyp_id": h.get("hyp_id"), "status": h.get("status"),
                 "text": (h.get("text") or "")[:200],
                 "superseded_by": h.get("superseded_by")}
                for h in hyps_concluded[-PKG_CONCLUDED_HYPS:]],
            "hypotheses_concluded_total": len(hyps_concluded),
            "levels_total": len(levels_all), "levels_included": len(levels),
            "contests_total": len(contests_all), "contests_included": len(contests),
            "side_events_total": {n: t["events"] for n, t in side_totals.items()},
            "segments_total": {n: t["segments"] for n, t in side_totals.items()},
            "watch_plans_total": len(plans_all),
            "note": ("摘要是索引不是事实：细节按 gap_id / level_key / ev- id "
                     "走 evidence 取证；引用校验对全量账本执行。"),
        }

        pkg_scene = {**scene, "levels": levels, "open_gaps": open_gaps,
                     "just_closed_gaps": closed, "contests": contests,
                     "directional_activity": da_slim,
                     "active_hypotheses": copy.deepcopy(hyps_active),
                     "watch_plans": copy.deepcopy(plans_active)}
        return {
            "schema_version": PACKAGE_SCHEMA_VERSION,
            "adapter_protocol": ADAPTER_PROTOCOL_VERSION,
            "output_schema_version": OUTPUT_SCHEMA_VERSION,
            "package_format": "bounded/v1",
            "token": token,
            "snapshot_revision": k.revision,
            "cursor": k.cursor,
            "ledger_revision": k.revision,
            "ledger_cursor": k.cursor,
            "last_bar": ({"open_time": last.open_time, "close_time": last.close_time,
                          "open": str(last.open), "high": str(last.high),
                          "low": str(last.low), "close": str(last.close)} if last else None),
            "bars": [{"t": b["open_time"], "o": b["open"], "h": b["high"],
                      "l": b["low"], "c": b["close"]}
                     for b in bars_all[-PKG_BARS:]],
            "scene": pkg_scene,
            "changes": changes,
            "side_up": sides["up"],
            "side_down": sides["down"],
            "hypotheses": copy.deepcopy(hyps_active),
            "watch_plans": copy.deepcopy(plans_active),
            "history_summary": history_summary,
            "omitted": omitted,
        }

    pkg = assemble(caps)
    size = _pkg_size(pkg)
    # 预算收紧阶梯：仍超限时逐级压活动事件/关闭缺口/地形/增量，并留痕
    tighten = [("side_events", 30), ("closed_gaps", 10), ("levels_near", 20),
               ("side_events", 12), ("changes_events", 200), ("levels_near", 10),
               ("side_segments", 6), ("changes_events", 80)]
    step = 0
    while size > PACKAGE_MAX_BYTES and step < len(tighten):
        field, value = tighten[step]
        step += 1
        if caps[field] <= value:
            continue
        caps[field] = value
        pkg = assemble(caps)
        size = _pkg_size(pkg)
    pkg["budget"] = {"max_bytes": PACKAGE_MAX_BYTES, "bytes": size,
                     "within_budget": size <= PACKAGE_MAX_BYTES,
                     "tighten_steps": step}
    return pkg


class BrainSession:
    """一个大脑的持续会话：持有 read cursor，逐次消费新事件并维护假设。"""

    def __init__(self, repo: InMemoryRepository, adapter):
        self.repo = repo
        self.adapter = adapter
        self.read_revision = 0          # 已消费到的状态 revision
        self.runs: List[dict] = []      # 每次运行的结果留痕（含系统结果）

    # ---------- 主入口 ----------
    def run_once(self) -> dict:
        package = build_task_package(self.repo, self.read_revision)
        model_id = adapter_model_id(self.adapter)
        try:
            output = invoke_adapter(self.adapter, package)
        except ModelUnavailable as exc:
            result = {"status": "model_unavailable", "detail": str(exc),
                      "snapshot_revision": package["snapshot_revision"],
                      "model_id": model_id,
                      "adapter_protocol": ADAPTER_PROTOCOL_VERSION}
            self.runs.append(result)
            return result
        try:
            applied = self._validate_and_apply(package, output)
        except StaleAssessment as exc:
            result = {"status": "stale", "detail": str(exc),
                      "snapshot_revision": package["snapshot_revision"],
                      "model_id": model_id,
                      "adapter_protocol": ADAPTER_PROTOCOL_VERSION,
                      "output_summary": output_summary(output)}
            self.runs.append(result)
            return result
        except ModelContractError as exc:
            result = {"status": "contract_error", "detail": str(exc),
                      "snapshot_revision": package["snapshot_revision"],
                      "model_id": model_id,
                      "adapter_protocol": ADAPTER_PROTOCOL_VERSION,
                      "output_summary": output_summary(output)}
            self.runs.append(result)
            return result
        self.read_revision = package["snapshot_revision"]
        result = {"status": "ok", "action": output.get("action"),
                  "snapshot_revision": package["snapshot_revision"],
                  "model_id": model_id,
                  "adapter_protocol": ADAPTER_PROTOCOL_VERSION,
                  "output_schema_version": output.get("schema_version")
                                           or OUTPUT_SCHEMA_VERSION,
                  "output_summary": output_summary(output), **applied}
        self.runs.append(result)
        return result

    # ---------- 校验后统一落盘 ----------
    def _validate_and_apply(self, package: dict, output) -> dict:
        k = self.repo.kernel
        _validate_output_schema(output)
        if output.get("read_cursor") != package["snapshot_revision"]:
            raise StaleAssessment(
                f"read_cursor={output.get('read_cursor')} != snapshot {package['snapshot_revision']}")
        action = output.get("action")
        if action not in ACTIONS:
            raise ModelContractError(f"动作不在枚举内: {action}")
        rev = package["snapshot_revision"]

        hyp_ops = output.get("hypothesis_ops") or []
        plan = output.get("watch_plan")
        candidate = output.get("candidate")

        # —— 先全量校验（假设操作按序校验：同批先 add 出的假设可被后续 op 引用） ——
        known_hyp_ids = {h.get("hyp_id") for h in k.hypotheses}
        planned = len(k.hypotheses)
        for op in hyp_ops:
            kind = op.get("op")
            if kind not in HYP_OPS:
                raise ModelContractError(f"假设操作不在枚举内: {kind}")
            if kind in ("confirm", "challenge", "supersede") \
                    and op.get("hyp_id") not in known_hyp_ids:
                raise ModelContractError(f"假设不存在: {op.get('hyp_id')}")
            if kind in ("add", "supersede"):
                if not op.get("text"):
                    raise ModelContractError("add/supersede 必须带 text")
                refs = list(op.get("support_refs", [])) + list(op.get("counter_refs", []))
                if not refs:
                    raise ModelContractError("新假设必须至少带一条可核验引用")
                _check_refs(k, refs)
                planned += 1
                known_hyp_ids.add(f"H{planned}")
        if plan is not None:
            for f in ("watch_level", "watch_behavior", "entry_trigger", "cancel_if"):
                if not plan.get(f):
                    raise ModelContractError(f"观察计划缺四段链字段: {f}")
            _check_refs(k, [plan["watch_level"]])
        if action == "PROPOSE_CANDIDATE":
            if not candidate:
                raise ModelContractError("PROPOSE_CANDIDATE 必须带 candidate")
            refs = list(candidate.get("refs", []))
            if not refs:
                raise ModelContractError("候选必须带可核验引用")
            _check_refs(k, refs)
        _check_test_labels(k, hyp_ops, plan, candidate)

        # —— 再统一落盘（只写提案分区） ——
        applied = {"hypotheses_changed": [], "watch_plan_added": None,
                   "candidate_proposed": None}
        for op in hyp_ops:
            applied["hypotheses_changed"].append(self._apply_hyp_op(op, rev))
        if plan is not None:
            entry = propose_watch_plan(self.repo, plan)
            applied["watch_plan_added"] = entry.get("plan_id") or "watch_plan"
        if action == "PROPOSE_CANDIDATE":
            entry = {"status": "proposed", "revision": rev, **copy.deepcopy(candidate)}
            k.candidate_proposals.append(entry)
            applied["candidate_proposed"] = entry
        return applied

    def _find_hyp(self, hyp_id: Optional[str]):
        for h in self.repo.kernel.hypotheses:
            if h.get("hyp_id") == hyp_id:
                return h
        return None

    def _apply_hyp_op(self, op: dict, rev: int) -> str:
        k = self.repo.kernel
        kind = op["op"]
        if kind in ("add", "supersede"):
            new_id = f"H{len(k.hypotheses) + 1}"
            entry = {"hyp_id": new_id, "kind": "hypothesis", "status": "active",
                     "text": op["text"],
                     "support_refs": list(op.get("support_refs", [])),
                     "counter_refs": list(op.get("counter_refs", [])),
                     "history": [{"revision": rev, "op": kind,
                                  "reason": op.get("reason", "")}]}
            if kind == "supersede":
                old = self._find_hyp(op["hyp_id"])
                old["status"] = "superseded"
                old["history"].append({"revision": rev, "op": "superseded_by",
                                       "by": new_id, "reason": op.get("reason", "")})
                entry["supersedes"] = op["hyp_id"]
            k.hypotheses.append(entry)
            return new_id
        hyp = self._find_hyp(op["hyp_id"])
        if kind == "challenge":
            hyp["status"] = "challenged"
        hyp["history"].append({"revision": rev, "op": kind,
                               "reason": op.get("reason", "")})
        return hyp["hyp_id"]
