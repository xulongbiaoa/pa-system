"""连续账本（plan-2）测试：账本/视图分离、跨 96 根连续、幂等与故障恢复。

覆盖验证清单：
- 初始化 96 根后追加 97/98 根，账本不截断、revision 连续、旧假设保留；
- 视图只含最近 96 根，但 ledger revision/cursor 正确；
- 重复拉取幂等，缺根/乱序/同 ID 修订显式失败；
- phase2 同输出重试不重复 append、不同输出拒绝；
- 导出故障后重跑从失败阶段恢复，不重复落账。
"""
import json
import os

import pytest

from battlefield import export_24h as e24
from battlefield import roll_site
from battlefield.contracts import make_bar
from battlefield.feed import InputIncompleteError, plan_increment
from battlefield.shadow import ShadowBook

TF_MS = 900_000
BASE = 1_700_000_100_000


def _bars(sym, n, start=BASE):
    bars = []
    price = 100.0
    for i in range(n):
        drift = 0.6 if (i // 10) % 2 == 0 else -0.6
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


# ---------- feed 增量规划 ----------

def test_plan_increment_ok_gap_revision_unsorted():
    existing = _bars("BTCUSDT", 10)
    fetched = _bars("BTCUSDT", 13)  # 含重叠 10 根 + 新 3 根
    new = plan_increment(existing, fetched, TF_MS)
    assert [b.open_time for b in new] == [BASE + i * TF_MS for i in (10, 11, 12)]

    gapped = _bars("BTCUSDT", 12)
    del gapped[10]  # 第 11 根缺失
    with pytest.raises(InputIncompleteError):
        plan_increment(existing, gapped, TF_MS)

    import dataclasses
    revised = _bars("BTCUSDT", 13)
    revised[5] = dataclasses.replace(revised[5], close=revised[5].low)  # 同 ID 改内容
    with pytest.raises(InputIncompleteError):
        plan_increment(existing, revised, TF_MS)

    shuffled = _bars("BTCUSDT", 13)
    shuffled[11], shuffled[12] = shuffled[12], shuffled[11]
    with pytest.raises(InputIncompleteError):
        plan_increment(existing, shuffled, TF_MS)


# ---------- ShadowBook 严格追加与 canonical 落账 ----------

def _mini_book(tmp_path):
    return ShadowBook(str(tmp_path / "BTCUSDT-15m"), "BTCUSDT", "15m", TF_MS)


def test_shadow_append_gap_and_revision_conflict(tmp_path):
    book = _mini_book(tmp_path)
    bars = _bars("BTCUSDT", 10)
    assert book.append_bars(bars) == 10
    assert book.append_bars(bars) == 0  # 重复幂等
    with pytest.raises(InputIncompleteError):
        book.append_bars(_bars("BTCUSDT", 3, start=BASE + 11 * TF_MS))  # 跳过第 11 根
    import dataclasses
    revised = [dataclasses.replace(bars[0], close=bars[0].low)]  # 同 ID 改内容
    with pytest.raises(InputIncompleteError):
        book.append_bars(revised)


def test_shadow_apply_canonical_idempotent_and_conflict(tmp_path):
    book = _mini_book(tmp_path)
    book.append_bars(_bars("BTCUSDT", 25))  # 足够产生摆动 level
    repo, session, pkg = book.pending_package()
    level = pkg["scene"]["levels"][0]["level_key"]
    out = {"read_cursor": pkg["snapshot_revision"], "action": "WAIT_BEHAVIOR",
           "hypothesis_ops": [{"op": "add", "text": "连续账本假设",
                               "support_refs": [level], "counter_refs": []}],
           "watch_plan": None, "candidate": None}
    r1 = book.apply_output(out)
    assert r1["status"] == "ok" and r1["output_digest"]
    r2 = book.apply_output(out)
    assert r2["status"] == "ok" and r2["detail"] == "duplicate_ignored"
    assert len(book._read_outputs()) == 1  # 没重复 append
    other = {**out, "hypothesis_ops": [{"op": "add", "text": "另一份",
                                        "support_refs": [level],
                                        "counter_refs": []}]}
    r3 = book.apply_output(other)
    assert r3["status"] == "contract_error"  # 同 cursor 不同输出拒绝
    assert len(book._read_outputs()) == 1
    repo2, session2, pkg2 = book.pending_package()
    assert pkg2 is None and session2.read_revision == pkg["snapshot_revision"]


# ---------- phase1/phase2 连续账本全流程 ----------

class LedgerEnv:
    def __init__(self, tmp_path, monkeypatch):
        self.out = tmp_path / "data24"
        self.out.mkdir()
        monkeypatch.setattr(e24, "OUT", str(self.out))
        self.ledger_root = str(tmp_path / "shadow")
        self.all_bars = {sym: _bars(sym, 98) for sym in roll_site.SYMBOLS}
        self.released = {sym: 96 for sym in roll_site.SYMBOLS}
        self.published = []

    def fetcher(self, sym, existing):
        have = len(existing)
        want = self.released[sym]
        return self.all_bars[sym][have:want] if want > have else []

    def publisher(self, sym):
        self.published.append(sym)
        return "uploaded"

    def judge_file(self, tmp_path, sym, note):
        pkg = json.loads((self.out / f"pkg_{sym}.json").read_text())
        level = pkg["scene"]["levels"][0]["level_key"]
        out = {"read_cursor": pkg["snapshot_revision"],
               "action": "WAIT_BEHAVIOR",
               "hypothesis_ops": [{"op": "add", "text": f"连续判读 {note}",
                                   "support_refs": [level], "counter_refs": []}],
               "watch_plan": {"plan_id": "WP1", "watch_level": level,
                              "watch_behavior": "等回补测试",
                              "entry_trigger": "测试收官后复核",
                              "cancel_if": "账本推进到下一 revision"},
               "candidate": None}
        path = tmp_path / f"judge-{sym}-{note}.json"
        path.write_text(json.dumps(out, ensure_ascii=False))
        return str(path)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    return LedgerEnv(tmp_path, monkeypatch)


def test_ledger_flow_continuous_across_96(env, tmp_path):
    r1 = roll_site.phase1(fetcher=env.fetcher, ledger_root=env.ledger_root)
    assert all(r["status"] == "package_ready" and r["snapshot_revision"] == 96
               for r in r1)
    judges = {sym: env.judge_file(tmp_path, sym, "one")
              for sym in roll_site.SYMBOLS}
    res = roll_site.phase2(judges, publisher=env.publisher,
                           ledger_root=env.ledger_root)
    for r in res:
        assert r["ledger_revision"] == 96 and r["ledger_cursor"] == 96
        assert r["ai_stale"] is False
    snap = json.loads((env.out / "BTCUSDT.json").read_text())
    assert snap["meta"]["view_window"] == 96  # 账本此时共 96 根，展示全量
    assert snap["meta"]["bars_total"] == 96
    assert snap["meta"]["ledger_revision"] == 96
    assert len(snap["bars"]) == 96
    assert snap["hypotheses"], "第一轮假设应进快照"

    # 推进到 98 根：账本不截断，旧假设还在 package 里
    for sym in roll_site.SYMBOLS:
        env.released[sym] = 98
    r2 = roll_site.phase1(fetcher=env.fetcher, ledger_root=env.ledger_root)
    assert all(r["snapshot_revision"] == 98 for r in r2)
    pkg = json.loads((env.out / "pkg_BTCUSDT.json").read_text())
    assert any("连续判读 one" in h["text"] for h in pkg["hypotheses"]), \
        "跨过 96 根后旧假设必须保留"
    assert pkg["changes"]["from_revision"] == 96
    assert pkg["changes"]["to_revision"] == 98  # 增量游标正确推进（静默根可无事件）

    judges2 = {sym: env.judge_file(tmp_path, sym, "two")
               for sym in roll_site.SYMBOLS}
    res2 = roll_site.phase2(judges2, publisher=env.publisher,
                            ledger_root=env.ledger_root)
    assert all(r["ledger_revision"] == 98 for r in res2)
    snap2 = json.loads((env.out / "BTCUSDT.json").read_text())
    assert snap2["meta"]["ledger_bars"] == 98
    assert len(snap2["bars"]) == 98, "展示层给全量账本 K 线（可左拖回看）"
    assert snap2["meta"]["view_window"] == 98
    assert snap2["bars"][0]["t"] == BASE  # 第一根还在，没被 96 窗口截掉
    assert snap2["bars"][-1]["t"] == BASE + 97 * TF_MS
    assert snap2["meta"]["ai"]["outputs_total"] == 2

    # 同一份判读重跑 phase2：不重复 append
    res3 = roll_site.phase2(judges2, publisher=env.publisher,
                            ledger_root=env.ledger_root)
    assert all(r["ledger_revision"] == 98 for r in res3)
    book = ShadowBook(os.path.join(env.ledger_root, "BTCUSDT-15m"),
                      "BTCUSDT", "15m", TF_MS)
    assert len(book._read_outputs()) == 2

    # 无新根：up_to_date，不生成新 package
    r3 = roll_site.phase1(fetcher=env.fetcher, ledger_root=env.ledger_root)
    assert all(r["status"] == "up_to_date" for r in r3)


def test_ledger_phase2_export_failure_recovers(env, tmp_path, monkeypatch):
    roll_site.phase1(fetcher=env.fetcher, ledger_root=env.ledger_root)
    judges = {sym: env.judge_file(tmp_path, sym, "one")
              for sym in roll_site.SYMBOLS}
    original = e24.finalize_from_ledger
    state = {"failed": False}

    def flaky(sym, book=None):
        if not state["failed"]:
            state["failed"] = True
            raise RuntimeError("export boom")
        return original(sym, book)

    monkeypatch.setattr(e24, "finalize_from_ledger", flaky)
    with pytest.raises(RuntimeError):
        roll_site.phase2(judges, publisher=env.publisher,
                         ledger_root=env.ledger_root)
    res = roll_site.phase2(judges, publisher=env.publisher,
                           ledger_root=env.ledger_root)
    assert all(r["ledger_revision"] == 96 for r in res)
    book = ShadowBook(os.path.join(env.ledger_root, "BTCUSDT-15m"),
                      "BTCUSDT", "15m", TF_MS)
    assert len(book._read_outputs()) == 1, "恢复轮不得重复落账"
