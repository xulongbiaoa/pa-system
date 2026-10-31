# Build 1 设计稿：拒绝理由依据引用（2026-10-31，与 B3 样板配套）

## 数据结构

pending_conditions 的 missing 从字符串数组升级为对象数组（单项）：

```json
{"condition": "缺的必要条件，一句话",
 "evidence": "对应哪根 K 线 / 哪个价位（如『决策根收 80400.27，未收回 80430.45 上方』）",
 "basis": {"type": "branch|card|skeleton|extra",
           "ref": "branch→点位号 P2；card→条目号 B3-N3；skeleton→条款名；extra→加码理由一句话"}}
```

## 校验（judge/schema.json + judge/validate.py）

- schema：missing items 放宽为 anyOf [字符串（存量旧格式）, 旧对象
  形式（存量）, 新对象形式]；新对象形式 required 三键、basis.type
  枚举、additionalProperties false。
- validate 对新对象形式硬校验：三键非空；basis=card 时 ref 必须以
  本 pending 的 setup 代号开头且形如 `<SETUP>-<N|B|V>\d+`；
  basis=branch 时 ref 须形如 `P\d+`（点位存在性由 record/复核对
  备忘地图核对）；basis=extra 时 ref 不许为空（必须自述理由）。
- 诚实边界：validate 只核形式与引用格式；「引对了没有」靠复核与
  错误空仓考试，与「禁候选降格」同例——不假装可全自动执法。

## 提示纪律（judge/prompt_builder.py 与 campaign_prompt 到达备忘各加一段）

- 每条 missing 必须带 basis；引冻结分支 trigger 的写 branch+点位号，
  引卡片条件的写 card+条目号，引骨架硬条的写 skeleton+条款名。
- **extra 规则**：分支、卡片、骨架之外的任何要求一律标 extra 并写
  明理由；extra 不许单独构成不写候选的理由——某 setup 的缺项若
  全部是 extra 且卡上必须项已齐，必须写候选并标 qualified，
  extra 只作复核标记随判读落账。
- no_trade_reason 维持枚举不变（它是汇总口径，细账在 missing）。

## 度量（eval/forward_anatomy.py 增补）

- basis 分布（branch / card / skeleton / extra 各占缺项比例）；
- **额外加码率** = extra 缺项 / 全部缺项；
- **纯加码空仓数** = 全部缺项均为 extra 的判读数（最该进复核的
  一类）；每批影子复跑，与出手率并列报告。

## 落地顺序

B3 样板过目 → 其余 6 卡四分（条目号就位）→ schema/validate/提示
三处同批改 + 测试 → 下一批影子起新判读全量带 basis；存量判读
不回改，解剖对存量只报「无 basis」占比。
