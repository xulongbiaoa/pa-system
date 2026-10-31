# W09 战场可视化：战略沙盘（主） + K 线核验页

**主舞台是沙盘 `sandbox.html`**（形态 = 用户 2026-10-31 给定的参考图：深色皮肤照抄、K 线主图 + 右栏简报/四段计划 + 事件时间线 + 多空行动对照）：用户两条口径钉死——① 支撑/阻力是**带**（账本位置的 watch 带）；② **缺口是锚线、画在带的最外沿**（支撑带最下面 / 阻力带最上面，价格须穿透整条带才碰到锚线、碰到即销账，仍是定版 v0.2 单线生死）。无缺口的一侧画最近 major 摆动带并明示「无缺口」。T1/T2 标记 = 缺口回补测试起点；时间线只走缺口生命周期事件（export 须全量保留该类事件，export_web 与 export_24h 均已处理）；多空对照 = 双侧最近一段的净推进/回吐/用时。MM 目标位未画：targets 未接线，不自算冒充

`sandbox.html` 打开即沙盘；`index.html` 为 K 线核验页（§18 的四块界面与 AS_KNOWN 模式在该页），两者同读一份快照、页眉互链。

两页都不做缺口或攻守识别，只渲染 `battlefield/export_web.py` 经 **QueryService** 导出的快照——与 AI 判读同一状态源、同一 snapshot token。

## 运行

沙盘（主）读 24h 数据，核验页读影子全史数据，两条导出分开：

```bash
cd ~/workspace/pa-system
# 沙盘：15m × 24h（96 根）新鲜战场（用户 2026-10-31 定版口径）
python3 -m battlefield.export_24h prepare BTCUSDT   # 抓数建场，出待判包
python3 -m battlefield.export_24h prepare ETHUSDT
# 判读员读 data24/pkg_<SYM>.json 出简报后：
python3 -m battlefield.export_24h apply BTCUSDT <判读输出.json>
python3 -m battlefield.export_24h apply ETHUSDT <判读输出.json>
python3 -m battlefield.export_24h finalize BTCUSDT  # 出 data24/<SYM>.json
python3 -m battlefield.export_24h finalize ETHUSDT
# 核验页：影子全史快照
python3 -m battlefield.export_web                   # 出 web/data/{BTCUSDT,ETHUSDT}.json
cd battlefield/web && python3 -m http.server 8901
# 打开 http://127.0.0.1:8901/sandbox.html（沙盘）或 index.html（核验页）
```

`web/data/` 是生成物（gitignore），改账本后重跑导出即刷新。本机 Chrome 直连 127.0.0.1 可能被 Local Network Access 拦截，验收截图走 puppeteer 请求拦截供文件（脚本范例 `~/workspace/.tmp/shot_w09.js`）。

## 口径

- **LIVE** = 最新投影；**AS_KNOWN** = 按每份大脑输出的 read_cursor 截断（K 线截断、事件按 confirmed_at 过滤、假设按 hypothesis_ops 折叠重演、计划取当时版本），并显式标「历史时点，非当前判断」。
- 页面数据本身即账本重放重建（**RECONSTRUCTED** 口径，算法 = 当前代码），页脚明示 token、生成时间、范围与来源。
- AI 已复核至当前 revision 时显示「已复核」；若落后，假设面板带「基于旧快照，待复核」陈旧标记（代码路径已实现；当前账本 ai cursor = revision，截图中为已复核态）。
- 图层按距现价最近优先：缺口锚线最近 10、主要地形最近 8、事件标记最近 250 根，折叠数量明示，不静默隐藏。
- 批注存浏览器 localStorage（键 = snapshot token），独立于事实，不回写账本。
- 纯静态只读：无轮询、无下单、无模型调用入口（§18.3 的 HTTP 轮询与增量 cursor 留待滚动影子恢复后接）。

## §18.8 验收对照（v1）

1. 同 token 一致 ✓（导出 token 与影子 pending 包 token 逐字相同：`BTCUSDT|15m|r1000|1793443499999`）
2. 测试计数画在锚线标题（测N），复核（大脑输出）单列于模式菜单，两者不混 ✓
3. 陈旧标记 ✓（代码路径 + AS_KNOWN 历史标记已验）
4. 乱序响应：v1 单快照整批替换，无增量请求，天然免疫；轮询未做（见上）
5. AS_KNOWN 回放无未来 K 线/事件/解释 ✓（截图验）
6. 批注（蓝）/假设（卡片）/事实（图与时间线）视觉可区分 ✓
7. 点击引用定位证据 ✓（gap_id 跳立账根、ev- 跳事件并居中）；不存在的引用不伪装定位 ✓
8. 浏览/切换不触发下单与模型调用 ✓（纯静态）
9. 数据健康异常有独立徽章（缺根/断裂）；unknown 与等待未并入 no_trade 概念（本页无 no_trade 文案）✓
10. 范围/版本/更新时间在页脚与顶栏明示；无兵力/胜率类虚构数值 ✓（双方行动只列事实段向量）
