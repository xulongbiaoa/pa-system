"""滚动影子账本测试：交错重放恢复、过期不落账、无新根不开跑。"""
from decimal import Decimal

from battlefield.contracts import make_bar
from battlefield.reducers import Battlefield
from battlefield.repository import InMemoryRepository
from battlefield.shadow import ShadowBook
from battlefield.terrain import make_level

TF_MS = 900_000

FIXTURE = [
    (99, "99.4", "98.6", 99),
    (99, 102, "98.8", "101.5"),
    ("101.5", 103, 101, "102.5"),
    ("102.5", "102.8", "100.2", "100.4"),
    ("100.8", "102.5", "100.7", "102.2"),
    ("102.2", "102.4", "100.3", "100.4"),
    ("100.8", 103, "100.7", "102.8"),
]


def bar(i, o, h, l, c):
    return make_bar("TEST", "15m", i * TF_MS, (i + 1) * TF_MS, o, h, l, c,
                    received_at=(i + 1) * TF_MS)


def factory(bars):
    kernel = Battlefield("TEST", "15m", TF_MS)
    kernel.register_level(make_level("P1", "100", "100", kind="manual", source="样板锚",
                                     available_at=0, confirmed_at=0, band=Decimal("0.5")))
    repo = InMemoryRepository(kernel)
    for b in bars:
        repo.commit_bar(b)
    return repo


def make_book(tmp_path):
    return ShadowBook(str(tmp_path / "book"), "TEST", "15m", TF_MS, factory=factory)


def test_shadow_rolling_and_recovery(tmp_path):
    book = make_book(tmp_path)
    bars = [bar(i, *r) for i, r in enumerate(FIXTURE)]
    assert book.append_bars(bars[:4]) == 4
    assert book.append_bars(bars[:4]) == 0            # 无新根
    repo, session, pkg = book.pending_package()
    assert pkg is not None and pkg["snapshot_revision"] == 4
    out1 = {"read_cursor": 4, "action": "WATCH",
            "hypothesis_ops": [{"op": "add", "text": "缺口守住",
                                "support_refs": ["GAP-P1-1"], "counter_refs": []}]}
    assert book.apply_output(out1)["status"] == "ok"
    repo, session, pkg = book.pending_package()
    assert pkg is None                                # 已消费到最新，不开跑

    assert book.append_bars(bars[4:]) == 3
    repo, session, pkg = book.pending_package()
    assert pkg["snapshot_revision"] == 7
    assert pkg["hypotheses"][0]["hyp_id"] == "H1"     # 大脑带着旧假设看新变化
    out2 = {"read_cursor": 7, "action": "WATCH",
            "hypothesis_ops": [{"op": "challenge", "hyp_id": "H1", "reason": "再议"}]}
    assert book.apply_output(out2)["status"] == "ok"

    # 全新进程视角：交错重放恢复
    book2 = make_book(tmp_path)
    repo2, session2 = book2.rebuild()
    assert repo2.kernel.hypotheses[0]["status"] == "challenged"
    assert session2.read_revision == 7
    _, _, pkg2 = book2.pending_package()
    assert pkg2 is None


def test_shadow_stale_output_not_persisted(tmp_path):
    book = make_book(tmp_path)
    bars = [bar(i, *r) for i, r in enumerate(FIXTURE)]
    book.append_bars(bars[:4])
    res = book.apply_output({"read_cursor": 99, "action": "WATCH"})
    assert res["status"] == "stale"
    assert book._read_outputs() == []                 # 没落账
    repo, session, pkg = book.pending_package()
    assert pkg is not None                            # cursor 没推进，仍待判读
