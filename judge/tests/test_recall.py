"""召回隔离与多样性测试（2026-10-30 复核后新增）。

原实现只按趋势标签取「每类第一条」，实测任何样本都只返回 ex-APT + ex-ARB，
且不排除当前样本：APT/ARB/AVAX 三段的提示里会出现自己的 draft_verdict。
这组测试锁住三条不变量，防回退。
"""

import json
import os

import pytest

from judge.prompt_builder import recall_examples
from perception.features import build_feature_pack, load_config

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
CFG = load_config()


def _load(seg_id):
    for split in ("dev", "val", "test"):
        p = os.path.join(ROOT, "eval", "datasets", split, seg_id + ".json")
        if os.path.exists(p):
            return json.load(open(p))
    raise FileNotFoundError(seg_id)


def _pack(seg):
    bars = seg["bars"][:180]
    p0 = build_feature_pack(bars, [], CFG)
    anchors = [{"price": s["anchor"], "source": "swing-major"}
               for s in p0["swings"]["major"]]
    return build_feature_pack(bars, anchors, CFG), bars


def _recall(seg_id, k=3):
    seg = _load(seg_id)
    pack, bars = _pack(seg)
    return recall_examples(pack, k, segment=seg["id"], symbol=seg["symbol"],
                           bars=bars)


@pytest.mark.parametrize("seg_id", [
    "bn-APTUSDT-1d-1707004800000",
    "bn-ARBUSDT-4h-1763539200000",
    "bn-AVAXUSDT-15m-1726945200000",
])
def test_never_recalls_itself(seg_id):
    """曾经的自样本泄漏点：这三段会在自己的提示里读到自己的草稿结论。"""
    ids = [e["id"] for e in _recall(seg_id)]
    assert ids, "召回为空，测试失效"
    assert "ex-" + seg_id not in ids
    assert seg_id not in [e.get("segment") for e in _recall(seg_id)]


def test_val_sample_only_recalls_from_dev():
    """验证集样本的提示里不得出现 val 的答案。"""
    exs = _recall("bn-DOTUSDT-4h-1767513600000")
    assert exs
    assert all(e["split"] == "dev" for e in exs), [e["split"] for e in exs]


def test_pool_not_degenerate():
    """不许再恒返回同一对样本：k=3 时应尽量覆盖 3 个不同 (语境,结论) 桶。"""
    exs = _recall("ds23")
    assert len(exs) == 3
    keys = {(e["annotation"]["context"], e["annotation"]["draft_verdict"])
            for e in exs}
    assert len(keys) == 3, keys


def test_overlapping_window_excluded():
    """同标的、时间区间相交的切片也算泄漏——只按文件名排除挡不住。"""
    ex_path = os.path.join(ROOT, "knowledge", "examples", "ex-ds23.json")
    ex = json.load(open(ex_path))
    pack, _ = _pack(_load("ds23"))
    # 不给 segment，只给 symbol + 同一段时间：ds23 仍应被时间区间挡掉
    got = recall_examples(pack, 3, symbol=ex["symbol"], bars=ex["bars"])
    assert "ex-ds23" not in [e["id"] for e in got]


def test_recall_is_deterministic():
    a = [e["id"] for e in _recall("ds23")]
    b = [e["id"] for e in _recall("ds23")]
    assert a == b
