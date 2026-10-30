# 审计证据台账 audit-evidence-ledger（2026-10-31 汇编）

性质：只汇编、不评价。每一项只引用仓库文件里写明的数字与结论，
出处逐项标注；文件里没有的写「无记录」。方向栏用语：支持 / 反对 /
不可识别 / 未检验（文件有记载但从未被实验触发）。

## 一、结构 / 规则实证表

| # | 结构 / 规则 | 被什么检验 | 关键数字（照抄出处） | 方向 | 出处 |
|---|---|---|---|---|---|
| 1 | 识别与执法分工（眼认图识别、数据只做附件与执法） | 阿布原图盲考（纯看图）vs 数据特征包同题对照；A/B 输入实验（金标准 6 段，纯数字 vs 数字+图） | 纯看图日型 8 日累计 7.5/8、极值价位误差普遍 ≤2 点；数据包同两天（10-27/28）语境 0/2 且错法相反。A/B：语境一致 A 5/6 vs B 6/6；理由一致两组同为 4/6。处置：图像采纳为判断层标准输入 | 支持（图读识别）；反对（数据包作语境依据，changelog 已废止 trend 标签作语境依据） | brooks-image-exam/SCORECARD.md；brooks-baseline.md；ab-image-vs-data-20261030.md；changelog「识别与执法分工定版」 |
| 2 | H7 条件矩阵（G1 证据卡：R1/R2/R3 必需、V1–V3 否决、维度计数） | 消融 v0.1–v0.5 五轮盲判 + gate 执法 | v0.1：55 份判断 50 份显式审议 G1、零硬凑零维度错位（g1-ablation-v0.1.md）。v0.4：首批 G1 候选 2（死于格式词表，未及 H7 实质）。v0.5：G1 候选 2、**H7 通过 2/2**（修复接线 bug 后口径） | 支持（可成形且可执法）；对 G1 绩效本身不可识别（见 #10） | g1-ablation-v0.1.md；g1-ablation-v0.4.md；g1-ablation-v0.5.md |
| 3 | H1 首目标结算口径 | v0.2 六候选影子双口径对照（首目标 vs 末目标结算） | 首目标 +3.222R（5 胜 1 负）vs 末目标 +3.208R（4 胜 2 负），总账打平、分布不同；用户 2026-10-30 拍板首目标定版 | 两口径无分胜负（文件原话「没有证据支持改结算语义」）；口径已定版 | g1-ablation-v0.2.md；changelog「H1 结算口径定版」 |
| 4 | H1 现价 min 口径（市价计划：计划 RR 与现价 RR 取 element-wise min） | 入场价博弈实验（ds23 计划逐档抬价）+ 金标准回归核对 | 做空入场价 +0%→+2%：承诺净 RR 2.59→7.98、实现 R −1.031→−1.083（承诺与实际反向）；改 min 后两张冻结计划入场价 = 决策收盘，裁决不变、「通过率不下降」 | 支持（堵住分母侧利用） | changelog「特征包补 last_close」「H1 改为现价口径」 |
| 5 | H1 限价入场价基点（限价计划按限價入场价计，2026-10-31 裁定） | v0.5 同批判断在新旧口径下重跑 gate | 旧（现价）：SNX 净 RR −0.013 被拒、候选 3 过 gate 0。新（限价）：SNX 限价净 RR ≈1.62 过 gate、THETA G1 过 gate（G1 首个官方成交样本）；VET 限价口径 ≈1.05 仍被拒 | 支持（按 Brooks v30 slide 34/72/74、v32 slide 38/12 裁定）；样本外绩效未检验 | g1-ablation-v0.5.md 附记；changelog「H1 计价基点定版」 |
| 6 | 职责归位 C（过卡即写候选、数字执法归 gate、pending_conditions 结构化） | v0.1 → v0.2 对照（同底料 fresh 30 段，三项修正 A/B/C 一起改） | v0.1：候选 0/55、pending 为字符串 125 条、gate 拒恒 0。v0.2：候选 6/60（10%）、结构化 pending 60/60、gate 首次真实执法（H1 拒 6） | 支持（三项合改的合并效应；C 单独效应未隔离） | g1-ablation-v0.1.md 附记；g1-ablation-v0.2.md |
| 7 | 事件采样框 v0.2（要塞/缺口点位触及 + 防伪四条） | 消融 v0.2（fresh 30 段） | 60 事件（每段 2、第 60–151 根）；触发率 0%（随机点）→10%；已知局限：事件以要塞触及为主、缺口事件少数、首达偏差 | 支持（采样框可用，定义与防伪已固化）；对 G1 不对口（G1 候选 0） | g1-ablation-v0.2.md |
| 8 | 账本事件采样 v0.3（回补敞开缺口锚的触及根） | 消融 v0.3（同底料） | 51 事件；候选 3（全 B3）、G1 0；G1 挂起普查 53 份：缺 R3 50 次 / R2 26 / R1 9——采样时刻（触及根）早于回补失败行为（到达后 1–3 根） | 反对（作为 G1 采样时刻）；R1 供给有效（缺失仅 9/53） | g1-ablation-v0.4.md（v0.3 节） |
| 9 | 确认窗采样 v0.4/v0.5（到达 + 5 根内首根反向收盘确认根） | 消融 v0.4（fresh 33 事件）、v0.5 预注册复现（fresh2 全新标的 31 事件） | v0.4：G1 候选 2（系统首批）。v0.5 预注册三终点：EP1 G1 候选率 2/31=6.5%；EP2 H7 通过 2/2；EP3 分层 attempts≥1 层 0/4、=0 层 2/27（注册口径无分层信号） | 支持（G1 可成形性，两批全新标的复现）；EP3 分层假设本轮无信号 | g1-ablation-v0.4.md；g1-ablation-v0.5.md；g1-ablation-v0.5-prereg.md |
| 10 | G1 维度分层 L0–L3（消融主问题：逐层加维比绩效） | 五轮消融的分层 runner | v0.1–v0.4：L0 恒空集或 L1–L3 无样本。v0.5（新 H1 口径）：官方成交 2 单均落 L0，L1/L2/L3 各 n=1 系同一单（THETA）的逐层归属、L0 合计 n=2、mean −0.3923R、CI [−0.7042, −0.0804]、proven_edge=false、「样本不足（n=2<30），不下结论」 | **不可识别**（五轮一致结论：G1 不晋升不否决、维持研究级） | ablation-*.json（各轮 summary/layers）；g1-ablation-v0.5.md 附记 |
| 11 | 简单基线（EMA 回调 + 尝试计数）与随机基线 | dev 31 段基线两版（口径修正前后） | v0.1（坏尺子）：simple n=2、+1.4516R（作废口径）。v0.2：simple n=30、胜率 43.3%、mean −0.0237R、CI [−0.4446, 0.3986]；simple_loose n=31、胜率 51.6%、mean +0.1873R、CI [−0.2646, 0.6234]；random n=31、胜率 35.5%、mean −0.2416R、CI [−0.6617, 0.1822]；三者 proven_edge 均为 false | 无优势可证（CI 含 0）；v0.1 的「2 笔全胜」系计量接错线，已作废 | baselines-dev-v0.1.json；baselines-dev-v0.2.json；changelog「P1 三修」「阶段 4」 |
| 12 | 纹理 / regime 原型（整窗纹理聚合分类语境，perception/regime.py v0） | 双考场：阿布日型 2 日 + 金标准 30 段语境 | 日型 2/2（优于现行 1/2）；金标准语境 **11/30**（现行摆动标签 26/30）。失败模式：180 根窗 overlap 普遍 0.57–0.66、efficiency ≤0.24，趋势/震荡不分 | 反对（不过线不许转正；路线已废止，逐腿纹理降为附件参考） | knowledge/specs/context-regime.md；changelog 废止清单 |
| 13 | 现行摆动 trend 标签（trend_state） | 金标准 30 段语境吻合 + 参数变体扫描（P2-9 裁定） | 现状（窗 5 + 2H/2L）26/30（87%）为八变体最优；w=8 → 15/30、w=10 → 10/30、w=12 → 9/30、3H+3L → 19/30、右缘临时摆动 → 15/30。遗留 4 段单向偏空（WIF-15m/ds04/ds06/ds18）。官网盲测语境轴：10-27 判下降（答案转区间）、10-28 判上升（答案区间日），0/2 | 支持（段语境口径下）；反对（作日型标签：无日型层，两日全错） | changelog「两项裁定」；brooks-baseline.md；brooks-pilot-2026-10-28.md |
| 14 | gold-book（阿布原册涂字页为题、本人讲义为答案） | 原册盲考六批累计 | 101 道有效：课眼强命中 31、命中 25、半中 38、错 7；gap_call 轴第五批 9/18（50%）→ 第六批 13/18（72%），第五批两类错法第六批零复发；极性轴三至六批连续全对；管理页累计 7 道不计识别分 | 支持（作为识别考场与回归护栏）；识别分寸短板有记录（次要/主要定级、高潮极性已堵、焦点缺口选择为最新错法） | brooks-book-exam/SCORECARD.md；changelog「gold 重建」 |
| 15 | 执行轴（信号 K 极值 stop 触发 vs 多等一根确认） | 执行轴盲考 v1：阿布箭头 7 个决策点对照回放 | 方向/出手对齐 **1/7**；5 不做、1 反向；dp4 满分（入场与阿布分毫不差、+1.68R vs 参考 +0.75R）；系统性错法 = 触发点多等一根确认（dp1/dp2/dp6 理由均为等第二腿/强信号/更深回踩） | 反对（现行触发纪律）；识别轴同日 7.5/8 与执行 1/7 并存（文件原话「识别 ≠ 执行」） | brooks-exec-exam/SCORECARD.md |
| 16 | S1–S3 软规则（抛物线/踩踏/衰减降仓 ×0.5） | 接线审计 + 测试登记 | changelog 明载：`flags` 参数无任何生产者，「S1–S3 在所有真实回放里一次都没触发，降仓层至今是空的」；S1 判据（parabolic）登记 PENDING（需新常数、无样本与原册依据前不设）；S1/S3 的 RR 条件曾退化为恒成立死代码，已按甲案去掉、改为无条件降仓 | 未检验（从未在真实回放触发）；接线未全修 | changelog「软规则去掉 RR 条件」「设计目标盈亏比 2:1」；gate/tests/test_wiring.py（PENDING 登记） |
| 17 | H6 模式停牌台账（样本 ≥3 且 0 胜停牌） | 各轮 runner 的 h6_active 字段 + gold-run notes | 消融/试点各轮 JSON：h6_active 恒为 False；gold-run-v1 notes：「H6 未生效：台账无 B3×下降 样本（n=0）」。接线 bug 已修（context 须枚举、未生效须写 notes，见 §二 #8） | 未检验（台账始终无样本可触发） | ablation-fresh-v0.1.json；ablation-devplumb-v0.1.json；pilot-dev10-v0.1.json；gold-run-v1.json |
| 18 | H2 止损结构外（大小级别摆动合并取最近） | 外部复核放行单 DOT A2 过裁决实测 | 旧实现只看大级别：DOT 止损 1.585 被误杀（第二腿高点 1.576 仅小级别摆动）；改合并后通过，揭盲 +2.93R（第 12 根达目标），净 RR 2.83 与复核计算一致 | 支持（修正后口径） | gold-adjudication-sheet.md 已定版 2；changelog「H2 修正」 |
| 19 | 凯利分层仓位（gate/sizing.py：1% 生存顶 + 1/4 凯利 + 证据闸门） | 本系统自有样本回算（提案，未生效） | 金标准 2 单：全凯利 32.4% / 下界版 0；simple_loose 31 笔：9.2% / 0。实测分工：n=15 凯利愿给 1.4% 被证据闸门压 0；n≥30 后 1/4 凯利 2.4% 被 1% 上限压。当前 stage：金标准 explore、31 笔基线 no_edge，「现在正确的仓位是 0」。core 红线 3 仍为 1%，提案未生效 | 未检验（未生效、无前向样本）；文件结论为分层保留而非凯利替换上限 | changelog「凯利公式提案」「凯利补充」两节 |
| 20 | 设计目标 RR 2:1（毛口径）与地板 1.5 的关系 | scan 配对实验（同入场点、目标倍数 1.0–3.0R） | 9 笔配对：1.0R 66.7%/+0.300、1.5R 55.6%/+0.356、2.0R 33.3%/−0.033、2.5R −0.644、3.0R −0.589（均 R 在 1.5R 见顶）；文件明载 n=9 决定不了任何事（2.0R 多一胜即 +0.29）。另：地板若设 2.0 净，毛 2:1 单净 RR 1.820–1.976 → 9/9 全拒，故地板留 1.5 | 不可识别（n=9）；地板不抬有几何证明（min_stop_frac_for_floor(2.0) 无解） | changelog「设计目标盈亏比 2:1」「软规则去掉 RR 条件；地板不能抬到 2.0 净」 |
| 21 | 外部复核对账（判断层草稿 vs 外部 AI 盲审 41 段） | review_diff 对账 | 语境一致 33/41（80%）、结论一致 17/41（41%）；分歧 26 段中 24 段为草稿 candidate 被复核砍单（主因位置不对）；两放行单双方一致（ds23 净 RR 2.59、DOT 2.83） | 草稿口径过宽（反对）；细审口径下双方在放行单上一致 | review-diff-v0.1.md；gold-adjudication-sheet.md |
| 22 | gold-run v1 判断层成绩（旧 gold，已删） | 30 段冻结标注重跑（两轴记分） | 格式 29/30、结论轴 28/29=96.6%、语境轴 28/30=93.3%、理由轴 17/27=63.0%；唯一成交 ds23 −1.0314R。changelog 已定性：旧 gold 标注者读我方知识卡判卷属自产自销，整集删除、成绩只作历史记录、不再是合入门槛 | 历史记录（底料已废，成绩不可再引用为证据） | gold-run-v1.md；changelog「gold 重建」 |

## 二、接线 / 口径 bug 清单

| # | 名称 | 影响（文件记载） | 已修 | 出处 |
|---|---|---|---|---|
| 1 | 旧 gold 自产自销底料 | 外部 AI 按我方知识卡标注充当 ground truth；v0.1 第一批旧 dev 判读亦因此只作管线验证 | 是（整目录删除，gold-book 以阿布原文重建） | g1-ablation-v0.1.md；changelog「gold 重建」 |
| 2 | 判断层从未附图（违背眼/数据分工） | v0.1 的 55 份判断全靠文本；「成色不合格」占空仓 38%，被记为质地判断被数字压扁的症状 | 是（v0.2 起双通道为标准管线） | g1-ablation-v0.1.md 附记 |
| 3 | pending_conditions 字符串形式 | 125 条 pending 不可机读、近失信息丢失 | 是（结构化对象 {setup, missing[], watch}，v0.2 起 60/60 结构化） | g1-ablation-v0.1.md 附记；g1-ablation-v0.2.md |
| 4 | A/B 批格式全军覆没 | 12/12 缺 primary 字段；hypotheses 形状即兴 5 例；校验器遇对象式 hypotheses AttributeError 崩溃打断打分 | 是（校验器报错不崩 + 回归测试；提示任务段置顶契约骨架。此后各轮格式合规：v0.2 60/60、gold-run 29/30、v0.5 0 失败） | ab-image-vs-data-20261030.md |
| 5 | H1 入场价博弈洞 | 入场价往有利方向挪可无界放大承诺 RR（+2% → 7.98）而实现 R 反向恶化（−1.083），H1/H2/H3 全程无阻力 | 是（补 last_close 字段 + 现价 min 口径；限价单 2026-10-31 另行裁定豁免，见 §一 #5） | changelog「特征包补 last_close」「H1 改为现价口径」 |
| 6 | H1 按末级目标计价 | 加一个远目标即可过 1.5 门槛（「目标改近」的反向利用），与回放首目标结算不同口径 | 是（改首目标计价） | changelog「裁决层与 core 对齐 P0-2」 |
| 7 | H3 上限 1.5% 与 core 1% 不一致 | 代码沿用方案原文，未随冻结口径收窄 | 是（收窄 1%，加断言） | changelog「P0-1」 |
| 8 | H6 静默失效（context 自由文本） | pilot 把假设 statement 文本当 context，(setup, 语境) 台账键永不匹配，停牌规则等于没接线 | 是（context 须枚举、取感知 trend.label、未生效写 notes；CLI/gold_run 同步接线） | changelog「P0 三修」「复核五处 ②」 |
| 9 | H4 适用范围错误 | 标注/试点的决策点（第 180 根）被 trainer 局内 Bar 140 截止字面误伤 | 是（adjudicate 加 mode，H4 只管 trainer） | changelog「P0-3」；gold-adjudication-sheet 已定版 1 |
| 10 | H2 整数关口判据死代码 | `abs(stop−round(stop))<0.02×seg_avg` 只对整数报价资产成立，1.58 类价格永不命中 | 是（按价格量级取关口步长 mag/20） | changelog「P0 三修」 |
| 11 | H2 只看大级别摆动误杀 | DOT A2 合理止损被判结构内（见 §一 #18） | 是（大小级别合并） | gold-adjudication-sheet.md；changelog |
| 12 | MM 未组装进 pack | mm_project() 函数存在但未进特征包——「写了没接线」第三例（前两例 H6、flags） | 是（全 major 腿去重限量组装；复测 10-27 投影回归覆盖 7800 一带，10-28 仍无 7818 候选系其 major 腿碎裂传导） | brooks-pilot-2026-10-28.md；brooks-baseline.md 复测进展 |
| 13 | flags 无生产者 → S1–S3 从未触发 | fortress 的 decaying/trampled 未翻成 flags；parabolic/second_bar_confirmed 无测量函数 | **否（部分登记）**：parabolic 判据登记 PENDING；S2/S3 生产者无记录已补 | changelog「软规则去掉 RR 条件」③；gate/tests/test_wiring.py |
| 14 | simulate_limit_trade 死代码 | 无任何调用方：限价单被当作以限价直接成交（正是限价口径要防的高估），未成交单不留档 | 是（新增 simulate_plan 按 order_type 分派，两运行器改用，未成交单独留档） | changelog「限价口径接进回放」 |
| 15 | 费用双轨 | schema 只认 order_type、gate 只读 limit_in（限价单按市价费率算 RR）；回放硬编码 FEE=0.0005 与 config 两套账 | 是（gate 以 order_type 为准、回放统一读 config；金标准回归值 DOT 2.926202 / ds23 −1.031392 不变） | changelog「复核五处 ③」 |
| 16 | 召回自样本泄漏 | prompt 召回只返回 ex-APT+ex-ARB 两条且不排除自身，样本提示里出现自己的 draft_verdict | 是（排除自身/同标的重叠窗、只从 dev 池、分桶轮转） | changelog「复核五处 ①」 |
| 17 | 评估链路依赖 numpy | 顶层 import numpy，本机无 numpy 时 gold_run/gold_build 整体起不来 | 是（bootstrap/分位改纯标准库） | changelog「复核五处 ④」 |
| 18 | 基线窗口残留旧口径 | baselines 入场窗 WARM/END=30/170（红线 4 旧截止残留）、结局跑到段末最长 420 根（比主系统多 120 根前向 K） | 是（决策点 180、固定 300 根生命周期，fee_x2 同窗重算） | changelog「P1 三修」 |
| 19 | route_cards 永不带 C1/B2 | MTR 整族在提示里不可达、B2 无入口 | 是（按 router.md 四类语境重写，每类 ≤3 张） | changelog「P1 三修」 |
| 20 | features.net_rr 两套实现漂移 | 特征包版长/空分支同体、入场费重复计、出场费按入场价计，且无调用方（死代码） | 是（perception 侧为唯一实现，裁决层薄包装） | changelog「P1 三修」 |
| 21 | 尝试计数与 A1 两腿口径冲突（基线触发率之谜） | count_entry_attempts 要求先创新低才计第二次，与 A1 允许更高第二腿低点不是一回事；漏斗 4650 根 → attempts≥2 仅 30 → 2 段出信号 | 处置完成（计数器语义经用户裁定保留并写死 docstring；新增 count_pullback_legs 与 pullback.legs/two_legs 字段：dev 31 段两腿以上 10/31=32%，对照 attempts≥2 的 2/31） | changelog「P1 三修」「两项裁定 ①」 |
| 22 | trend 标签与账本冲突未标记 | ds18 标签下降 −2 而 6 条敞开缺口全套空头，冲突不可见 | 是（新增 trend.gap_consistency 与 trend.window） | review-diff-v0.1.md；changelog「感知层三修」 |
| 23 | pullback.dir_against 语义反转 | 旧实现以最后一条腿为参照，段尾回调时输出顺势腿方向 | 是（参照改趋势标签方向，新增 pullback.expired） | review-diff-v0.1.md；changelog |
| 24 | 低价标的精度压零 | ds19 seg_avg_range 被 round 成 0.0 | 是（precision.r6，10 位有效数字） | review-diff-v0.1.md；changelog |
| 25 | build_fresh 切割窗 bug | 上市晚标的种子窗落在历史不足 480 根处，旧重试整窗回跳只会更糟 | 是（先查上市时间抬高下限、失败只挪一根） | g1-ablation-v0.1.md |
| 26 | event_run / pilot_run 漏并 conditions | plan 组装漏并候选 conditions 与 strongest_countercase，H7 将两张矩阵完整的 G1 误判「缺条件矩阵」（首跑 H7 命中 16 次为假象） | 是（共享 helper merge_candidate_terms + 回归测试 test_runner_merge_feeds_h7，全仓 170 passed） | g1-ablation-v0.5.md |
| 27 | 候选格式损耗（void 散句 / role 词表） | 两轮 9 个候选中 3 个死于格式（33%）：v0.3 一单 void 写成散句；v0.4 两张 G1 的 role 写成 enhancement（词表 enhancing） | 是（提示补 void 结构与 role 词表明示；v0.5 验证格式失败 0/31） | g1-ablation-v0.4.md；g1-ablation-v0.5.md |
| 28 | v0.3 采样 overlap 标记过松 | 要塞带宽含住锚即算，50/51 为 True，分层不可用 | 否（报告已声明不可用，分层改用判读 conditions + runner 严格口径；标记本身无修复记录） | g1-ablation-v0.4.md 方法变更 2 |
| 29 | trend_age.legs 结构性退化 | 主级别摆动 H/L 交替、同向腿不可能相邻，该字段在 dev 31/31 段恒为 1 | 否（记为待裁定的感知层缺陷，无修复记录） | changelog「P1 三修」路由节 |
| 30 | 要塞带粒度不稳 | 10-28 支撑并入 7757–7782.25 巨带（宽 25 点、测次 79 无分辨）；10-27 碎成 7 条微带；测次口径随带宽漂移 | 否（记账待改，无修复记录） | brooks-pilot-2026-10-28.md；brooks-baseline.md |
| 31 | 感知尺度与短窗不匹配 | 81 根日盘窗 major 尺度前 29 根无摆动/腿，真主腿 38 点未成腿 | 部分（尺度适配 v1 落地：短窗 <150 根 major 窗降到 3，10-28 首腿出现、起点 7751.5 ≈ 答案 7752；但 10-28 全天标签仍为上升，「无日型层」继续挂账） | brooks-baseline.md 复测进展 #2 |
| 32 | 原册涂字漏网（book_exam_mask） | 彩色文字不在 pdftotext 词框枚举内，累计 3 例漏涂（v15-s127 红字、v11-s5 橙字行、v29-s44 副标题行），个别题记分因此降档 | 否（处置为抽题时人工抽查图面残字，无工具修复记录） | brooks-book-exam/SCORECARD.md 第六批注 |
| 33 | 回放不执行前提失效（红线 5） | void_if 无受限表达式与解释器，回放不执行前提破出场 | 否（列入未修清单） | changelog「复核五处」仍未修清单 |
| 34 | second_bar_confirmed 靠自声明 | 判断层自报、无样本外核对机制 | 否（列入未修清单） | changelog「复核五处」仍未修清单 |
| 35 | examples 池无 split 字段 | knowledge/examples 未纳入隔离模型（召回隔离靠 builder 侧 dev-only 规则兜底） | 否（列入未修清单） | changelog「复核五处」仍未修清单 |

## 三、官方成交样本现状（按口径分列，不合并）

| 口径 | 官方成交 n | 明细（文件记载） | 出处 |
|---|---|---|---|
| 消融 v0.1（随机决策点，55 点） | 0 | 候选 0、gate 拒 0、成交 0；L0 空集 | g1-ablation-v0.1.md |
| 消融 v0.2（事件采样 60） | 0 | 候选 6、过 gate 0（H1 拒 6、其中 1 单兼 H2）；影子回放 6 单不算官方成交 | g1-ablation-v0.2.md；ablation-events-v0.2.json |
| 消融 v0.3（账本事件 51） | 0 | 合格 2、gate 拒 2（H1×2、H2×1 条目计数）、另 1 候选死于格式 | ablation-gap-events-v0.3.json |
| 消融 v0.4（确认事件 33） | 0 | 合格入 runner 1、gate 拒 1（H1）；另 2 张 G1 死于格式未入 runner | ablation-confirm-events-v0.4.json；g1-ablation-v0.4.md |
| 消融 v0.5（确认事件 31，新 H1 限价口径） | **2** | SNX B3 空 −0.704R（void 出场）、THETA G1 空 −0.080R（void 出场）；summary n=2、win_rate 0、mean −0.3923R、CI [−0.7042, −0.0804]、样本不足不下结论。VET G1 被 H1 拒（限价口径 ≈1.05），其影子 +1.053R 不算官方 | ablation-confirm2-events-v0.5.json；g1-ablation-v0.5.md 附记 |
| 消融五轮官方成交合计 | **2** | 均为 v0.5、同为 void 出场小亏；全部官方样本即此 2 单 | 同上 |
| 阶段 5 试点（dev 前 10 段） | 0 | judged 10、no_trade 10、裁决拒 0、成交 0（只验通空仓路径） | stage5-pilot-v0.1.md；pilot-dev10-v0.1.json |
| gold-run v1（旧 gold 30 段，已删集） | 1 | ds23 B3 空 −1.0314R（第 23 根触损）；底料已废，成绩只作历史记录 | gold-run-v1.md / .json |
| 外部复核放行单对账回放 | （与上行同一批，不另计） | ds23 −1.03R、DOT A2 +2.93R——系标注对账的揭盲回放，ds23 与 gold-run 的成交为同一单 | gold-adjudication-sheet.md |
| 简单基线（机械基线，非判断层样本） | simple 30 / simple_loose 31 / random 31（dev） | 见 §一 #11 | baselines-dev-v0.2.json |
| 逐根扫描去重叠样本（changelog 台账节） | 11 笔 | 50 段原始信号 96 个、去重叠后 11 笔（A1 5 胜 2、A2 6 胜 3 的原文记法），胜率 45.5%、b=1.43——系扫描基线口径，非判断层官方成交 | changelog「台账 v1 + 逐根扫描」 |
| trainer 新批（预演制计分局） | **本仓库无记录** | pa-system 仓库内未见 trainer 新批的局数/成交数记载（批次日志不在本仓库） | —（检索 eval/reports、changelog、knowledge 无果） |
| 执行轴盲考（对照回放，非系统成交） | 不计 | 盲判实际下单回放仅 dp4 +1.68R、dp5 +1.5R（路径运气）两笔有 R，其余 5 点为漏单 | brooks-exec-exam/SCORECARD.md |

## 四、汇编口径说明

- 「官方成交」= 判断 JSON 经 validate → gate 通过 → runner 回放落账的单；
  影子回放（绕过 gate 的诊断数）一律不计，并在表中注明。
- 同一单在不同报告出现（ds23 见于 gold-run 与外部对账）只计一次。
- 结论方向只转述文件原话的定性（如「不可识别」「不下结论」「不过线」），
  本台账不新增判断。
