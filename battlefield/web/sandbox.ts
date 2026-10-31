// W09 战略沙盘 v3（用户 2026-10-31 给定目标形态 + 两条口径）：
// 形态照用户参考图：K 线主图 + 带 + 右栏简报/四段计划 + 事件时间线 + 多空行动对照；深色皮肤照抄。
// 口径一：支撑/阻力是带（据点/要塞的价格带，取账本位置的 watch 带）；
// 口径二：缺口是锚线，画在带的最外沿——支撑带的最下面、阻力带的最上面
//        （价格须穿透整条带才碰到锚线，碰到即销账，仍是定版 v0.2 的单线生死）。
// 数据 = export_24h 的 15m×24h 快照（data24/）。本页只做展示聚合，不新造事实数值；
// MM 目标位未画：targets 尚未接线，不拿自算数字冒充系统目标。
declare const LightweightCharts: any;
type AnyObj = { [k: string]: any };

const CST = 8 * 3600;
let snap: AnyObj | null = null;
let chart: any = null, candleSeries: any = null;

const $ = (id: string) => document.getElementById(id)!;
const fmtTc = (ms: number, withDay = true) => {
  const d = new Date(ms + CST * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${withDay ? `${d.getUTCMonth() + 1}-${p(d.getUTCDate())} ` : ""}${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
};
const fmtPx = (x: number) => x >= 1000 ? x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : String(Math.round(x * 100) / 100);
const fmtNum = (x: number | null) => x == null ? "—" : (Math.abs(x) >= 100 ? x.toFixed(0) : x.toFixed(2));
const fmtDur = (bars: number) => {
  const mins = bars * 15;
  return mins >= 60 ? `${Math.floor(mins / 60)} 小时${mins % 60 ? ` ${mins % 60} 分` : ""}` : `${mins} 分钟`;
};

// ---------- 带与锚线（展示聚合） ----------
function buildZones(): AnyObj[] {
  const bars = snap!.bars;
  const px = bars[bars.length - 1].c;
  const zones: AnyObj[] = [];
  const gapByLevel = new Map<string, AnyObj>();
  for (const g of snap!.open_gaps) gapByLevel.set(g.level_key, g);
  const lvByKey = new Map<string, AnyObj>();
  for (const lv of snap!.levels) lvByKey.set(lv.level_key, lv);

  const nearestGap = (side: "below" | "above") => {
    const cand = snap!.open_gaps.filter((g: AnyObj) => side === "below" ? g.anchor < px : g.anchor > px)
      .sort((a: AnyObj, b: AnyObj) => side === "below" ? b.anchor - a.anchor : a.anchor - b.anchor);
    return cand[0] || null;
  };
  const nearestLevel = (side: "below" | "above") => {
    const cand = snap!.levels.filter((l: AnyObj) => l.kind === "swing_major" && l.lo != null &&
      (side === "below" ? l.lo < px : l.lo > px))
      .sort((a: AnyObj, b: AnyObj) => side === "below" ? b.lo - a.lo : a.lo - b.lo);
    return cand[0] || null;
  };

  for (const side of ["below", "above"] as const) {
    const gap = nearestGap(side);
    const isSupport = side === "below";
    if (gap) {
      const lv = lvByKey.get(gap.level_key);
      const far = isSupport ? (lv?.watch_hi ?? gap.anchor * 1.0018) : (lv?.watch_lo ?? gap.anchor * 0.9982);
      zones.push({
        side, kind: isSupport ? "支撑区" : "阻力区", hasGap: true,
        bandLo: isSupport ? gap.anchor : far, bandHi: isSupport ? far : gap.anchor,
        anchor: gap.anchor, anchorEdge: isSupport ? "bottom" : "top",
        gap, color: isSupport ? "47,191,113" : "240,86,79",
        anchorColor: isSupport ? "#2fbf71" : "#f0564f",
      });
    } else {
      const lv = nearestLevel(side);
      if (lv) zones.push({
        side, kind: isSupport ? "支撑带" : "阻力带", hasGap: false,
        bandLo: lv.watch_lo ?? lv.lo, bandHi: lv.watch_hi ?? lv.hi, anchor: null,
        gap: null, color: "110,140,170", anchorColor: "", level: lv,
      });
    }
  }
  (window as any)._zones = zones;
  return zones;
}

function positionBands() {
  if (!candleSeries || !snap) return;
  const host = $("bands");
  host.innerHTML = "";
  const zones: AnyObj[] = (window as any)._zones || [];
  for (const z of zones) {
    const yTop = candleSeries.priceToCoordinate(z.bandHi);
    const yBot = candleSeries.priceToCoordinate(z.bandLo);
    if (yTop == null || yBot == null) continue;
    const div = document.createElement("div");
    div.className = "band";
    div.style.top = `${yTop}px`;
    div.style.height = `${Math.max(yBot - yTop, 3)}px`;
    div.style.background = `rgba(${z.color},.13)`;
    div.style.borderTop = z.anchorEdge === "top" ? "none" : `1px dashed rgba(${z.color},.5)`;
    div.style.borderBottom = z.anchorEdge === "bottom" ? "none" : `1px dashed rgba(${z.color},.5)`;
    const siege = z.gap ? (z.gap.test_count > 0 ? ` · 已挡攻城 ⚔×${z.gap.test_count}` : " · 尚未被攻") : "";
    div.innerHTML = `<span class="blabel" style="color:rgba(${z.color},1);${z.anchorEdge === "top" ? "top:3px" : "bottom:3px"}">${z.kind} ${fmtPx(z.bandLo)} – ${fmtPx(z.bandHi)}</span>` +
      (z.hasGap ? `<span class="alabel" style="${z.anchorEdge === "bottom" ? "bottom:-8px" : "top:-8px"}">${fmtPx(z.gap.anchor)} ${z.gap.direction === "up" ? "向上" : "向下"}缺口锚</span>` : `<span class="alabel">${fmtPx((z.level && (z.level.lo ?? z.level.anchor)) || 0)} 无缺口</span>`);
    host.appendChild(div);
    if (z.hasGap) {
      const yA = candleSeries.priceToCoordinate(z.anchor);
      if (yA != null) {
        const line = document.createElement("div");
        line.className = "anchorLine";
        line.style.top = `${yA}px`;
        line.style.borderTop = `2px solid ${z.anchorColor}`;
        host.appendChild(line);
      }
    }
  }
}

// ---------- 图表 ----------

// —— 页面只写数字，不写机器 ID（用户 2026-10-31：GAP-SWM-H-8-4 这种很丑）——
let GAP_PX: Record<string, number> = {};
let LV_PX: Record<string, number> = {};
let EV_MAP: Record<string, AnyObj> = {};
const EV_SHORT: Record<string, string> = { GAP_OPENED: "立账", GAP_CLOSED: "关账", TEST_STARTED: "测试开始", TEST_ENDED: "测试结束" };
function buildLookups() {
  GAP_PX = {}; LV_PX = {}; EV_MAP = {};
  const s: AnyObj = snap!;
  [...(s.open_gaps || []), ...(s.closed_gaps_recent || [])].forEach((g: AnyObj) => { GAP_PX[g.gap_id] = g.anchor; });
  (s.levels || []).forEach((l: AnyObj) => { LV_PX[l.level_key] = l.lo; });
  (s.events || []).forEach((e: AnyObj) => { EV_MAP[e.event_id] = e; });
}
function evTime(ev: AnyObj): number { return ev.bar_open_ms ?? ev.time_ms ?? ev.occurred_at_ms ?? 0; }
function numRef(id: string): string {
  if (id in GAP_PX) return fmtPx(GAP_PX[id]);
  if (id in LV_PX) return fmtPx(LV_PX[id]);
  const ev = EV_MAP[id];
  if (ev) return `${fmtTc(evTime(ev), false)} ${EV_SHORT[ev.type] || "事件"}`;
  return id;
}
function humanize(text: string): string {
  if (!text) return text;
  let t = text.replace(/GAP-[A-Z0-9]+(?:-[A-Z0-9]+)*[（(]锚\s*([0-9.]+)[）)]/g, (_m, p) => fmtPx(Number(p)));
  t = t.replace(/GAP-[A-Z0-9]+(?:-[A-Z0-9]+)*/g, m => (m in GAP_PX) ? fmtPx(GAP_PX[m]) : "该缺口");
  t = t.replace(/[A-Z]{1,4}-[HL]-\d+@v\d+/g, m => (m in LV_PX) ? fmtPx(LV_PX[m]) : "该位置");
  t = t.replace(/\bev-\d+/g, m => { const ev = EV_MAP[m]; return ev ? fmtTc(evTime(ev), false) : m; });
  return t;
}

function renderHeader() {
  const m = snap!.meta;
  const ageMin = Math.max(0, Math.round((Date.now() - m.cursor_close_ms) / 60000));
  const lb = $("liveBadge");
  if (ageMin <= 17) { lb.textContent = "● LIVE"; lb.style.color = "#2fbf71"; }
  else if (ageMin <= 35) { lb.textContent = `● 延迟 ${ageMin} 分钟`; lb.style.color = "#e8a33d"; }
  else { lb.textContent = `● 陈旧 ${ageMin} 分钟`; lb.style.color = "#f0564f"; }
  $("dataTime").textContent =
    `最新已收盘 K 线 ${fmtTc(m.cursor_close_ms)} · 战场快照生成 ${fmtTc(m.generated_at_ms)} · AI 简报基于 rev ${m.ai.last_read_cursor ?? "—"}（UTC+8） · ${m.window}`;
  $("tokenBadge").textContent = m.token;
  $("aiBadge").textContent = m.ai.stale ? "AI 待复核（基于旧快照）"
    : `AI 已复核至 ${fmtTc(m.cursor_close_ms, false)}`;
}

function renderChart() {
  const bars = snap!.bars;
  if (chart) { chart.remove(); chart = null; }
  chart = LightweightCharts.createChart($("chart"), {
    layout: { background: { color: "transparent" }, textColor: "#7e97ab", fontSize: 11, attributionLogo: false },
    grid: { vertLines: { color: "rgba(38,64,87,.35)" }, horzLines: { color: "rgba(38,64,87,.35)" } },
    rightPriceScale: { borderColor: "#24455e" },
    timeScale: { borderColor: "#24455e", timeVisible: true, secondsVisible: false,
      tickMarkFormatter: (t: number) => fmtTc(t * 1000, false) },
    localization: { locale: "zh-CN", timeFormatter: (t: number) => fmtTc(t * 1000) },
  });
  candleSeries = chart.addCandlestickSeries({
    upColor: "#22b573", downColor: "#e5484d", borderVisible: false,
    wickUpColor: "#22b573", wickDownColor: "#e5484d",
    priceFormat: { type: "price", precision: snap!.meta.symbol === "BTCUSDT" ? 1 : 2, minMove: snap!.meta.symbol === "BTCUSDT" ? 0.1 : 0.01 },
  });
  candleSeries.setData(bars.map((b: AnyObj) => ({ time: Math.floor(b.t / 1000), open: b.o, high: b.h, low: b.l, close: b.c })));
  const last = bars[bars.length - 1];
  candleSeries.createPriceLine({ price: last.c, color: "#e8a33d", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "" });

  // 测试标记 T1/T2…：开放缺口 + 最近关账缺口的回补测试起点
  const markers: any[] = [];
  const allGaps = [...snap!.open_gaps];
  for (const g of allGaps) (g.tests || []).forEach((t: AnyObj, i: number) => {
    if (!t.started_ms) return;
    markers.push({
      time: Math.floor(t.started_ms / 1000), position: g.direction === "up" ? "belowBar" : "aboveBar",
      shape: "circle", color: g.direction === "up" ? "#2fbf71" : "#f0564f", text: `T${i + 1}`,
    });
  });
  markers.sort((a, b) => a.time - b.time);
  if (markers.length) candleSeries.setMarkers(markers);

  chart.timeScale().fitContent();
  chart.timeScale().subscribeVisibleLogicalRangeChange(positionBands);
  setTimeout(positionBands, 60);
}

// ---------- 右栏 ----------
function renderBrief() {
  const hyps: AnyObj[] = snap!.hypotheses;
  const fmtRefs = (refs: string[]) => refs && refs.length ? refs.map(numRef).join("、") : "—";
  if (!hyps.length) { $("hypBody").innerHTML = "暂无假设。"; return; }
  const [main, ...rest] = hyps;
  const backup = rest[0];
  $("hypBody").innerHTML = `
    <div class="hypMain"><div class="t">主要观点（当前假设 ${main.hyp_id}）</div><div>${humanize(main.text || "")}</div></div>
    <div class="evT">支持证据</div>
    ${[main].map(h => `<div class="evItem"><span class="n">✓</span><span>${fmtRefs(h.support_refs)}</span></div>`).join("")}
    <div class="evT red">反证因素</div>
    <div class="evItem"><span class="n">!</span><span>${fmtRefs(main.counter_refs)}</span></div>
    ${backup ? `<div class="evT">备推演（${backup.hyp_id}）</div><div style="color:#c6dcee;font-size:12.5px">${humanize(backup.text || "")}</div>` : ""}`;
  $("hypUpd").textContent = `更新于 ${fmtTc(snap!.meta.generated_at_ms, false)}`;
}

function renderPlan() {
  const plans: AnyObj[] = snap!.watch_plans;
  if (!plans.length) { $("planBody").innerHTML = "暂无观察计划。"; return; }
  const p = plans[plans.length - 1];
  const proposals: AnyObj[] = snap!.candidate_proposals || [];
  const cand = proposals.length ? proposals[proposals.length - 1] : null;
  const candText = cand ? (cand.text || cand.setup || cand.reason || "已立候选（提案分区）") : null;
  const execText = cand ? (cand.entry_trigger || cand.entry || cand.trigger || null) : null;
  const step = (n: number, cls: string, title: string, desc: string, extra = "") =>
    `<div class="step ${cls}"><span class="n">${n}</span><div><div class="st">${title}</div><div class="sd">${desc}</div></div>${extra}</div>`;
  $("planBody").innerHTML = `<div class="steps">` +
    step(1, "done", "观察位置", numRef(p.watch_level || "") || "—") +
    step(2, "act", "等待行为", humanize(p.watch_behavior || "—"), `<span class="waitB">WAIT</span>`) +
    step(3, "", "复核触发", `${humanize(p.entry_trigger || "—")}<br><span style="color:#55707f;font-size:11.5px">满足后唤醒 AI 复核，不是入场指令</span>`) +
    step(4, cand ? "done" : "", "候选条件", candText || "等待——尚无候选，复核通过后才立") +
    step(5, execText ? "done" : "", "订单触发", execText || "等待——候选未立，无可执行触发") +
    step(6, "", "取消条件", humanize(p.cancel_if || "—")) + `</div>`;
}

// ---------- 底部：时间线 + 多空对照 ----------
function sparkline(barMs: number): string {
  const bars = snap!.bars;
  let idx = bars.findIndex((b: AnyObj) => b.t >= barMs - 1);
  if (idx < 0) idx = bars.length - 1;
  const win = bars.slice(Math.max(0, idx - 8), Math.min(bars.length, idx + 9));
  if (win.length < 2) return "";
  const cs = win.map((b: AnyObj) => b.c);
  const mn = Math.min(...cs), mx = Math.max(...cs), rg = (mx - mn) || 1;
  const pts = cs.map((c: number, i: number) => `${(i / (cs.length - 1) * 86).toFixed(1)},${(30 - (c - mn) / rg * 26).toFixed(1)}`).join(" ");
  const upNet = cs[cs.length - 1] >= cs[0];
  return `<svg width="86" height="32"><polyline points="${pts}" fill="none" stroke="${upNet ? "#22b573" : "#e5484d"}" stroke-width="1.4"/></svg>`;
}

function renderTimeline() {
  const TITLE: Record<string, (e: AnyObj) => [string, string]> = {
    GAP_OPENED: e => ["缺口建立", `锚 ${e.payload?.anchor ? fmtPx(Number(e.payload.anchor)) : ""}`],
    TEST_STARTED: e => [`测试（T${e.payload?.test_index || ""}）`, `${e.payload?.gap_id || ""} 回补测试开始`],
    TEST_ENDED: e => ["测试结束", `${e.payload?.gap_id || ""} · ${e.payload?.outcome === "anchor_touched" ? "触锚" : "被拒（代理口径）"}`],
    GAP_CLOSED: e => ["缺口回补", `${e.payload?.gap_id || ""} 触锚关账（城破）`],
  };
  const story = snap!.events.filter((e: AnyObj) => TITLE[e.type]).slice(-5);
  $("tlBody").innerHTML = story.length ? story.map((e: AnyObj) => {
    const [t, s] = TITLE[e.type](e);
    return `<div class="node"><div class="tm">${fmtTc(e.bar_open_ms)}</div><div class="dot"></div><div class="tt">${t}</div><div class="ts">${humanize(s)}</div>${sparkline(e.bar_open_ms)}</div>`;
  }).join("") : "24h 内无缺口事件。";
}

function renderCompare() {
  const pick = (sideKey: string) => {
    const segs: AnyObj[] = snap!.sides[sideKey].segments || [];
    return [...segs].reverse().find(s => !s.open) || segs[segs.length - 1] || null;
  };
  const cell = (seg: AnyObj | null, kind: string) => {
    if (!seg) return "—";
    const dir = seg.direction === "up" ? 1 : -1;
    if (kind === "prog") return `${seg.direction === "up" ? "+" : "−"}${fmtNum(seg.net_progress)}（${fmtPx(seg.p0)} → ${fmtPx(seg.p0 + dir * (seg.net_progress ?? 0))}）`;
    if (kind === "give") return `${fmtNum(seg.giveback)}（极值 ${fmtPx(seg.p0 + dir * (seg.favorable ?? 0))} → ${fmtPx(seg.p0 + dir * (seg.net_progress ?? 0))}）`;
    return `${fmtDur(seg.elapsed_bars ?? 0)}${seg.open ? "（进行中）" : ""}`;
  };
  const up = pick("up"), dn = pick("down");
  $("cmpBody").innerHTML = `<table class="cmp"><tr><th></th><th class="up">多方（上涨）</th><th class="down">空方（下跌）</th></tr>
    <tr><td>推进幅度</td><td class="up">${cell(up, "prog")}</td><td class="down">${cell(dn, "prog")}</td></tr>
    <tr><td>回撤幅度</td><td>${cell(up, "give")}</td><td>${cell(dn, "give")}</td></tr>
    <tr><td>持续时间</td><td>${cell(up, "dur")}</td><td>${cell(dn, "dur")}</td></tr></table>`;
}

// ---------- 装配 ----------
let curSymbol = "BTCUSDT";
async function load(sym: string) { curSymbol = sym;
  $("symBTC").classList.toggle("on", sym === "BTCUSDT");
  $("symETH").classList.toggle("on", sym === "ETHUSDT");
  snap = await (await fetch(`data24/${sym}.json`)).json();
  buildLookups();
  const m = snap!.meta, bars = snap!.bars, last = bars[bars.length - 1];
  const prev = bars[bars.length - 2] || last;
  const chg = last.c - prev.c, pct = (chg / prev.c * 100);
  renderHeader();
  $("ohlcLine").innerHTML = `<span><b>${m.symbol}</b> · 15 · Binance</span>` +
    `<span>开 <b>${fmtPx(last.o)}</b></span><span>高 <b>${fmtPx(last.h)}</b></span><span>低 <b>${fmtPx(last.l)}</b></span>` +
    `<span>收 <b>${fmtPx(last.c)}</b></span><span class="${chg >= 0 ? "up" : "down"}">${chg >= 0 ? "+" : ""}${fmtPx(Math.abs(chg))} (${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)</span>` +
    ``;
  buildZones();
  renderChart();
  renderBrief();
  renderPlan();
  renderTimeline();
  renderCompare();
  $("footLine").textContent = `快照 ${m.token} · rev ${m.state_revision} · 生成 ${fmtTc(m.generated_at_ms)} · ${m.source} · 缺口锚线 = 带的最外沿（支撑带最下 / 阻力带最上），碰到即销账 · MM 目标位未接线，本页不画 · 沙盘只读`;
}

window.addEventListener("resize", positionBands);
$("symBTC").addEventListener("click", () => load("BTCUSDT"));
$("symETH").addEventListener("click", () => load("ETHUSDT"));
load("BTCUSDT");
// 日内滚动：每 60 秒探一次新快照，token 变了才整页重渲染（数据由 roll_site 每 15 分钟整窗更新）
setInterval(async () => {
  try {
    const fresh = await (await fetch(`data24/${curSymbol}.json?t=${Date.now()}`)).json();
    if (!snap || fresh.meta.token !== snap.meta.token) { snap = fresh; buildLookups(); const m = snap.meta, bars = snap.bars, last = bars[bars.length - 1]; const prev = bars[bars.length - 2] || last; const chg = last.c - prev.c, pct = (chg / prev.c * 100);
      renderHeader();
      $("ohlcLine").innerHTML = `<span><b>${m.symbol}</b> · 15 · Binance</span><span>开 <b>${fmtPx(last.o)}</b></span><span>高 <b>${fmtPx(last.h)}</b></span><span>低 <b>${fmtPx(last.l)}</b></span><span>收 <b>${fmtPx(last.c)}</b></span><span class="${chg >= 0 ? "up" : "down"}">${chg >= 0 ? "+" : ""}${fmtPx(Math.abs(chg))} (${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)</span>`;
      buildZones(); renderChart(); renderBrief(); renderPlan(); renderTimeline(); renderCompare();
      $("footLine").textContent = `快照 ${m.token} · rev ${m.state_revision} · 生成 ${fmtTc(m.generated_at_ms)} · ${m.source} · 缺口锚线 = 带的最外沿（支撑带最下 / 阻力带最上），碰到即销账 · MM 目标位未接线，本页不画 · 沙盘只读`;
    }
  } catch (e) { /* 网络抖动下轮再探 */ }
}, 60000);
