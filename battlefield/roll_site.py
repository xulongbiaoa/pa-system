"""网站日内滚动（沙盘 data24 线，用户 2026-10-31 定版：做日内，不做连续全局账本）。

语义：每一轮 = 一个全新的日内战场——抓最近 96 根已收盘 15m（24h）整窗重建，
状态只来自本窗，上一窗的账与简报全部作废（全局信息不进日内盘）。简报每轮由
当值判读基于本窗状态包从零写（read_cursor = 本窗 revision），落账后导出并
上传 R2 sandbox/data24/，线上沙盘轮询读取。

用法：
  python3 -m battlefield.roll_site phase1
      双标的抓数建场（覆盖 bars/pkg，清空旧输出），输出两份包的路径与摘要
  python3 -m battlefield.roll_site phase2 <BTC判读.json> <ETH判读.json>
      两份判读落账 → finalize → 上传，输出 JSON 状态（人工应急入口，保留）
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
        marker_path = os.path.join(OUT, f"applied_{sym}.json")
        if os.path.exists(marker_path):
            os.remove(marker_path)
        repo = e24.build_battlefield(sym, "15m", e24.TF_MS, bars)
        session = BrainSession(repo, RecordedAdapter([]))
        pkg = build_task_package(repo, session.read_revision)
        pkg_path = os.path.join(OUT, f"pkg_{sym}.json")
        json.dump(pkg, open(pkg_path, "w"), ensure_ascii=False, default=str)
        results.append({"symbol": sym, "bars": len(bars), "token": pkg["token"],
                        "pkg": pkg_path})
    return results


def phase2(judge_files: dict) -> list:
    """幂等：同一窗同一份判读文件只落账一次（2026-10-31 21:15 轮教训：首跑
    BTC 已落账、ETH 被拒后整批重跑，BTC 被追加了第二份，造成快照重复条目）。"""
    import hashlib
    results = []
    for sym in SYMBOLS:
        judge_path = judge_files[sym]
        digest = hashlib.sha256(open(judge_path, "rb").read()).hexdigest()
        pkg = json.load(open(os.path.join(OUT, f"pkg_{sym}.json")))
        marker_path = os.path.join(OUT, f"applied_{sym}.json")
        marker = json.load(open(marker_path)) if os.path.exists(marker_path) else {}
        if marker.get("judge_sha256") == digest and marker.get("token") == pkg["token"]:
            pass  # 本窗本文件已落过账：跳过 apply，只重建快照
        else:
            e24.apply(sym, judge_path)
            json.dump({"judge_sha256": digest, "token": pkg["token"]},
                      open(marker_path, "w"))
        e24.finalize(sym)
        snap = json.load(open(os.path.join(OUT, f"{sym}.json")))
        results.append({"symbol": sym, "token": snap["meta"]["token"],
                        "open_gaps": len(snap["open_gaps"]),
                        "ai_stale": snap["meta"]["ai"]["stale"],
                        "upload": _upload(sym)})
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
