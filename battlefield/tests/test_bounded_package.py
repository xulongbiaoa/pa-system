"""有界判读包验收（用户口径：全量账本 + 有界判读包 + 按需查历史）。

- 账本跨多个窗口后 package 大小仍有上限，裁剪必留痕（omitted）；
- 历史摘要可追溯：closed_gaps_recent 的来源事件 ID 必须真实存在于账本；
- 旧证据仍可按 ID 查询（QueryService.inspect_evidence / evidence CLI）；
- 引用校验对全量账本执行：包里被裁掉的旧 level 仍可合法引用；
- build_task_package 是只读的：调用前后重放状态不变。
"""
import json
import subprocess
import sys

import pytest

from battlefield.brain import (PACKAGE_MAX_BYTES, BrainSession, RecordedAdapter,
                               build_task_package)
from battlefield.contracts import make_bar
from battlefield.queries import QueryService, make_token
from battlefield.runner import build_battlefield
from battlefield.shadow import ShadowBook

TF_MS = 900_000
BASE = 1_700_000_100_000


def _bars(sym, n, start=BASE):
    # 阶梯行情（涨腿强于跌腿）：会真实产生突破缺口的开/关账，
    # 对称锯齿在等高点上永远整根分离不了、立不了账（已实测）。
    bars = []
    price = 100.0
    for i in range(n):
        drift = 1.2 if (i // 10) % 2 == 0 else -0.8
        o = price
        c = price + drift
        h = max(o, c) + (0.4 if drift > 0 else 0.2)
        l = min(o, c) - (0.2 if drift > 0 else 0.4)
        bars.append(make_bar(sym, "15m", start + i * TF_MS,
                             start + i * TF_MS + TF_MS - 1,
                             f"{o:.2f}", f"{h:.2f}", f"{l:.2f}", f"{c:.2f}",
                             source="binance-vision",
                             received_at=start + (i + 1) * TF_MS))
        price = c
    return bars


def _pkg_bytes(pkg):
    return len(json.dumps(pkg, ensure_ascii=False, default=str).encode())


def test_package_bounded_as_ledger_grows():
    repo200 = build_battlefield("BTCUSDT", "15m", TF_MS, _bars("BTCUSDT", 200))
    repo400 = build_battlefield("BTCUSDT", "15m", TF_MS, _bars("BTCUSDT", 400))
    pkg200 = build_task_package(repo200, 0)
    pkg400 = build_task_package(repo400, 0)
    for pkg in (pkg200, pkg400):
        assert pkg["package_format"] == "bounded/v1"
        assert _pkg_bytes(pkg) <= PACKAGE_MAX_BYTES
        assert pkg["budget"]["within_budget"] is True
        assert len(pkg["bars"]) == 192
    # 账本翻倍，包不许近似同比膨胀
    assert _pkg_bytes(pkg400) < _pkg_bytes(pkg200) * 1.6
    assert pkg400["omitted"], "大账本必然发生裁剪，且必须留痕"
    fields = {o["field"] for o in pkg400["omitted"]}
    assert any("levels" in f or "events" in f for f in fields)
    hs = pkg400["history_summary"]
    assert hs["levels_total"] > hs["levels_included"]
    assert hs["closed_gaps_total"] >= len(hs["closed_gaps_recent"])


def test_history_summary_traceable_to_events():
    repo = build_battlefield("BTCUSDT", "15m", TF_MS, _bars("BTCUSDT", 400))
    pkg = build_task_package(repo, 0)
    event_ids = {e.event_id for e in repo.kernel.events}
    recent = pkg["history_summary"]["closed_gaps_recent"]
    assert recent, "400 根回放应有关闭缺口可摘要"
    for entry in recent:
        if entry["opened_event_id"]:
            assert entry["opened_event_id"] in event_ids
        if entry["closed_event_id"]:
            assert entry["closed_event_id"] in event_ids


def test_old_evidence_queryable_and_package_readonly():
    repo = build_battlefield("BTCUSDT", "15m", TF_MS, _bars("BTCUSDT", 400))
    qs = QueryService(repo, make_token(repo))
    scene = qs.get_scene()
    assert scene["just_closed_gaps"], "需要至少一座已关闭缺口作旧证据样本"
    old_gap = scene["just_closed_gaps"][0]["gap_id"]

    def state_digest():
        s = qs.get_scene()
        return (s["revision"], len(repo.kernel.events),
                len(s["levels"]), len(s["open_gaps"]))

    before = state_digest()
    build_task_package(repo, 0)
    assert state_digest() == before, "组包不得改变账本状态（重放结果不变）"

    ev = qs.inspect_evidence(old_gap)
    assert ev["object"]["gap_id"] == old_gap
    assert ev["bars"], "旧缺口的原始 Bar 证据链必须还在"
    with pytest.raises(ValueError):
        qs.inspect_evidence("GAP-NOPE-0-0")


def test_refs_validated_against_full_ledger_not_package():
    repo = build_battlefield("BTCUSDT", "15m", TF_MS, _bars("BTCUSDT", 400))
    pkg = build_task_package(repo, 0)
    in_pkg = {lv["level_key"] for lv in pkg["scene"]["levels"]}
    qs = QueryService(repo, make_token(repo))
    all_keys = [lv["level_key"] for lv in qs.get_scene()["levels"]]
    trimmed = [k for k in all_keys if k not in in_pkg]
    assert trimmed, "400 根账本应有 level 被裁出包外"
    out = {"read_cursor": pkg["snapshot_revision"], "action": "WAIT_BEHAVIOR",
           "hypothesis_ops": [{"op": "add", "text": "引用包外旧地形",
                               "support_refs": [trimmed[0]], "counter_refs": []}],
           "watch_plan": None, "candidate": None}
    session = BrainSession(repo, RecordedAdapter([out]))
    result = session.run_once()
    assert result["status"] == "ok", "包外旧 level 的引用必须仍合法（全量校验）"


def test_concluded_hypotheses_move_to_summary():
    bars = _bars("BTCUSDT", 60)
    repo = build_battlefield("BTCUSDT", "15m", TF_MS, bars[:30])
    level = QueryService(repo, make_token(repo)).get_scene()["levels"][0]["level_key"]
    out1 = {"read_cursor": 30, "action": "WAIT_BEHAVIOR",
            "hypothesis_ops": [{"op": "add", "text": "第一代假设",
                                "support_refs": [level], "counter_refs": []}],
            "watch_plan": None, "candidate": None}
    session = BrainSession(repo, RecordedAdapter([out1]))
    assert session.run_once()["status"] == "ok"
    for b in bars[30:]:
        repo.commit_bar(b)
    pkg_mid = build_task_package(repo, session.read_revision)
    hyp_id = pkg_mid["hypotheses"][0]["hyp_id"]
    out2 = {"read_cursor": 60, "action": "WAIT_BEHAVIOR",
            "hypothesis_ops": [{"op": "supersede", "hyp_id": hyp_id,
                                "text": "第二代假设接管",
                                "support_refs": [level], "counter_refs": []}],
            "watch_plan": None, "candidate": None}
    session.adapter = RecordedAdapter([out2])
    assert session.run_once()["status"] == "ok"
    pkg = build_task_package(repo, session.read_revision)
    active_texts = [h["text"] for h in pkg["hypotheses"]]
    assert "第二代假设接管" in active_texts
    assert "第一代假设" not in active_texts
    concluded = pkg["history_summary"]["hypotheses_concluded_recent"]
    assert any(h["text"] == "第一代假设" and h["status"] == "superseded"
               for h in concluded), "被接管的假设应进历史摘要而不是消失"


def test_evidence_cli_roundtrip(tmp_path):
    book_dir = tmp_path / "BTCUSDT-15m"
    book = ShadowBook(str(book_dir), "BTCUSDT", "15m", TF_MS)
    book.append_bars(_bars("BTCUSDT", 200))
    repo, _ = book.rebuild()
    qs = QueryService(repo, make_token(repo))
    gaps = qs.get_scene()["just_closed_gaps"]
    assert gaps
    gid = gaps[0]["gap_id"]
    proc = subprocess.run(
        [sys.executable, "-m", "battlefield.shadow_cli", "evidence",
         "--workdir", str(book_dir), "--symbol", "BTCUSDT", "--tf", "15m",
         "--id", gid],
        capture_output=True, text=True, cwd=".", timeout=120)
    assert proc.returncode == 0, proc.stderr[-500:]
    out = json.loads(proc.stdout)
    assert out["object"]["gap_id"] == gid and out["bars"]
    bad = subprocess.run(
        [sys.executable, "-m", "battlefield.shadow_cli", "evidence",
         "--workdir", str(book_dir), "--symbol", "BTCUSDT", "--tf", "15m",
         "--id", "GAP-NOPE-1-1"],
        capture_output=True, text=True, cwd=".", timeout=120)
    assert bad.returncode == 2  # 查不到显式失败，不许静默
