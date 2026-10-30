# pa-system

价格行为学 AI 交易系统（按 2026-10-30 用户拍板的架构方案实施）。

五层：感知层（确定性代码 + 单元测试）→ 判断层（AI 只做语境/成色，JSON 契约）→ 裁决层（代码只否决）→ 评估层（开发/验证/测试三切分 + 基线对照）→ 反思闭环（归因分类，改规走提案）。

- knowledge/：core.md（常驻，≤2000 字）、router.md（≤800 字）、priors.md、setups/（每卡 ≤500 字）、examples/（标注样本）、archive/（冻结附册与方案原文）
- perception/：特征包纯函数 + tests/
- judge/：提示构造、schema、适配器
- gate/：裁决规则代码
- eval/：datasets/（dev/val/test）、replay 与报告
- proposals/：改规提案（一案一文件，用户裁定合入）
- changelog.md：版本史与废止规则（不进 AI 上下文）

纪律：本仓每次改动先 commit；感知口径改动必须同步更新测试与 changelog；先验「未验证」只能当倾向。
