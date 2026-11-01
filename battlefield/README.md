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

## 实时输入闭环（run-once，2026-11-01）

`roll_site.py` 新增单次、可重入编排入口，外部定时器一轮调用即完成：
`python3 -m battlefield.roll_site run-once`，按标的执行
feed → 窗口校验（恰 96 根已收盘 15m、连续、边界正确，缺根 = `input_incomplete` 不建场）
→ 模型 → 契约落账 → finalize 导出 → R2 发布。

- 状态 = `web/data24/run_state/<SYM>.json`（原子写），绑定窗口 token + 输入
  指纹 + 输出摘要：同窗重跑返回 `no_new_bar`；同窗未完成则从首个未完成阶段
  恢复，模型不重复调用、输出不重复 append；状态/账本不一致显式停机。
- 结果状态：`no_new_bar / input_incomplete / feed_error / model_unavailable /
  contract_error / stale / applied / export_error / publish_error / completed`，
  命令输出机器可读 JSON，非全 completed/no_new_bar 时退出码 2。
- 模型层为供应商无关协议（brain.py：`battlefield.model-adapter/v1` +
  package/output schema 版本、长度约束、超时/限流/网络/API 失败归一为
  `model_unavailable`）。注入方式：Python 层传任意 callable/适配器，或 CLI
  `--adapter-factory module:factory`（factory(config) 返回适配器）；
  `--adapter mock` 只做链路冒烟，`--adapter recorded` 回放既有判读 JSON。
  phase1/phase2 人工判读入口保留为应急路径。
- 尚未接真实供应商：无获批的供应商/凭据前，不执行真实模型调用，
  线上 cron 仍走人工判读流程，未切换。

## 未实现（按方案依赖排后）

- W06 已落程序契约与会话层（brain.py），尚未接真实模型（适配器为 Recorded/Callable，考试与影子接模型时注入）。
- W07 持久影子：PostgreSQL 形态未落，当前为内存 repository 同契约（方案 §12 离线形态）。
- W08 对齐评估、W09–W11 可视化/推演/复盘：未开工。
