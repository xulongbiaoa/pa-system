"""网站滚动（沙盘线）。语义分两层（2026-11-01 plan-2 定版，取代 10-31 日内整窗）：

- **连续账本**（记忆层）：每标的 battlefield/shadow/<SYM>-15m/ 的 ShadowBook，
  只追加已收盘 Bar、跨窗跨天不截断；Brain cursor、假设、观察计划、候选
  与判读历史连续演化。缺根/修订/乱序显式报错，无新根不生成判读任务。
- **96 根视图**（观察层）：网站快照仍是最近 96 根 15m 的切片，由连续账本
  状态导出（export_24h.finalize_from_ledger），meta 带 ledger_revision /
  ledger_cursor；视图不承担持久记忆。

线上流程仍是 phase1 → 当值 agent 判读 → phase2，不接外部模型供应商。

用法：
  python3 -m battlefield.roll_site phase1
      双标的增量推进连续账本；有待判读时写出 package（data24/pkg_<SYM>.json），
      输出每标的状态（package_ready / up_to_date）
  python3 -m battlefield.roll_site phase2 <BTC判读.json|-> <ETH判读.json|->
      判读经 ShadowBook canonical 幂等落账 → 导出 96 根视图 → 上传；
      "-" 表示该标的本轮无待判读（只做未完成的导出/发布恢复）
  python3 -m battlefield.roll_site run-once --adapter mock [--no-publish]
      单次可重入闭环：窗口检查 → 模型 → 幂等落账 → 导出 → 发布。
      真实供应商经 --adapter-factory module:factory 注入（factory(config)
      返回一个 package->output callable 或适配器对象）；本仓库不绑定任何
      供应商 SDK、模型名或凭据。--adapter recorded --btc-output F --eth-output F
      可回放既有判读 JSON 做离线验收。
"""
from __future__ import annotations

import dataclasses
import importlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from battlefield import export_24h as e24
from battlefield.brain import (ADAPTER_PROTOCOL_VERSION, OUTPUT_SCHEMA_VERSION,
                               BrainSession, CallableAdapter, MockAdapter,
                               ModelUnavailable, RecordedAdapter,
                               adapter_model_id, build_task_package,
                               invoke_adapter, output_digest, output_summary)
from battlefield.feed import (FeedError, InputIncompleteError, fetch_closed_window,
                              fetch_klines, validate_closed_window,
                              window_input_hash)
from battlefield.runner import build_battlefield

OUT = e24.OUT
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TIMEFRAME = "15m"

ROLL_STATE_SCHEMA = "battlefield.roll-state/v1"
STAGE_NAMES = ("input", "model", "apply", "export", "publish")
FINAL_OK_STATUSES = ("completed", "no_new_bar")


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


# 连续账本目录：沿用既有 ShadowBook 账本位置（仓库根 shadow/<SYM>-15m，
# 2026-10-31 种子 1000 根 + 既有判读历史都在那里，不迁移、不丢历史）。
LEDGER_ROOT = os.path.join(e24.ROOT, "shadow")
FLOW_STATE_SCHEMA = "battlefield.flow-state/v1"


def _book(sym: str, ledger_root: str | None = None):
    from battlefield.shadow import ShadowBook
    return ShadowBook(os.path.join(ledger_root or LEDGER_ROOT, f"{sym}-15m"),
                      sym, TIMEFRAME, e24.TF_MS)


def _flow_path(book) -> str:
    return os.path.join(book.workdir, "flow_state.json")


def _read_flow(book) -> dict:
    path = _flow_path(book)
    if os.path.exists(path):
        try:
            flow = json.load(open(path))
            if isinstance(flow, dict) and flow.get("schema_version") == FLOW_STATE_SCHEMA:
                return flow
        except json.JSONDecodeError as exc:
            raise StateConsistencyError(f"flow_state 损坏: {path}: {exc}") from exc
    return {"schema_version": FLOW_STATE_SCHEMA, "symbol": book.symbol,
            "stages": {}, "last_apply": {}}


def _write_flow(book, flow: dict) -> None:
    flow["updated_at_ms"] = _now_ms()
    path = _flow_path(book)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(flow, f, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def _flow_stage(book, flow: dict, name: str, status: str, **extra) -> None:
    flow.setdefault("stages", {})[name] = {
        "status": status, "at_ms": _now_ms(), **extra}
    _write_flow(book, flow)


def phase1(fetcher=None, ledger_root: str | None = None) -> list:
    """连续账本推进：增量拉取 → 严格追加 → 有待判读则写出稳定 package。

    fetcher 可注入：(symbol, existing_bars) -> 新 Bar 列表（测试用）；
    默认 feed.fetch_incremental（以账本尾根为界，缺根/修订/乱序显式报错）。
    无新根或 Brain 已消费到最新 revision 时，该标的返回 up_to_date，
    不生成新判读任务；已生成未判读的 package 跨重启保持同一份（token 不变）。
    """
    from battlefield.feed import fetch_incremental
    from battlefield.queries import make_token

    results = []
    for sym in SYMBOLS:
        book = _book(sym, ledger_root)
        flow = _read_flow(book)
        existing = book._read_bars()
        try:
            new_bars = fetcher(sym, existing) if fetcher is not None \
                else fetch_incremental(sym, TIMEFRAME, existing, limit=1000)
            added = book.append_bars(new_bars) if new_bars else 0
        except Exception as exc:
            _flow_stage(book, flow, "input", "failed", detail=str(exc))
            raise
        bars_now = book._read_bars()
        last_close = bars_now[-1].close_time if bars_now else None
        _flow_stage(book, flow, "input", "completed", added_bars=added,
                    ledger_bars=len(bars_now), last_close_ms=last_close)
        repo, session, pkg = book.pending_package()
        if pkg is None:
            _flow_stage(book, flow, "package", "up_to_date",
                        revision=repo.kernel.revision)
            results.append({"symbol": sym, "status": "up_to_date",
                            "added_bars": added, "bars": len(bars_now),
                            "revision": repo.kernel.revision,
                            "brain_cursor": session.read_revision,
                            "token": make_token(repo)})
            continue
        pkg_path = os.path.join(e24.OUT, f"pkg_{sym}.json")
        os.makedirs(e24.OUT, exist_ok=True)
        with open(pkg_path, "w") as f:
            json.dump(pkg, f, ensure_ascii=False, default=str)
        with open(os.path.join(book.workdir, "pending_pkg.json"), "w") as f:
            json.dump(pkg, f, ensure_ascii=False, default=str)
        _flow_stage(book, flow, "package", "completed",
                    token=pkg["token"], snapshot_revision=pkg["snapshot_revision"],
                    read_cursor=session.read_revision, last_close_ms=last_close)
        results.append({"symbol": sym, "status": "package_ready",
                        "added_bars": added, "bars": len(bars_now),
                        "token": pkg["token"],
                        "snapshot_revision": pkg["snapshot_revision"],
                        "brain_cursor": session.read_revision,
                        "last_close_ms": last_close, "pkg": pkg_path})
    return results


def phase2(judge_files: dict, publisher=None, ledger_root: str | None = None) -> list:
    """判读落账（ShadowBook canonical 幂等）→ 导出 96 根视图 → 发布。

    恢复语义：同一判读文件（sha256）已落账则跳过 apply 直接续跑导出/发布；
    账本层另有 canonical 校验兜底（同 read_cursor 同输出复用、不同输出拒绝）。
    任一阶段失败：flow_state 记 failed 并抛错，下一轮同文件重跑从失败处续。
    judge_files 值为 "-" 或 None 的标的跳过 apply，只做导出/发布恢复检查。
    """
    import hashlib

    results = []
    for sym in SYMBOLS:
        book = _book(sym, ledger_root)
        flow = _read_flow(book)
        judge_path = judge_files.get(sym)
        skip_apply = judge_path in (None, "-")
        if not skip_apply:
            digest = hashlib.sha256(open(judge_path, "rb").read()).hexdigest()
            marker = flow.get("last_apply") or {}
            if marker.get("judge_sha256") == digest \
                    and marker.get("status") == "completed":
                _flow_stage(book, flow, "apply", "completed",
                            detail="flow marker 命中，不重复落账",
                            judge_sha256=digest)
            else:
                judge = json.load(open(judge_path))
                res = book.apply_output(judge)
                if res["status"] != "ok":
                    _flow_stage(book, flow, "apply", "failed",
                                detail=res.get("detail"), judge_sha256=digest)
                    raise RuntimeError(f"{sym} 判读落账失败: {res}")
                flow["last_apply"] = {"status": "completed",
                                      "judge_sha256": digest,
                                      "output_digest": res.get("output_digest"),
                                      "token": res.get("token"),
                                      "at_ms": _now_ms()}
                _flow_stage(book, flow, "apply", "completed",
                            judge_sha256=digest,
                            output_digest=res.get("output_digest"))
        try:
            snap = e24.finalize_from_ledger(sym, book)
        except Exception as exc:
            _flow_stage(book, flow, "export", "failed", detail=str(exc))
            raise
        _flow_stage(book, flow, "export", "completed",
                    token=snap["meta"]["token"],
                    ledger_revision=snap["meta"]["ledger_revision"])
        try:
            upload = publisher(sym) if publisher is not None else _upload(sym)
        except Exception as exc:
            _flow_stage(book, flow, "publish", "failed", detail=str(exc))
            raise
        _flow_stage(book, flow, "publish", "completed", detail=str(upload))
        results.append({"symbol": sym, "token": snap["meta"]["token"],
                        "ledger_revision": snap["meta"]["ledger_revision"],
                        "ledger_cursor": snap["meta"]["ledger_cursor"],
                        "open_gaps": len(snap["open_gaps"]),
                        "ai_stale": snap["meta"]["ai"]["stale"],
                        "upload": upload})
    return results


# =====================================================================
# run-once：可恢复单轮编排（实施方案《补完整实时输入到 AI 分析链路》）
#
# 状态文件 = OUT/run_state/<SYM>.json（原子替换写）。每窗一份状态，绑定
# 窗口 token + 输入指纹 + 输出摘要：同窗同输出重试只返回既有结果、不重复
# append；导出/发布失败后重跑从首个未完成阶段恢复，不再调用模型。
# 账本/状态不一致 = StateConsistencyError 显式停机，绝不静默跳过。
# =====================================================================


class StateConsistencyError(RuntimeError):
    """本地状态/账本互相矛盾：显式停止，不带病继续。"""


def _now_ms() -> int:
    return int(time.time() * 1000)


def _state_path(sym: str, state_dir: str | None = None) -> str:
    return os.path.join(state_dir or os.path.join(e24.OUT, "run_state"),
                        f"{sym}.json")


def _read_state(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise StateConsistencyError(f"滚动状态文件损坏: {path}: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema_version") != ROLL_STATE_SCHEMA:
        raise StateConsistencyError(f"滚动状态 schema 不符: {path}")
    return state


def _write_state(path: str, state: dict) -> None:
    state["updated_at_ms"] = _now_ms()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def _stage(state: dict, name: str) -> dict:
    return state["stages"].setdefault(name, {"status": "pending"})


def _begin_stage(state: dict, name: str, path: str) -> None:
    st = _stage(state, name)
    st["status"] = "running"
    st["started_at_ms"] = _now_ms()
    _write_state(path, state)


def _finish_stage(state: dict, name: str, status: str, path: str,
                  detail: str | None = None, **extra) -> None:
    st = _stage(state, name)
    st["status"] = status
    st["finished_at_ms"] = _now_ms()
    if "started_at_ms" in st:
        st["duration_ms"] = st["finished_at_ms"] - st["started_at_ms"]
    if detail is not None:
        st["detail"] = detail
    st.update(extra)
    _write_state(path, state)


def _write_bars(sym: str, bars) -> None:
    os.makedirs(e24.OUT, exist_ok=True)
    with open(os.path.join(e24.OUT, f"bars_{sym}.jsonl"), "w") as f:
        for b in bars:
            f.write(json.dumps(dataclasses.asdict(b), default=str) + "\n")


def _load_persisted_outputs(sym: str) -> list:
    path = os.path.join(e24.OUT, f"output_{sym}.json")
    if not os.path.exists(path):
        return []
    outputs = []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                outputs.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise StateConsistencyError(
                    f"{sym} 大脑输出账本第 {i} 行损坏: {exc}") from exc
    return outputs


def _window_meta(sym: str, bars, pkg: dict) -> dict:
    input_hash = window_input_hash(bars)
    return {
        "symbol": sym, "timeframe": TIMEFRAME,
        "token": pkg["token"], "revision": pkg["snapshot_revision"],
        "bars": len(bars),
        "start_open_ms": bars[0].open_time, "end_open_ms": bars[-1].open_time,
        "last_close_ms": bars[-1].close_time,
        "input_hash": input_hash,
        "idempotency_key": f"{sym}|{pkg['token']}|{input_hash}",
    }


def _result(sym: str, status: str, started: float, state: dict | None = None,
            detail: str | None = None, state_path: str | None = None) -> dict:
    out = {"symbol": sym, "status": status,
           "duration_ms": int((time.time() - started) * 1000)}
    if detail is not None:
        out["detail"] = detail
    if state is not None:
        window = state.get("window") or {}
        out["window"] = {k: window.get(k) for k in
                         ("token", "revision", "bars", "start_open_ms",
                          "end_open_ms", "last_close_ms", "input_hash")}
        out["token"] = window.get("token")
        out["revision"] = window.get("revision")
        model = (state.get("stages") or {}).get("model") or {}
        if model.get("model_id"):
            out["model_id"] = model["model_id"]
        out["stages"] = {name: (state.get("stages") or {}).get(name, {}).get("status")
                         for name in STAGE_NAMES}
        publish = (state.get("stages") or {}).get("publish") or {}
        if publish.get("status"):
            out["publish_status"] = publish["status"]
    if state_path is not None:
        out["state_path"] = state_path
    return out


def run_once_symbol(sym: str, adapter, *, window_fetcher=None, publisher=None,
                    publish: bool = True, state_dir: str | None = None) -> dict:
    """单标的单轮闭环。adapter 为 package->output 的适配器/callable。

    window_fetcher: 可注入的 (symbol)->List[Bar]，默认走 feed.fetch_closed_window。
    publisher: 可注入的 (symbol)->str，默认沿用现有 R2 上传 _upload。
    """
    started = time.time()
    path = _state_path(sym, state_dir)
    state = _read_state(path)

    # ---------- 1. 输入窗口 ----------
    try:
        raw_bars = window_fetcher(sym) if window_fetcher is not None \
            else fetch_closed_window(sym, TIMEFRAME, e24.BARS_N)
        bars = validate_closed_window(raw_bars, sym, TIMEFRAME,
                                      expected_count=e24.BARS_N,
                                      timeframe_ms=e24.TF_MS)
    except FeedError as exc:
        return _result(sym, "feed_error", started, state, str(exc), path)
    except InputIncompleteError as exc:
        return _result(sym, "input_incomplete", started, state, str(exc), path)

    input_hash = window_input_hash(bars)
    last_close = bars[-1].close_time
    same_window = bool(state and state.get("window")
                       and state["window"].get("input_hash") == input_hash)
    if state and not same_window and state.get("window") \
            and state["window"].get("last_close_ms") == last_close:
        raise StateConsistencyError(
            f"{sym} 同一收盘根但输入指纹变化（数据修订冲突），显式停机")
    if state and not same_window \
            and (state.get("window") or {}).get("last_close_ms", -1) >= last_close:
        return _result(sym, "no_new_bar", started, state,
                       "最新已收盘根未超过已处理窗口", path)
    if same_window and state.get("status") == "completed":
        return _result(sym, "no_new_bar", started, state,
                       "本窗已完整处理", path)

    if same_window:
        # 恢复：输入以已持久化 bars 为准，核对与本次抓取一致
        persisted = e24._load_bars(sym)
        if window_input_hash(persisted) != input_hash:
            raise StateConsistencyError(f"{sym} 已持久化 bars 与状态指纹不符")
        bars = persisted
        repo = build_battlefield(sym, TIMEFRAME, e24.TF_MS, bars)
        pkg = build_task_package(repo, 0)
        if pkg["token"] != state["window"]["token"]:
            raise StateConsistencyError(
                f"{sym} 恢复重建 token 漂移: {pkg['token']} != {state['window']['token']}")
    else:
        _write_bars(sym, bars)
        repo = build_battlefield(sym, TIMEFRAME, e24.TF_MS, bars)
        pkg = build_task_package(repo, 0)
        previous = None
        if state and state.get("window"):
            w = state["window"]
            previous = {"token": w.get("token"),
                        "last_close_ms": w.get("last_close_ms"),
                        "status": state.get("status")}
        state = {
            "schema_version": ROLL_STATE_SCHEMA,
            "symbol": sym, "timeframe": TIMEFRAME, "status": "running",
            "created_at_ms": _now_ms(), "updated_at_ms": _now_ms(),
            "window": _window_meta(sym, bars, pkg),
            "previous_window": previous,
            "stages": {name: {"status": "pending"} for name in STAGE_NAMES},
        }
        _finish_stage(state, "input", "completed", path,
                      detail="96 根已收盘、连续、边界正确",
                      input_hash=input_hash)
        with open(os.path.join(e24.OUT, f"pkg_{sym}.json"), "w") as f:
            json.dump(pkg, f, ensure_ascii=False, default=str)

    # ---------- 2. 模型 ----------
    model_stage = _stage(state, "model")
    if model_stage.get("status") == "completed" and "output" in model_stage:
        output = model_stage["output"]
    else:
        _begin_stage(state, "model", path)
        try:
            output = invoke_adapter(adapter, pkg)
        except ModelUnavailable as exc:
            _finish_stage(state, "model", "failed", path, detail=str(exc),
                          result_status="model_unavailable",
                          model_id=adapter_model_id(adapter),
                          adapter_protocol=ADAPTER_PROTOCOL_VERSION)
            state["status"] = "model_unavailable"
            _write_state(path, state)
            return _result(sym, "model_unavailable", started, state, str(exc), path)
        try:
            json.dumps(output, ensure_ascii=False)
            stored_output = output
        except (TypeError, ValueError):
            stored_output = None
        _finish_stage(state, "model", "completed", path,
                      model_id=adapter_model_id(adapter),
                      adapter_protocol=ADAPTER_PROTOCOL_VERSION,
                      package_schema=pkg.get("schema_version"),
                      output_schema_version=OUTPUT_SCHEMA_VERSION,
                      output_digest=output_digest(output),
                      output_summary=output_summary(output),
                      output=stored_output)
        if stored_output is None:
            state["status"] = "contract_error"
            _write_state(path, state)
            return _result(sym, "contract_error", started, state,
                           "模型输出不可 JSON 序列化，无法持久化", path)

    # ---------- 3. 幂等落账 ----------
    apply_stage = _stage(state, "apply")
    digest = output_digest(output)
    if apply_stage.get("status") == "completed":
        digests = [output_digest(o) for o in _load_persisted_outputs(sym)]
        if digest not in digests:
            raise StateConsistencyError(
                f"{sym} 状态记为已落账，但 output 账本缺该输出，显式停机")
    else:
        _begin_stage(state, "apply", path)
        digests = [output_digest(o) for o in _load_persisted_outputs(sym)]
        if digest in digests:
            _finish_stage(state, "apply", "completed", path,
                          detail="输出已在账本中（崩溃恢复），不重复 append",
                          output_digest=digest)
        else:
            try:
                res = e24.apply_output(sym, output)
            except RuntimeError as exc:
                _finish_stage(state, "apply", "failed", path, detail=str(exc))
                raise StateConsistencyError(str(exc)) from exc
            if res["status"] != "ok":
                status = res["status"] if res["status"] in (
                    "stale", "contract_error", "model_unavailable") else "contract_error"
                _finish_stage(state, "apply", "failed", path,
                              detail=res.get("detail"), result_status=status)
                state["status"] = status
                _write_state(path, state)
                return _result(sym, status, started, state,
                               res.get("detail"), path)
            _finish_stage(state, "apply", "completed", path,
                          detail="BrainSession 契约校验通过并已 append",
                          output_digest=digest,
                          action=res.get("action"),
                          snapshot_revision=res.get("snapshot_revision"))

    # ---------- 4. 导出 ----------
    export_stage = _stage(state, "export")
    snap_path = os.path.join(e24.OUT, f"{sym}.json")
    export_ok = False
    if export_stage.get("status") == "completed" and os.path.exists(snap_path):
        snap = json.load(open(snap_path))
        export_ok = snap.get("meta", {}).get("token") == state["window"]["token"]
    if not export_ok:
        _begin_stage(state, "export", path)
        try:
            e24.finalize(sym)
            snap = json.load(open(snap_path))
            if snap.get("meta", {}).get("token") != state["window"]["token"]:
                raise RuntimeError("快照 token 与本窗不一致")
            if snap.get("meta", {}).get("bars_count") != e24.BARS_N:
                raise RuntimeError("快照 bars_count 与本窗不一致")
        except Exception as exc:
            _finish_stage(state, "export", "failed", path, detail=str(exc))
            state["status"] = "export_error"
            _write_state(path, state)
            return _result(sym, "export_error", started, state, str(exc), path)
        _finish_stage(state, "export", "completed", path,
                      snapshot_path=snap_path,
                      snapshot_bytes=os.path.getsize(snap_path),
                      snapshot_token=snap["meta"]["token"],
                      open_gaps=len(snap.get("open_gaps") or []))

    # ---------- 5. 发布 ----------
    publish_stage = _stage(state, "publish")
    if not publish:
        if publish_stage.get("status") != "skipped":
            _finish_stage(state, "publish", "skipped", path,
                          detail="本轮禁用发布（离线/验收模式）")
    elif publish_stage.get("status") != "completed":
        _begin_stage(state, "publish", path)
        try:
            detail = publisher(sym) if publisher is not None else _upload(sym)
        except Exception as exc:
            _finish_stage(state, "publish", "failed", path, detail=str(exc))
            state["status"] = "publish_error"
            _write_state(path, state)
            return _result(sym, "publish_error", started, state, str(exc), path)
        _finish_stage(state, "publish", "completed", path, detail=str(detail))

    state["status"] = "completed"
    _write_state(path, state)
    return _result(sym, "completed", started, state, state_path=path)


def run_once(symbols=SYMBOLS, adapter=None, **kwargs) -> list:
    """多标的顺序单轮：一个标的失败不挡另一个标的出结果。"""
    if adapter is None:
        adapter = MockAdapter()
    return [run_once_symbol(sym, adapter, **kwargs) for sym in symbols]


def _load_adapter_factory(spec: str, config_json: str | None):
    module_name, sep, attr = spec.partition(":")
    if not sep or not module_name or not attr:
        raise SystemExit("--adapter-factory 格式应为 module:factory")
    factory = getattr(importlib.import_module(module_name), attr)
    config = json.loads(config_json) if config_json else {}
    adapter = factory(config)
    if not hasattr(adapter, "__call__"):
        raise SystemExit("adapter factory 返回值不可调用")
    model_id = getattr(adapter, "model_id", None) or spec
    return adapter if hasattr(adapter, "model_id") else CallableAdapter(adapter, model_id=model_id)


def _run_once_cli(argv) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="roll_site run-once")
    parser.add_argument("--adapter", choices=("mock", "recorded", "factory"),
                        default="mock")
    parser.add_argument("--adapter-factory", help="module:factory，factory(config) 返回适配器")
    parser.add_argument("--adapter-config-json", help="传给 factory 的 JSON 配置（不含凭据也可）")
    parser.add_argument("--btc-output", help="recorded 模式：BTCUSDT 判读 JSON 文件")
    parser.add_argument("--eth-output", help="recorded 模式：ETHUSDT 判读 JSON 文件")
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--state-dir")
    args = parser.parse_args(argv)
    publish = not args.no_publish
    if args.adapter == "recorded":
        files = {"BTCUSDT": args.btc_output, "ETHUSDT": args.eth_output}
        if not all(files.values()):
            parser.error("recorded 模式需要 --btc-output 与 --eth-output")
        results = [run_once_symbol(sym, RecordedAdapter([json.load(open(files[sym]))]),
                                   publish=publish, state_dir=args.state_dir)
                   for sym in SYMBOLS]
    else:
        adapter = MockAdapter() if args.adapter == "mock" else None
        if args.adapter == "factory":
            if not args.adapter_factory:
                parser.error("factory 模式需要 --adapter-factory module:factory")
            adapter = _load_adapter_factory(args.adapter_factory,
                                            args.adapter_config_json)
        results = run_once(adapter=adapter, publish=publish,
                           state_dir=args.state_dir)
    print(json.dumps(results, ensure_ascii=False))
    return 0 if all(r["status"] in FINAL_OK_STATUSES for r in results) else 2


def main(argv) -> int:
    if argv and argv[0] == "run-once":
        return _run_once_cli(argv[1:])
    if argv and argv[0] == "phase1":
        print(json.dumps(phase1(), ensure_ascii=False))
        return 0
    if argv and argv[0] == "phase2":
        print(json.dumps(phase2({"BTCUSDT": argv[1], "ETHUSDT": argv[2]}),
                         ensure_ascii=False))
        return 0
    raise SystemExit("usage: roll_site phase1 | phase2 <btc.json> <eth.json> | "
                     "run-once [--adapter mock|recorded|factory] [--no-publish]")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
