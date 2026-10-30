"""gold-book 回归护栏（2026-10-30 重建）。

旧 knowledge/gold/（30 段外部标注）已按用户拍板删除：标注出自他方 AI
读我方知识卡，自产自销，不再作任何回归依据；原先钉在那 30 段上的
特征包/裁决/回放复现测试随之退役。

新护栏只管识别层金标准 knowledge/gold-book/ 的完整性：
1. MANIFEST.sha256 全部对得上（题面图与 items.jsonl 未被改动）；
2. 每条 items 可解析、出处（book/slide）齐备、答案卡原文非空；
3. 条目数不得低于首次冻结基线（只许增补，不许删减）。
"""

import hashlib
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
GOLD_BOOK = os.path.join(ROOT, "knowledge", "gold-book")
BASELINE_ITEMS = 10


def _items():
    path = os.path.join(GOLD_BOOK, "items.jsonl")
    return [json.loads(line) for line in open(path) if line.strip()]


def test_manifest_integrity():
    checked = 0
    for line in open(os.path.join(GOLD_BOOK, "MANIFEST.sha256")):
        digest, rel = line.split()
        path = os.path.join(GOLD_BOOK, rel)
        assert os.path.exists(path), f"missing {rel}"
        actual = hashlib.sha256(open(path, "rb").read()).hexdigest()
        assert actual == digest, f"hash mismatch {rel}"
        checked += 1
    assert checked >= BASELINE_ITEMS + 1


def test_items_wellformed():
    items = _items()
    assert len(items) >= BASELINE_ITEMS
    ids = [it["id"] for it in items]
    assert len(ids) == len(set(ids))
    for it in items:
        assert it["book"] and it["slide"]
        assert len(it["key_excerpt"]) >= 50
        assert os.path.exists(os.path.join(GOLD_BOOK, it["image"]))
