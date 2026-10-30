"""原册课件文本开采：54 本 Brooks 课程 PDF 逐页抽文本 → 案例库原料。

每页 = 一张图 + 他的讲义要点 + 图上标注（多在文本层）。产物：
knowledge/brooks-cases/raw/<编号>.jsonl（每行一页：book/slide/text）
与 knowledge/brooks-cases/INDEX.md（规模与标签统计）。
版权口径与学习站原册区一致：私有仓、仅个人学习。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

SRC = Path.home() / "workspace/goals/goal/hidden_files/reference/ppt"
OUT = Path(__file__).resolve().parents[1] / "knowledge" / "brooks-cases"

TAGS = {
    "缺口": ["gap", "缺口"], "MM": ["measured", "leg 1 = leg 2", "mm "],
    "楔形": ["wedge", "楔形"], "双顶底": ["double top", "double bottom"],
    "反转": ["reversal", "反转"], "MTR": ["major trend reversal"],
    "H2/L2": ["h2", "l2", "second entry"], "突破": ["breakout", "突破"],
    "通道": ["channel", "通道"], "区间": ["trading range", "区间"],
    "旗形": ["flag", "旗"], "高潮": ["climax", "高潮"],
    "回调": ["pullback", "回调"], "EMA": ["ema", "moving average"],
    "头肩": ["head and shoulders"], "三角形": ["triangle"],
}


def book_id(name):
    m = re.match(r"(\d+)[.提]", name)
    return f"v{m.group(1)}" if m else name[:8]


def main():
    raw = OUT / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    stats = []
    tag_counts = {k: 0 for k in TAGS}
    total_pages = total_text = 0
    for pdf in sorted(SRC.glob("*.pdf")):
        bid = book_id(pdf.name)
        title = re.sub(r"^\d+\.提取自1#共\d+页_", "", pdf.stem)
        txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                             capture_output=True, text=True).stdout
        pages = txt.split("\f")
        rows = []
        for i, page in enumerate(pages):
            clean = "\n".join(l.rstrip() for l in page.splitlines()
                              if l.strip() and "BrooksTradingCourse" not in l
                              and "@Albrooksall" not in l)
            if len(clean) < 40:
                continue
            low = clean.lower()
            tags = [k for k, kws in TAGS.items()
                    if any(w in low for w in kws)]
            for t in tags:
                tag_counts[t] += 1
            rows.append({"book": bid, "title": title, "slide": i + 1,
                         "tags": tags, "text": clean})
        with open(raw / f"{bid}.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        stats.append((bid, title, len(pages), len(rows)))
        total_pages += len(pages)
        total_text += len(rows)
        print(bid, title, f"页 {len(pages)} 有文本 {len(rows)}")
    lines = ["# Brooks 原册案例库（开采原料）", "",
             f"共 {len(stats)} 本、{total_pages} 页、抽得有文本页 {total_text} 页。",
             "每页含他的讲义要点与图上标注原文；按标签可检索（tools/case_search.py）。",
             "", "## 标签分布（页数）", ""]
    for k, v in sorted(tag_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {k}: {v}")
    lines += ["", "## 分册", ""]
    for bid, title, n, m in stats:
        lines.append(f"- {bid} {title}：{n} 页 / 有文本 {m}")
    (OUT / "INDEX.md").write_text("\n".join(lines) + "\n")
    print("TOTAL", total_pages, total_text)


if __name__ == "__main__":
    main()
