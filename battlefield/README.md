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

## 连续账本 + 96 根视图（plan-2，2026-11-01 定版）

沙盘线语义分两层，取代 2026-10-31 的「日内整窗」定版：

- **连续账本（记忆层）**：每标的 ShadowBook 在仓库根 `shadow/<SYM>-15m/`
  （2026-10-31 种子 1000 根起，沿用不迁移）。只追加已收盘 Bar，跨窗跨天
  不截断；Brain cursor、假设、观察计划、候选与判读历史连续演化。
  `feed.fetch_incremental / plan_increment` 以账本尾根为界取增量，缺根、
  乱序、同 ID 内容修订显式报错；`ShadowBook.append_bars` 同口径严格追加；
  `apply_output` canonical 幂等——同 read_cursor 同输出复用既有结果、
  不同输出拒绝覆盖/追加，stale/契约错误不推进 cursor。
- **96 根视图（观察层）**：`export_24h.finalize_from_ledger` 从连续账本
  状态导出网站快照，bars 只切最近 96 根，meta 带 `view_window=96`、
  `ledger_revision`、`ledger_cursor`；视图不承担历史记忆。
- **线上流程不变其形**：`roll_site phase1`（增量推进 + 写稳定 package，
  无新根/已消费返回 up_to_date）→ 当值 agent 按 BrainSession 契约判读 →
  `roll_site phase2 <btc|-> <eth|->`（canonical 落账 → 视图导出 → 发布）。
  每标的阶段状态记在账本目录 `flow_state.json`（input/package/apply/
  export/publish），失败重跑从失败阶段恢复，不重复调用 agent 或落账。

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
- 不接外部模型供应商（2026-11-01 用户拍板：「先不用模型供应商了，
  你来分析就行」）：判读由当值 agent 按 BrainSession 契约出简报，
  线上 cron 维持 phase1 + agent 判读 + phase2 流程（连续账本语义，
  见上节）；run-once 作为已备好的编排管线留置，将来若改主意接
  供应商再启用。

## 未实现（按方案依赖排后）

- W06 已落程序契约与会话层（brain.py），尚未接真实模型（适配器为 Recorded/Callable，考试与影子接模型时注入）。
- W07 持久影子：PostgreSQL 形态未落，当前为内存 repository 同契约（方案 §12 离线形态）。
- W08 对齐评估、W09–W11 可视化/推演/复盘：未开工。
