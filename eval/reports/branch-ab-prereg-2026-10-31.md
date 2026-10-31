# 分支预写 A/B 验证预注册（2026-10-31，用户拍板）

## 干预

judge/campaign_prompt.py 的 MAP_TASK 新增「分支预写三条款（硬性）」
（跟进锚定 / 叠加上限 / 引用价锚定，全文见 campaign_prompt.py 与
branch-trigger-autopsy-2026-10-31.md 的拟改条款）。点位对齐条款与
投影条款不变。生产影子自此吃新口径（build_map_prompt 一处共用，
与对齐条款同例）。

## 设计

- 总体：触及实验同一批 55 个事件（eval/touch-ab/population.json），
  快照、触发根（map_bar）、决策图全部复用。
- C 臂（本实验）：按新 MAP 任务重画地图（maps2），到达判读按触及
  口径（提示与 touch B 臂逐字相同：分轨认定 + 覆盖块），唯一变量
  = 地图预写口径。
- 基准：touch B 臂——qualified 2（均 B3）、已解析 1 笔 −0.3607R、
  1 笔未解析（本实验 score 前先复跑 touch score 更新基准）。
- 操作检查（manipulation check）：maps2 全部 branches 的 trigger
  文本统计（跟进出现率、条件叠加分布）与同 55 事件旧图同口统计
  对照——先确认三条款真的改变了预写，再谈产出。
- 指标：qualified 数（主指标，对基准 2）、按 setup 分布、violations、
  gate 拒绝、tracked 与逐单 R、每机会 R。点位重画带来的命中率变化
  （触及口径下被测位 ∈ maps2 点位比例）一并报告，作噪声登记。
- 污染防线：地图/到达判读员禁读旧 maps、旧 judgments 与任何报告；
  地图判读只读 map 提示 + 触发根图，到达判读只读到达提示 + 决策图。
- 本实验只验证预写口径对产出的影响；三条款已随用户拍板进生产
  提示，实验结果用于决定保留、加严或回退，不自动再改。
