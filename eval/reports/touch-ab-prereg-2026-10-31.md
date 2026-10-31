# 触及口径 A/B 回判实验预注册（2026-10-31，用户立项）

## 问题

出手率解剖补记定位的真漏点：55/81 个前向 fortress 事件，价格盘中触及
了地图已画点位，但决策收盘落在 v2 点名执法带（点位 ±0.25×段均幅）外，
到达遍只能记 no_trade。限价分支（B3 翻面挂要塞边缘、触及即成交）与
「收盘须在带内」的认定性质相冲。本实验问：**只改到达认定一处**
（限价单改触及口径），这批样本能多产出多少候选、过 gate 几何、
解析出的 R 是什么样。规则改不改，看回判数据，不在本实验内自动生效。

## 总体（机械规则，prep 时冻结）

eval/forward 全部判读中同时满足：
1. kind=fortress 且 state status=judged_no_trade；
2. eval/forward/maps/<eid>.json 与快照存在；
3. 决策根按全快照特征包算出的被测点位非空（决策根振幅 ±0.25×段均幅
   内触及至少一个 levels_of 点位）；
4. 决策收盘不在本地图任一点位 [lo,hi] ±0.25×段均幅内（A 臂失败的
   位置条件）。

## 两臂

- **A 臂（对照，常量）**：原始落账结果——总体全部 no_trade，候选 0、
  tracked 0、每机会 R=0。不重判。
- **B 臂（干预）**：复用同一批冻结地图（不重画），只重跑到达判读。
  提示 = 原 evmaprompt 全文，唯一改动是备忘规则 1 换成下述分轨认定，
  并在全文末尾追加实验口径覆盖块（声明与正文候选纪律冲突时以分轨
  认定为准）。分轨认定原文：

> 每个候选必须在 candidate 中写 point_id，点名上面地图中的一个决胜点；
> 到达认定分两轨：候选 plan 的 order_type 为 limit 时，决策根 K 线区间
> 与该点 [lo, hi] 相交（最高 ≥ lo 且最低 ≤ hi）即算到达，可标
> qualified；order_type 为 market 时，仍须决策根收盘价在该点
> [lo, hi] ±0.25×段均幅内才可标 qualified，未达者只许写进
> pending_conditions。

其余纪律（冻结分支触发条件、成色、腿数、RR 定价、void 双件、禁候选
降格）一字不变。判读员只读变体提示 + 决策图（持久目录重渲），禁读
原 judgments 与任何其它文件。

## score 口径（与 record 同源，只换位置执法一处）

validate_judgment → 取第一个 qualified → merge_candidate_terms +
注入 side/setup/context（与 record 同款组装）→ B 轨位置执法（limit 按
触及、market 按收盘，点不存在/缺 point_id 同样判 violation）→
adjudicate（同 record 参数）→ 过门者用决策点后 300 根 simulate_plan
解析（fetch 口径同 resolve_tracked；生命周期未走完者记 unresolved，
不计入分母并单独报数）。

## 指标与判读框架

- B 臂：候选数、qualified 数（按 setup）、violation 数、gate 拒绝数
  （按规则）、tracked/成交数、逐单 R、每机会 R（sum R / 有终局结果
  的事件数，unfilled 计 0）、每机会 R 的 bootstrap 95% CI（种子
  20261031）。
- 判定：本实验只出数与裁决建议，**不自动改任何生产规则**；触及口径
  是否进 v2 执法由用户看数后另行拍板。
- 污染防线：B 判读员禁读 A 判读与裁决报告；地图为 A/B 共用输入
  （冻结在前，非污染）；score 的位置执法机械复核，不采信判读员自述。
