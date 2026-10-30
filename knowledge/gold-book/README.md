# gold-book：识别层金标准（2026-10-30 用户拍板重建）

旧 gold（knowledge/gold/，外部 AI 按我方知识卡标注的 30 段）已删除：
标注者用的是我方知识，存在自产自销，2026-10-30 先降为回归护栏，
同日晚间用户拍板直接删除重建。

## 本集定义

- 每条 = 阿布原册一页：题面是该页涂字版图（文字层涂白，只剩 K 线/
  均线/线条/箭头），答案卡 key_excerpt 是该页他本人的讲义原文。
- ground truth 只有他本人的文字，没有任何我方或第三方标注。
- first_run_verdict 是首次盲考的记分（hit/half/miss），只作基线记录，
  不属于答案本身。

## 冻结与回归规则

- 本目录冻结：只许经新盲考批次「增补」新条目，不许改已有条目的
  key_excerpt；图片与 items.jsonl 由 MANIFEST.sha256 守护，
  eval/tests/test_gold_regression.py 校验。
- 任何对 knowledge/specs/chart-reading-checklist.md、判断提示的改动，
  合入前须在本集全量重跑盲判：语境轴与课眼轴不得低于首次基线。
- 污染声明：本集会被反复使用，只能当回归护栏；样本外成绩以不断
  抽取的新页批次为准（eval/reports/brooks-book-exam/）。
