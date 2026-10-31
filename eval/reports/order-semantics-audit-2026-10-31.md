# 存量订单语义审计（2026-10-31，设计 v2.2 P0 配套）

缺陷：旧 `eval/replay.py` 对 `order_type=market` 的计划从决策后第一根起按计划 entry **无条件成交**。顺势类计划当时按「stop 触发、order_type 写 market」的编码约定产生，价格从未到过 entry 时也被记成成交。本审计普查全部已解析的 plan 型交易并逐笔复核；脚本 `eval/order_semantics_audit.py`，机读结果同目录同名 .json。**既有结果文件一律未改**，修正以本报告为准。

## 普查结果

已解析 plan 型交易共 **13 笔**（branch-ab 4、touch-ab 1、event-ab 4、forward ledger 2、ablation-confirm2 2）：

| 类别 | 笔数 | 说明 |
|---|---|---|
| limit（不受影响） | 10 | 穿越才成交的口径从未变 |
| market（逐笔复核） | 3 | 见下 |

未解析 tracked（branch-ab 4 个 qualified 未入 trades、touch-ab XRP 1 笔）：order_type 均为 limit，今后复跑 score 不受本次语义修改影响。

## market 3 笔逐笔结论

1. **branch-ab BTC 15m A2 多**（entry 77384.02 = 决策根高点 77384.01 外 1 tick，标准 stop 触发编码）：触发成立，按 stop_market 重算 **−0.0889R**（原记 −0.1629R，仍为窗末平仓亏损）。该笔此前已因 A2 方向矛盾被剔除出分支 A/B 裁决总数，**裁决不受影响**，此数只作档案修正。
2. **event-ab/auto ev01 A1 多**（entry 165.66 在决策根区间内、收盘 165.44 上方）：语义不明（LEGACY_ORDER_AMBIGUOUS），但 stop 读法 −1.0488R、limit 读法 −1.0340R 均成交且止损出场，**与原记 −1.0488R 实质一致，AUTO 臂数字不动**。
3. **event-ab/evmap ev12 A2 空**（entry 41.9，决策收盘 43.45）：按唯一方向自洽的 stop 读法，**触发前前提先失效（void_before_fill），从未触发**——原记 **−1.014R 是未触发误成交，自即日起退役**，不得再引用（limit 读法方向不自洽，其 −1.010R 是限价模拟对低位卖单的机械产物，不作数）。

## 对已发布结论的影响

- **evmap 臂修正**：成交 2 笔 → 1 笔（只剩 ev04 B3 空限价 +3.373R）；每机会均值 +0.118 → **+0.169**；与 AUTO 的配对差 +0.192 → +0.243/机会。原裁决「CI 含 0、不宣胜者」**不变**（变化集中在单个配对，n=20 下 CI 仍跨 0）。
- **分支预写 A/B 裁决**：已解析 4 笔中 3 笔 limit 不动，BTC A2 本就在裁决口径外，**裁决不变**。
- **前向影子累计账面**（−1.2266R，2 笔 B3 限价）：**不变**。
- **B3 多空不对称统计**（多头限价 4 全亏 / 空头 2 胜 1 负）：全部为 limit，**不变**。
- 其余引用过 ev12 的场合（evmap 解剖、出手率材料）引用时须注「已退役」。

## 口径边界（即日起）

- 新判读：顺势 stop 触发写 `order_type=stop_market`（schema/prompt/router 已同步）；market 只表示决策点立即入场、按决策后首根开盘成交。
- 旧数据中 market 且 entry 偏离决策根极值的计划一律 LEGACY_ORDER_AMBIGUOUS：不得跨本次修改重跑 score 后与旧数字直接比对；必须重算时按本报告的分类法逐笔复核。
