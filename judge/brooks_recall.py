"""阿布原册讲义召回：按本次路由命中的卡片与语境标签，从原册案例库
（knowledge/brooks-cases，4,204 页讲义文本）拉最相关的 2 页进提示词。

定位：这是判断层的「原册撑腰」——卡片是我们提炼的规则，案例库是他
本人的讲义原文（含图上标注）。出处（册/页）随页附上，判断引用时可溯。
只召回不裁决：与本段无关的页由判断层自行忽略，提示词里已写明。
"""
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
RAW = os.path.join(ROOT, "knowledge", "brooks-cases", "raw")

SETUP_TAGS = {
    "B1-trend-breakout": ["突破"],
    "B2-breakout-pullback": ["突破", "回调"],
    "B3-failed-breakout": ["突破", "反转"],
    "A1-m2b": ["H2/L2", "回调"],
    "A2-m2s": ["H2/L2", "回调"],
    "C1-mtr": ["MTR", "反转"],
    "G1-confluence-gap": ["缺口", "测量"],
}

_CACHE = None


def _load():
    global _CACHE
    if _CACHE is None:
        pages = []
        if os.path.isdir(RAW):
            for name in sorted(os.listdir(RAW)):
                if name.endswith(".jsonl"):
                    with open(os.path.join(RAW, name)) as f:
                        pages.extend(json.loads(l) for l in f)
        _CACHE = pages
    return _CACHE


def query_tags(pack, cards):
    tags = []
    for c in cards:
        tags.extend(SETUP_TAGS.get(c, []))
    label = pack["trend"]["label"]
    if label in ("上升", "下降"):
        tags.append("通道")
    elif label == "震荡":
        tags.append("区间")
    verdict = (pack["trend"].get("gap_consistency") or {}).get("verdict")
    if verdict == "冲突":
        tags.append("反转")
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def recall_cases(pack, cards, k=2):
    """返回 [{book, title, slide, tags, text}]，按命中标签数降序、
    同分按 (book, slide) 确定性排序。text 截到约 500 字（整行边界）。"""
    pages = _load()
    if not pages:
        return []
    want = query_tags(pack, cards)
    scored = []
    for p in pages:
        score = sum(1 for t in want if t in p["tags"])
        if score:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], x[1]["book"], x[1]["slide"]))
    out = []
    for _, p in scored[:k]:
        text = p["text"]
        if len(text) > 500:
            cut = text.rfind("\n", 0, 500)
            text = text[:cut if cut > 200 else 500]
        out.append({"book": p["book"], "title": p["title"],
                    "slide": p["slide"], "tags": p["tags"], "text": text})
    return out
