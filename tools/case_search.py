"""原册案例检索：按标签/关键词查 Brooks 讲义页（判断层案例召回原料）。

用法：python3 tools/case_search.py <关键词...> [--limit N]
多个关键词取交集；先按标签命中、再按正文子串命中排序输出。
"""
import json
import sys
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "knowledge" / "brooks-cases" / "raw"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    limit = 5
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    if not args:
        print("给关键词，如: python3 tools/case_search.py 缺口 measuring")
        return
    hits = []
    for f in sorted(RAW.glob("*.jsonl")):
        for line in open(f):
            r = json.loads(line)
            low = r["text"].lower()
            if all(a.lower() in low or a in r["tags"] for a in args):
                score = sum(a in r["tags"] for a in args)
                hits.append((score, r))
    hits.sort(key=lambda x: -x[0])
    print(f"命中 {len(hits)} 页，示前 {min(limit, len(hits))} 页")
    for _, r in hits[:limit]:
        print(f"\n### [{r['book']} {r['title']} · slide {r['slide']}] "
              f"tags={','.join(r['tags'])}")
        print(r["text"][:600])


if __name__ == "__main__":
    main()
