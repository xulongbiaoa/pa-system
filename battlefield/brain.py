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


def build_task_package(repo: InMemoryRepository, since_revision: int) -> dict:
    """组装单次判读的完整输入：全局 scene + 局部 changes + 当前假设与计划。"""
    token = make_token(repo)
    qs = QueryService(repo, token)
    k = repo.kernel
    last = k.bars[-1] if k.bars else None
    return {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "adapter_protocol": ADAPTER_PROTOCOL_VERSION,
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "token": token,
        "snapshot_revision": k.revision,
        "cursor": k.cursor,
        "last_bar": ({"open_time": last.open_time, "close_time": last.close_time,
                      "open": str(last.open), "high": str(last.high),
                      "low": str(last.low), "close": str(last.close)} if last else None),
        "scene": qs.get_scene(),
        "changes": qs.get_changes(since_revision),
        "side_up": qs.get_side_activity("up"),
        "side_down": qs.get_side_activity("down"),
        "hypotheses": copy.deepcopy(k.hypotheses),
        "watch_plans": copy.deepcopy(k.watch_plans),
    }


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
