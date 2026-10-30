# 阿布原册锚点审计：Brooks 本人在六个议题上的明确做法

抽取范围：`knowledge/brooks-cases/raw/*.jsonl`（Brooks Trading Course 讲义文本层）。
规则：只收语料里明文写到的，每条给 video + slide 出处与英文原文摘录（OCR 有
个别字符噪声，语义以原页为准）；语料没有的，直说未覆盖，不补训练知识。

---

## 1. 入场方式：stop / limit / market 的场合与偏好

**总纲（v32《订单》）**：stop 单是默认，新手只应用 stop 单；limit/market 是
熟手工具，与 stop 单同等有效。

- v32 s3：「Most traders should almost always enter with stop orders.」
  四种订单（stop / limit / bracket / market）里，stop 是入场默认。
- v32 s29/s32 目录页：「Stop orders are better for most traders ■ Skilled
  traders use market and limit orders」。
- v32 s30：新手条款 + 机械口径——「Beginner should only enter with stop
  orders」「place buy stop order 1 tick/pip above high of prior bar (which is
  signal bar)」「Put initial protective stop 1 tick/pip below signal bar」；
  目标「at least as large or 2x as large as stop (risk)」。
- v32 s38：「Stop Orders and Limit Orders: Are Equally Effective …
  Beginners should only use stop orders (or market and limit orders in the
  direction of strong trend) … Expert traders can use limit orders about as
  often as stop orders」。
- v32 s31：stop 单的禁区——「Stop orders are bad in Tight Trading Ranges.
  Breakouts fail so stop orders lose money. Good during swings or trends.
  Entering with stop order is buying or selling BO of prior bar, betting on
  profitable BO」。
- 区间里 limit 才是唯一解：v18 s108「Range is too tight to make money with
  stop order entries … Only way to make money is entering with limit
  orders」；v12 s21/s27 通道转区间的标志动作就是在旧高/旧低挂限价
  （"Limit Order Bear" at old high / "Limit Order Bull" at old low）。
- limit 成交条件：v32 s12/s13「market usually (90% of time) has to go
  through the limit order price before order is filled」；限价止盈同理
  （v30 s97：通常要越过限价 1 tick 才成交）。
- market 单的场合：强趋势里按收盘市价进——v41 s16「Simplest approach is
  to buy at the market as soon as bar closes (Buy The Close)」；v8 s94 强
  多头「Buy for any reason: Buy at the market, buy above and below bars,
  buy bull and bear closes」；宽区间强反转也可用市价（v18 s105「Broad
  TR: enter with market orders when strong reversals」）。

## 2. 入场时机：买收盘 vs 等回踩 vs 等第二次；对「多等一根确认」的态度

三种时机他都用，是**概率与价格的交换**，不是纪律问题：

- **突破当根买收盘**（强突破的标准打法）：v30 s80「Strong bull BO …
  Buy the close」；v10 s41「Buy close of BO bar or follow-through bar」；
  v18 s164「Buy close of big bull breakout bar」。
- **等跟进根（follow-through）再买**：与买收盘并列为合法选项，且他明说
  代价——v22 s16「Higher probability to buy after strong bull BO. Pay for
  it with greater risk. Stop now far below. Buy close of follow-through
  bar」；v10 s40「Buy close, or wait for follow-through to buy」。
  有时跟进根本是确认的必要条件：v13 s12 突破后「need 1 more bar to
  confirm breakout and reversal (follow-through bar)」。
- **等回踩**：有警告——v14 s11「Beginner wants smaller stop. Wait for
  pullback. Pullback does not come for many, many bars. Miss most of
  trend, and most of profit!」；但回踩位挂限价是熟手常规（见 §1 v30
  50% PB 限价单，§3）。
- **第二次入场（H2/L2）是他体系的命名入场点**：v1 s12「In bull trend,
  look for High 2 (H2) pullback … Buy on stop above high of signal bar」；
  v1 s13 L2 镜像「Sell on stop below low of signal bar」。即第二次入场
  本身就是触发机制，用 stop 单在信号 K 外成交，不再另等确认根。
- **对弱信号「多等一根」**：他支持等——v8 s90 弱卖信号「probability of
  profit is low. Can increase probability by waiting for more
  information … Wait for strong bear BO, then sell. Wait for
  follow-through, so now Always In Short」。
  小结：他没有「永远多等一根」的通则；强突破买收盘、弱信号等确认、
  回踩用限价/第二次入场，都是语境分支，「等」买的是概率、付出的是
  止损变远与踏空风险。

## 3. RR 标准：等式最低要求、2:1 是否硬线、概率如何补偿

- 等式本体（v30 s12）：「Only take a trade if (Probability of win) x
  (Reward) > (Probability of loss) x (Risk)」。
- 锚点在入场价（v30 s34）：「Risk = number of ticks/pips to protective
  stop. Reward = number of ticks/pips to profit taking limit order …
  Most traders want profit at least equal to initial risk」——**底线是
  reward ≥ risk（1:1），不是 2:1**。
- v13 s18 同口径：「When enter, want reward at least equal to risk.
  Better if target is at least 2x risk」——2x 是「更好」，非硬线。
- **Swing 的口径才是 2x**：v31 s9/s10「Reward should be at least twice
  as big as risk」（波段最低目标）；v34 s14「Reasonable minimum reward
  is 2x Initial or Actual Risk. Always results in positive Trader's
  Equation」。
- **Scalp 允许 1x，靠概率补偿**：v30 s67 强熊趋势「Decide on logical
  place for stop. If stop is X ticks away, hold for target X ticks
  away」；v30 s100 强突破 scalp 在 1x initial risk 止盈，「Trader's
  Equation was positive because probability was 60%」；v30 s72/74/78
  50% 回踩限价单 risk = reward，靠「about 60% chance」撑正等式，并
  直言「High probability means bad RR」。
- 反面边界：scalp 若 reward 远小于 risk 又无管理，胜率要求苛刻到不可行
  ——v35 s42「When reward is small compared to risk … Without good
  management, need to win 90% to breakeven」。
- 最小 scalp 尺寸是另一回事（绝对值，不是 RR）：v31 s43 5 分钟 Emini
  「minimum profit target … 4–8 ticks」；v31 s45「Minimum scalp is the
  bigger of: height of average recent bars / 5–10% of average recent
  daily ranges」。

## 4. 止损：放哪；Actual Risk 与 Initial Risk

- **Initial Risk**（v34 s14）：「Initial Risk is from entry price to
  below signal bar」——入场价到信号 K 外（v32 s30：1 tick 外）的距离，
  下单时定的初始止损。
- **Actual Risk**（v34 s9/s10）：行情走出一段后回看，「the closest stop
  that would have prevented them from being stopped out」——即实际走
  势中本可以放的最近的「完美止损」到入场价的距离，通常小于 initial
  risk（v21 s92「Initial Risk was small and Actual Risk was even
  smaller」）。
- 用法分工（v34 s11/s12）：机构/程序用 Actual Risk 算止盈位——「take
  profits at only 1x Actual Risk … Computers often use Actual Risk to
  calculate where to take profits. So should you!」「Many take profits
  at 2x Actual Risk. When probability is high, 1x is okay」；但 Actual
  Risk 太小时不能拿它当止盈尺（v34 s20「Small Actual Risk is useless
  … use other support or resistance: Measured Move targets, prior
  highs and lows」）。
- 止损位置的本体是**价格行为止损**：v33 s40「Most reliable stop in bull
  is below bottom of current leg up」（信号 K 小、可能还有回踩时，
  止损放本腿底部外，而不是信号 K 外）；v13 s75「Do not put stop below
  HL (minor low) if last rally was not strong bull BO … Correct stop is
  below bottom of bull leg」；Always In 语境则放最近突破的底部外
  （v13 s18/s36「Protective stop below bottom of most recent breakout /
  below bottom of bull leg」）。
- 备选是 money stop（固定点数）：v33 s104/s105「consider wider stop:
  Money stop, like 2 points / 10–20 pips … Measured Move stop …
  trading small and adding on」。
- 宽度权衡（v33 s107）：「Any reasonable stop is good. Wider stops give
  higher probability … Not too small because low probability; not too
  big because risk too big」；v41 s12「As long as stop is reasonable,
  results are same after 100 trades … Choose what suits your
  personality」。

## 5. 概率观：他给典型 setup 的数字

- **MTR / 主要反转尝试：40%**。v11 s23「most major reversal attempts
  lead to PB or TR. Only 40% of attempts lead to opposite trend」；
  v11 s24/s26 图上直标「40% chance of bear/bull swing」。
- **80% 惯性律**（v15 s11）：「Only 10% of bars are in a strong
  breakout that has follow-through. 90% of bars are in channels or
  TR. In channel or TR, 80% of breakouts fail to go far」；v15 s21
  「80% of breakouts in TRs fail and reverse. 80% of reversals in
  trends fail and become flags」；v14 s17「Trends have inertia: 80% of
  reversal attempts fail」。
- **强突破后的 MM：60–80%**。v31 s7「Probability of Measured Move up
  is high (60–80%)」；v50 s3 强突破少重叠时「70% chance of at least a
  Measured Move up」；v30 s80 好语境强突破「High probability (60% or
  more) of reward at least as big as risk」。
- **50% 回踩顺势：约 60%**（v30 s72/75/78，见 §3）。
- **H2/L2 的通用概率数字：语料未覆盖。** 只有 v30 s49 一个具体交易
  系统示例（2nd entry reversal scalp 系统 12 笔中 11 胜的回溯展示），
  不是他给 H2 的一般概率标定，不可当锚点用。
- 楔形的独立概率数字：语料未覆盖（楔形出现在 MTR 语境时随 MTR 的
  40%，如 v11 s26）。

## 6. 分批 / 加仓：scaling in 与分批止盈

两者都明文存在，且是熟手管理的核心件：

- **Scaling in（逆势小步加仓，前提是宽止损 + 小仓位）**：v33 s33
  「Experienced trader often uses wide stop … Trades small if might
  scale in … Buys more below signal bar」；v35 s10 不会加仓的新手只能
  「wait」，而「scale in traders might add」在回踩里继续买；v30 s100
  强突破 scalp「Buy the close … Buy more lower (scale in)」；v18 s74
  区间 BLSHS「Use wide stops, scale in … Buy more lower (scale in) for
  scalps」；v16 s178 顶部/底部反转「experienced traders will enter
  with limit orders and scale in, betting on reversal」。
  效果自述（v35 s42）：「Experts improve probability by scaling in …
  probability can be 80–90%」，且「Expert will rarely let stop get
  hit, reducing risk」。
- **分批止盈（take half off 起步，有成文配比）**：v21 s92「Take at
  least half off at 1st target」（目标 = 2x risk 处）；v36 s21 给出
  完整阶梯：「Can take half off at 2x Actual Risk. Take another 25%
  at 3x Actual Risk. Swing final 25% … Always acceptable math to take
  profits at twice Initial or Actual Risk (as long as bigger than
  minimum scalp)」；v34 s13 scaling in 的第一仓在回本位出场
  （「Breakeven on 1st entry」+ 第二仓赚 scalp）。

---

## 审计备注（抽取口径）

- 本文件只做「阿布怎么说」的事实层，不含与本系统结构的对照裁定。
- 引用页均为讲义幻灯片文本，图内标注与正文混排，个别摘录顺序经
  轻微整理；需要逐字核对时按 video + slide 回 raw jsonl 原页。
- 未覆盖项已在正文标明：H2/L2 通用概率、楔形独立概率。
