"""run-once 编排测试：窗口→模型→幂等落账→导出→发布，全程离线注入。

覆盖实施方案的幂等与故障恢复口径：
- 同窗同输入同输出只落账一次，重跑返回 no_new_bar 且不重复调用模型；
- 发布/导出失败后重跑从失败阶段恢复，模型不重复调用、账不重复 append；
- 模型不可用不落账、同窗可重试；契约错误不落账且不靠重跑偷换输出；
- 输入不完整直接 input_incomplete，不建战场、不写状态。
"""
import json
import os

import pytest

from battlefield import export_24h as e24
from battlefield import roll_site
from battlefield.brain import ModelUnavailable
from battlefield.contracts import make_bar

TF_MS = 900_000
BASE = 1_700_000_100_000
SYM = "BTCUSDT"


def _bars(n=96, start=BASE):
    bars = []
    price = 100.0
    for i in range(n):
        # 10 根一折的锯齿：足够产生 swing 地形与 level 引用
        drift = 0.6 if (i // 10) % 2 == 0 else -0.6
        o = price
        c = price + drift
        # 转折根的影线极值必须严格大于/小于相邻根（摆动确认用严格比较）
        h = max(o, c) + (0.4 if drift > 0 else 0.2)
        l = min(o, c) - (0.2 if drift > 0 else 0.4)
        bars.append(make_bar(SYM, "15m", start + i * TF_MS,
                             start + i * TF_MS + TF_MS - 1,
                             f"{o:.2f}", f"{h:.2f}", f"{l:.2f}", f"{c:.2f}",
                             source="binance-vision",
                             received_at=start + (i + 1) * TF_MS))
        price = c
    return bars


class CountingAdapter:
    model_id = "counting-test"

    def __init__(self, mode="ok"):
        self.calls = 0
        self.mode = mode

    def __call__(self, pkg):
        self.calls += 1
        if self.mode == "unavailable":
            raise ModelUnavailable("provider down")
        if self.mode == "stale":
            return {"read_cursor": 999999, "action": "WATCH"}
        if self.mode == "bad_ref":
            return {"read_cursor": pkg["snapshot_revision"], "action": "WATCH",
                    "hypothesis_ops": [{"op": "add", "text": "伪造引用",
                                        "support_refs": ["GAP-NOPE-1"]}]}
        level = pkg["scene"]["levels"][0]["level_key"]
        return {"read_cursor": pkg["snapshot_revision"], "action": "WAIT_BEHAVIOR",
                "hypothesis_ops": [],
                "watch_plan": {"plan_id": "WP1", "watch_level": level,
                               "watch_behavior": "等回补测试",
                               "entry_trigger": "测试收官后复核",
                               "cancel_if": "窗口滚动"},
                "candidate": None}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    out = tmp_path / "data24"
    out.mkdir()
    monkeypatch.setattr(e24, "OUT", str(out))
    state_dir = str(tmp_path / "state")
    bars = _bars()
    published = []
    return {"out": out, "state_dir": state_dir, "bars": bars,
            "fetcher": lambda sym: bars,
            "publisher": lambda sym: published.append(sym) or "uploaded",
            "published": published}


def _run(env, adapter, **kw):
    kw.setdefault("window_fetcher", env["fetcher"])
    kw.setdefault("publisher", env["publisher"])
    kw.setdefault("state_dir", env["state_dir"])
    return roll_site.run_once_symbol(SYM, adapter, **kw)


def _output_lines(env):
    path = env["out"] / f"output_{SYM}.json"
    if not path.exists():
        return []
    return [l for l in path.read_text().splitlines() if l.strip()]


def test_run_once_completed_then_no_new_bar(env):
    ad = CountingAdapter()
    r1 = _run(env, ad)
    assert r1["status"] == "completed", r1
    assert r1["stages"] == {"input": "completed", "model": "completed",
                            "apply": "completed", "export": "completed",
                            "publish": "completed"}
    assert ad.calls == 1 and env["published"] == [SYM]
    assert len(_output_lines(env)) == 1
    snap = json.loads((env["out"] / f"{SYM}.json").read_text())
    assert snap["meta"]["token"] == r1["token"]
    assert snap["watch_plans"], "观察计划应随快照导出"

    r2 = _run(env, ad)
    assert r2["status"] == "no_new_bar"
    assert ad.calls == 1 and len(_output_lines(env)) == 1
    assert env["published"] == [SYM]  # 没重复发布


def test_run_once_publish_failure_recovers_without_model_recall(env):
    ad = CountingAdapter()
    calls = {"n": 0}

    def bad_publisher(sym):
        calls["n"] += 1
        raise RuntimeError("R2 down")

    r1 = _run(env, ad, publisher=bad_publisher)
    assert r1["status"] == "publish_error" and calls["n"] == 1
    r2 = _run(env, ad)
    assert r2["status"] == "completed"
    assert ad.calls == 1, "恢复不得重复调用模型"
    assert len(_output_lines(env)) == 1, "恢复不得重复 append"


def test_run_once_export_failure_recovers(env, monkeypatch):
    ad = CountingAdapter()
    original = e24.finalize
    state = {"failed": False}

    def flaky(sym, **kw):
        if not state["failed"]:
            state["failed"] = True
            raise RuntimeError("export boom")
        return original(sym, **kw)

    monkeypatch.setattr(e24, "finalize", flaky)
    r1 = _run(env, ad)
    assert r1["status"] == "export_error"
    r2 = _run(env, ad)
    assert r2["status"] == "completed" and ad.calls == 1
    assert len(_output_lines(env)) == 1


def test_run_once_model_unavailable_then_retry(env):
    ad = CountingAdapter(mode="unavailable")
    r1 = _run(env, ad)
    assert r1["status"] == "model_unavailable"
    assert _output_lines(env) == []
    ad.mode = "ok"
    r2 = _run(env, ad)
    assert r2["status"] == "completed" and ad.calls == 2
    assert len(_output_lines(env)) == 1


def test_run_once_contract_error_not_persisted_and_sticky(env):
    ad = CountingAdapter(mode="bad_ref")
    r1 = _run(env, ad)
    assert r1["status"] == "contract_error"
    assert _output_lines(env) == []
    r2 = _run(env, ad)
    assert r2["status"] == "contract_error"
    assert ad.calls == 1, "已持久化的模型输出不得靠重跑偷换"


def test_run_once_stale_output(env):
    ad = CountingAdapter(mode="stale")
    r = _run(env, ad)
    assert r["status"] == "stale" and _output_lines(env) == []


def test_run_once_input_incomplete(env):
    ad = CountingAdapter()
    r = _run(env, ad, window_fetcher=lambda sym: env["bars"][:95])
    assert r["status"] == "input_incomplete"
    assert ad.calls == 0
    assert not (env["out"] / f"bars_{SYM}.jsonl").exists()


def test_run_once_new_window_rebuilds(env):
    ad = CountingAdapter()
    r1 = _run(env, ad)
    assert r1["status"] == "completed"
    bars2 = _bars(96, start=BASE + TF_MS)  # 整体后移一根 = 新窗
    r2 = _run(env, ad, window_fetcher=lambda sym: bars2)
    assert r2["status"] == "completed" and r2["token"] != r1["token"]
    assert ad.calls == 2
    with open(os.path.join(env["state_dir"], f"{SYM}.json")) as f:
        state = json.load(f)
    assert state["previous_window"]["token"] == r1["token"]
