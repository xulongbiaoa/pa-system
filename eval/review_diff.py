"""对账：外部评审者的盲标 JSON vs 机器草稿。

评审文件放 knowledge/reviews/<segment>.json（annotation_schema 格式）。
输出：一致率（语境 / 结论两项）、分歧清单（供用户只裁定分歧段）。
"""

import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
EX = os.path.join(ROOT, "knowledge", "examples")
RV = os.path.join(ROOT, "knowledge", "reviews")


def main():
    reviews = {}
    if os.path.isdir(RV):
        for name in sorted(os.listdir(RV)):
            if name.endswith(".json"):
                r = json.load(open(os.path.join(RV, name)))
                reviews[r["segment"]] = r
    total = agree_ctx = agree_verdict = 0
    diffs = []
    for name in sorted(os.listdir(EX)):
        if not name.endswith(".json"):
            continue
        ex = json.load(open(os.path.join(EX, name)))
        seg = ex["segment"]
        if seg not in reviews:
            continue
        total += 1
        r = reviews[seg]
        d = ex["annotation"]
        ok_ctx = r["context"] == d["context"]
        ok_v = r["verdict"] == d["draft_verdict"]
        agree_ctx += ok_ctx
        agree_verdict += ok_v
        if not (ok_ctx and ok_v):
            diffs.append(
                {
                    "segment": seg,
                    "draft": {"context": d["context"], "verdict": d["draft_verdict"]},
                    "review": {"context": r["context"], "verdict": r["verdict"],
                               "setup": r.get("setup"), "hypothesis": r.get("primary_hypothesis")},
                }
            )
    print(f"已复核 {total} 段；语境一致 {agree_ctx}，结论一致 {agree_verdict}")
    print(f"分歧 {len(diffs)} 段（待用户裁定）：")
    for d in diffs:
        print(" -", json.dumps(d, ensure_ascii=False))


if __name__ == "__main__":
    main()
