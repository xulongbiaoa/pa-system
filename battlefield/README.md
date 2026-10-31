# 战场翻译器（battlefield）

《虚拟战场翻译器完整实施方案 v1》（design/）的独立实现；旧代码只作参考，不复用其状态与含义。

## 已实现（W01–W05）

| 任务 | 模块 | 内容 |
|---|---|---|
| W01 翻译规范 | contracts.py | Bar/Snapshot/Level/Target/Event 契约；Decimal 价格；战场词汇与数据边界 |
| W02 单根事实 | facts.py | range/body/CLV/影线/重叠/收盘变化；因果尺度（此前 20 根 range 中位数）、warmup、零振幅比率为 null |
| W03 地形与动作 | terrain.py / actions.py | 人工锚、确认摆动点（confirmed_at 纪律）、Attempt/Test/Gap 事件语义、行动结果向量与对照 |
| W04 状态内核 | reducers.py / repository.py | 确定性逐根归约、事件日志、内存 repository（幂等/修订隔离/迟到拒绝）、重放哈希一致 |
| W05 查询层 | queries.py | snapshot token 绑定、get_scene/get_changes/as_known_at/inspect_evidence/read_bars/check_conditions |
| W06 AI 判读 | brain.py | **单一大脑定案**：一个判读任务同时读全局 scene + 局部 changes（不再分 MAP/ARRIVAL 两任务）；假设集中维护 add/confirm/challenge/supersede 带修订历史；read_cursor 回显校验、引用先全量核验后统一落盘、模型不可用/过期是系统结果不记策略无机会；候选只进 candidate_proposals 提案分区 |

缺口口径 = anchor_separation（整根分离立账、触锚关账、回补测试按完整靠近—离开—返回计数），
与 G0/GC1 定义审定的关系见方案 §13：本实现不改变历史 gap 含义，审定结论出来后在此处对账。
“整根离开观察带即确认拒绝”为具名工程代理 `TEST_REJECTION_PROXY`，不等于专家定义。

## 验收

`battlefield/tests/test_battlefield.py`（16 项）：§11 主轨迹 + 分支夹具、前缀不变性、
向下镜像、无突破/双侧同根 unknown、缺根/迟到/重复/修订、摆动确认时间、重放确定性、
结果向量数值、快照绑定与提案引用核验。

## 未实现（按方案依赖排后）

- W06 已落程序契约与会话层（brain.py），尚未接真实模型（适配器为 Recorded/Callable，考试与影子接模型时注入）。
- W07 持久影子：PostgreSQL 形态未落，当前为内存 repository 同契约（方案 §12 离线形态）。
- W08 对齐评估、W09–W11 可视化/推演/复盘：未开工。
