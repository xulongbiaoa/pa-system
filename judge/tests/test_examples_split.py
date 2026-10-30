"""examples 池 split 字段回归锁（2026-10-31 审计复核）。

审计台账曾记「examples 池无 split 字段」——复核实测不成立：41 份样本
全部带 split（dev 31 / val 10），由 eval/build_examples.py 按源目录
eval/datasets/<split>/ 盖戳，标签正确性由构造保证，recall 已按
pool_split 过滤。本测试把这三件事钉住，防日后新增样本漏盖戳。
"""
import json
import os

EX_DIR = os.path.join(os.path.dirname(__file__), "..", "..",
                      "knowledge", "examples")
DS_DIR = os.path.join(os.path.dirname(__file__), "..", "..",
                      "eval", "datasets")


def _examples():
    out = []
    for name in sorted(os.listdir(EX_DIR)):
        if name.endswith(".json"):
            out.append(json.load(open(os.path.join(EX_DIR, name))))
    return out


def test_every_example_has_valid_split():
    exs = _examples()
    assert exs, "examples 池为空"
    for e in exs:
        assert e.get("split") in ("dev", "val"), \
            f"{e.get('id')} split 缺失或非法：{e.get('split')!r}"


def test_split_matches_source_dataset_dir():
    for e in _examples():
        seg = e.get("segment")
        src = os.path.join(DS_DIR, e["split"], seg + ".json")
        assert os.path.exists(src), \
            f"{e.get('id')} 标 {e['split']} 但源段不在该池：{src}"
