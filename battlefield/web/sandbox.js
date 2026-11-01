const CST = 8 * 3600;
let snap = null;
let chart = null, candleSeries = null;
const $ = (id) => document.getElementById(id);
const fmtTc = (ms, withDay = true) => {
    const d = new Date(ms + CST * 1000);
    const p = (n) => String(n).padStart(2, "0");
    return `${withDay ? `${d.getUTCMonth() + 1}-${p(d.getUTCDate())} ` : ""}${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
};
const fmtPx = (x) => x >= 1000 ? x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : String(Math.round(x * 100) / 100);
const fmtNum = (x) => x == null ? "—" : (Math.abs(x) >= 100 ? x.toFixed(0) : x.toFixed(2));
const fmtDur = (bars) => {
    const mins = bars * 15;
    return mins >= 60 ? `${Math.floor(mins / 60)} 小时${mins % 60 ? ` ${mins % 60} 分` : ""}` : `${mins} 分钟`;
};
// ---------- 带与锚线（展示聚合） ----------
function buildZones() {
    const bars = snap.bars;
    const px = bars[bars.length - 1].c;
    const zones = [];
    const gapByLevel = new Map();
    for (const g of snap.open_gaps)
        gapByLevel.set(g.level_key, g);
    const lvByKey = new Map();
    for (const lv of snap.levels)
        lvByKey.set(lv.level_key, lv);
    const nearestGap = (side) => {
        const cand = snap.open_gaps.filter((g) => side === "below" ? g.anchor < px : g.anchor > px)
            .sort((a, b) => side === "below" ? b.anchor - a.anchor : a.anchor - b.anchor);
        return cand[0] || null;
    };
    const nearestLevel = (side) => {
        const cand = snap.levels.filter((l) => l.kind === "swing_major" && l.lo != null &&
            (side === "below" ? l.lo < px : l.lo > px))
            .sort((a, b) => side === "below" ? b.lo - a.lo : a.lo - b.lo);
        return cand[0] || null;
    };
    for (const side of ["below", "above"]) {
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
        }
        else {
            const lv = nearestLevel(side);
            if (lv)
                zones.push({
                    side, kind: isSupport ? "支撑带" : "阻力带", hasGap: false,
                    bandLo: lv.watch_lo ?? lv.lo, bandHi: lv.watch_hi ?? lv.hi, anchor: null,
                    gap: null, color: "110,140,170", anchorColor: "", level: lv,
                });
        }
    }
    window._zones = zones;
    return zones;
}
function positionBands() {
    if (!candleSeries || !snap)
        return;
    const host = $("bands");
    host.innerHTML = "";
    const zones = window._zones || [];
    for (const z of zones) {
        const yTop = candleSeries.priceToCoordinate(z.bandHi);
        const yBot = candleSeries.priceToCoordinate(z.bandLo);
        if (yTop == null || yBot == null)
            continue;
        const div = document.createElement("div");
        div.className = "band";
        div.style.top = `${yTop}px`;
        div.style.height = `${Math.max(yBot - yTop, 3)}px`;
        div.style.background = `rgba(${z.color},.13)`;
        div.style.borderTop = z.anchorEdge === "top" ? "none" : `1px dashed rgba(${z.color},.5)`;
        div.style.borderBottom = z.anchorEdge === "bottom" ? "none" : `1px dashed rgba(${z.color},.5)`;
        const siege = z.gap ? (z.gap.test_count > 0 ? ` · 已挡攻城 ⚔×${z.gap.test_count}` : " · 尚未被攻") : "";
        div.innerHTML = `<span class="blabel" style="color:rgba(${z.color},1);${z.anchorEdge === "top" ? "top:3px" : "bottom:3px"}">${z.kind} ${fmtPx(z.bandLo)} – ${fmtPx(z.bandHi)}</span>` +
            (z.hasGap ? `<span class="alabel" style="${z.anchorEdge === "bottom" ? "bottom:-8px" : "top:-8px"}">${fmtPx(z.gap.anchor)} ${z.gap.direction === "up" ? "向上" : "向下"}缺口</span>` : `<span class="alabel">${fmtPx((z.level && (z.level.lo ?? z.level.anchor)) || 0)} 无缺口</span>`);
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
let GAP_PX = {};
let LV_PX = {};
let EV_MAP = {};
let SEG_DIR = {};
const EV_SHORT = { GAP_OPENED: "立账", GAP_CLOSED: "关账", TEST_STARTED: "测试开始", TEST_ENDED: "测试结束" };
function buildLookups() {
    GAP_PX = {};
    LV_PX = {};
    EV_MAP = {};
    SEG_DIR = {};
    const s = snap;
    [...(s.open_gaps || []), ...(s.closed_gaps_recent || [])].forEach((g) => { GAP_PX[g.gap_id] = g.anchor; });
    (s.levels || []).forEach((l) => { LV_PX[l.level_key] = l.lo; });
    (s.events || []).forEach((e) => { EV_MAP[e.event_id] = e; });
    for (const side of ["up", "down"])
        (s.sides?.[side]?.segments || []).forEach((sg) => {
            SEG_DIR[sg.segment_id] = sg.direction === "up" ? "上涨段" : "下跌段";
        });
}
function evTime(ev) { return ev.bar_open_ms ?? ev.time_ms ?? ev.occurred_at_ms ?? 0; }
function numRef(id) {
    if (id in GAP_PX)
        return fmtPx(GAP_PX[id]);
    if (id in LV_PX)
        return fmtPx(LV_PX[id]);
    const ev = EV_MAP[id];
    if (ev)
        return `${fmtTc(evTime(ev), false)} ${EV_SHORT[ev.type] || "事件"}`;
    return id;
}
const DIALECT = {
    GAP_OPENED: "缺口立账", GAP_CLOSED: "缺口关账", TEST_STARTED: "测试开始", TEST_ENDED: "测试结束",
    LEFT_BAND_UP: "向上离开支撑带", LEFT_BAND_DOWN: "向下离开阻力带", RETURN_TO_BAND: "回到带内",
    LEVEL_TOUCHED: "触及位置", LEVEL_CONFIRMED: "位置确认", RECLAIMED: "收复位置", SEPARATED: "整根分离",
    ATTEMPT_STARTED: "尝试开始", rejected_proxy: "被拒", anchor_touched: "已触线", sufficient: "推进充分",
    test_count: "测试次数",
};
function humanize(text) {
    if (!text)
        return text;
    let t = text.replace(/GAP-[A-Z0-9]+(?:-[A-Z0-9]+)*[（(]锚\s*([0-9.]+)[）)]/g, (_m, p) => fmtPx(Number(p)));
    t = t.replace(/GAP-[A-Z0-9]+(?:-[A-Z0-9]+)*/g, m => (m in GAP_PX) ? fmtPx(GAP_PX[m]) : "该缺口");
    t = t.replace(/[A-Z]{1,4}-[HL]-\d+@v\d+/g, m => (m in LV_PX) ? fmtPx(LV_PX[m]) : "该位置");
    // 判读员的研判原文是机器方言，展示前翻成人话：事件号/段号/类型名一律不漏
    t = t.replace(/增量\s*ev-\d+\s*至\s*ev-\d+/g, "增量");
    t = t.replace(/ev-\d+\s*至\s*ev-\d+/g, "新增事件");
    t = t.replace(/\bev-\d+/g, m => { const ev = EV_MAP[m]; return ev ? fmtTc(evTime(ev), false) : "该事件"; });
    t = t.replace(/（该事件）/g, "").replace(/、该事件/g, "").replace(/该事件、/g, "");
    t = t.replace(/（该事件[，,]/g, "（");
    t = t.replace(/SEG-\d+/g, m => SEG_DIR[m] || "一段行情");
    t = t.replace(/(一段行情)(、一段行情)+/g, "多段行情");
    t = t.replace(/\bWP\d+\b/g, "观察计划");
    for (const [k, v] of Object.entries(DIALECT))
        t = t.split(k).join(v);
    // 分析是给人看的（用户 2026-11-01 点名）：假设管理方言与「锚」字一律不许上脸
    t = t.replace(/[（(]\s*supersede\s*H\d+\s*[）)]/gi, "");
    t = t.replace(/supersede\s*H\d+/gi, "上一推演");
    t = t.replace(/\bH\d+\b/g, "该推演");
    t = t.replace(/[（(]锚\s*[\d.,]+[）)]/g, "");
    t = t.replace(/锚线/g, "缺口线").replace(/触锚/g, "触线");
    t = t.replace(/该锚位/g, "该位置").replace(/锚位/g, "");
    t = t.replace(/锚\s*(?=[\d])/g, "");
    t = t.replace(/open状态/g, "开放状态");
    return t;
}
function renderHeader() {
    const m = snap.meta;
    if (liveOk) {
        const lb0 = $("liveBadge");
        lb0.textContent = "● LIVE 实时";
        lb0.style.color = "#2fbf71";
        return;
    }
    const ageMin = Math.max(0, Math.round((Date.now() - m.cursor_close_ms) / 60000));
    const lb = $("liveBadge");
    if (ageMin <= 17) {
        lb.textContent = "● LIVE";
        lb.style.color = "#2fbf71";
    }
    else if (ageMin <= 35) {
        lb.textContent = `● 延迟 ${ageMin} 分钟`;
        lb.style.color = "#e8a33d";
    }
    else {
        lb.textContent = `● 陈旧 ${ageMin} 分钟`;
        lb.style.color = "#f0564f";
    }
    // 顶栏只留 LIVE 状态：快照时间/token/AI 复核徽章按用户 2026-11-01
    // 要求全部撤下（数据在快照 meta 里，随时可查，不摆在脸上）
}
function renderChart() {
    const bars = snap.bars;
    if (chart) {
        chart.remove();
        chart = null;
    }
    chart = LightweightCharts.createChart($("chart"), {
        autoSize: true,
        layout: { background: { color: "transparent" }, textColor: "#7e97ab", fontSize: 11, attributionLogo: false },
        grid: { vertLines: { color: "rgba(38,64,87,.35)" }, horzLines: { color: "rgba(38,64,87,.35)" } },
        rightPriceScale: { borderColor: "#24455e" },
        timeScale: { borderColor: "#24455e", timeVisible: true, secondsVisible: false,
            tickMarkFormatter: (t) => fmtTc(t * 1000, false) },
        localization: { locale: "zh-CN", timeFormatter: (t) => fmtTc(t * 1000) },
    });
    candleSeries = chart.addCandlestickSeries({
        upColor: "#22b573", downColor: "#e5484d", borderVisible: false,
        wickUpColor: "#22b573", wickDownColor: "#e5484d",
        priceFormat: { type: "price", precision: snap.meta.symbol === "BTCUSDT" ? 1 : 2, minMove: snap.meta.symbol === "BTCUSDT" ? 0.1 : 0.01 },
    });
    candleSeries.setData(bars.map((b) => ({ time: Math.floor(b.t / 1000), open: b.o, high: b.h, low: b.l, close: b.c })));
    const last = bars[bars.length - 1];
    liveLine = candleSeries.createPriceLine({ price: last.c, color: "#e8a33d", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "" });
    // 测试标记 T1/T2…：开放缺口 + 最近关账缺口的回补测试起点
    const markers = [];
    const allGaps = [...snap.open_gaps];
    for (const g of allGaps)
        (g.tests || []).forEach((t, i) => {
            if (!t.started_ms)
                return;
            markers.push({
                time: Math.floor(t.started_ms / 1000), position: g.direction === "up" ? "belowBar" : "aboveBar",
                shape: "circle", color: g.direction === "up" ? "#2fbf71" : "#f0564f", text: `T${i + 1}`,
            });
        });
    markers.sort((a, b) => a.time - b.time);
    if (markers.length)
        candleSeries.setMarkers(markers);
    // 实时层：把正在形成的那根接上（视图宽度把它算在内），并确保 WS 已订阅
    applyLiveBar();
    startLive(snap.meta.symbol);
    const total = bars.length + (liveBar && liveBar.t > last.t ? 1 : 0);
    // 默认缩放 = 最近 24h（96 根）满屏；全量历史仍在数据里，左拖可回看
    const DEFAULT_VIEW_BARS = 96;
    if (total > DEFAULT_VIEW_BARS) {
        chart.timeScale().setVisibleLogicalRange({
            from: total - DEFAULT_VIEW_BARS - 0.5, to: total - 0.5,
        });
    }
    else {
        chart.timeScale().fitContent();
    }
    chart.timeScale().subscribeVisibleLogicalRangeChange(positionBands);
    setTimeout(positionBands, 60);
}
// ---------- 实时行情（只管图表层） ----------
// 快照给已收盘 K 线；正在形成的当根由 Binance WebSocket 直推，图表实时
// 跳动（用户 2026-11-01：别 15 分钟推一根，实时弄）。简报/账本/时间线
// 仍是 15 分钟判读口径，不受实时层影响。
let liveWs = null;
let liveSym = "";
let liveBar = null;
let liveLine = null;
let liveLineAt = 0;
let liveOk = false;
function renderLiveBadge() {
    if (!liveOk)
        return;
    const lb = $("liveBadge");
    lb.textContent = "● LIVE 实时";
    lb.style.color = "#2fbf71";
}
function applyLiveBar() {
    if (!candleSeries || !liveBar || !snap)
        return;
    const bars = snap.bars;
    const lastT = bars[bars.length - 1].t;
    if (liveBar.t < lastT)
        return; // 已被更新的快照收编
    try {
        candleSeries.update({ time: Math.floor(liveBar.t / 1000), open: liveBar.o, high: liveBar.h, low: liveBar.l, close: liveBar.c });
    }
    catch { /* 系列重建瞬间可能抛错，下一推自愈 */ }
    const prev = liveBar.t === lastT ? (bars[bars.length - 2] || liveBar) : bars[bars.length - 1];
    const chg = liveBar.c - prev.c, pct = prev.c ? chg / prev.c * 100 : 0;
    $("ohlcLine").innerHTML = `<span><b>${snap.meta.symbol}</b> · 15 · Binance</span>` +
        `<span>开 <b>${fmtPx(liveBar.o)}</b></span><span>高 <b>${fmtPx(liveBar.h)}</b></span><span>低 <b>${fmtPx(liveBar.l)}</b></span>` +
        `<span>收 <b>${fmtPx(liveBar.c)}</b></span><span class="${chg >= 0 ? "up" : "down"}">${chg >= 0 ? "+" : ""}${fmtPx(Math.abs(chg))} (${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)</span>` +
        `<span style="color:#2fbf71">· 实时</span>`;
    const now = Date.now();
    if (now - liveLineAt > 1000) {
        liveLineAt = now;
        try {
            if (liveLine)
                candleSeries.removePriceLine(liveLine);
            liveLine = candleSeries.createPriceLine({ price: liveBar.c, color: "#e8a33d", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "" });
        }
        catch { /* 同上 */ }
    }
}
function startLive(sym) {
    if (liveSym === sym && liveWs)
        return;
    liveSym = sym;
    liveBar = null;
    liveOk = false;
    if (liveWs) {
        try {
            liveWs.close();
        }
        catch { /* 已断开 */ }
        liveWs = null;
    }
    const hosts = ["wss://stream.binance.com:9443", "wss://data-stream.binance.vision"];
    let hi = 0;
    const connect = () => {
        if (liveSym !== sym)
            return;
        const ws = new WebSocket(`${hosts[hi]}/ws/${sym.toLowerCase()}@kline_15m`);
        liveWs = ws;
        let opened = false;
        ws.onopen = () => { opened = true; liveOk = true; renderLiveBadge(); };
        ws.onmessage = (ev) => {
            try {
                const k = JSON.parse(ev.data).k;
                if (!k)
                    return;
                liveBar = { t: k.t, o: parseFloat(k.o), h: parseFloat(k.h), l: parseFloat(k.l), c: parseFloat(k.c) };
                applyLiveBar();
            }
            catch { /* 单帧坏数据忽略 */ }
        };
        ws.onerror = () => { try {
            ws.close();
        }
        catch { /* 忽略 */ } };
        ws.onclose = () => {
            if (liveWs === ws)
                liveWs = null;
            if (liveSym !== sym)
                return;
            liveOk = false;
            if (!opened && hi < hosts.length - 1) {
                hi++;
                connect();
            }
            else
                setTimeout(connect, 3000);
        };
    };
    connect();
}
// ---------- 右栏 ----------
// 引用 → 人话事实：证据/反证不许只摆数字（用户 2026-11-01 点名「写个数字
// 就敷衍」）——缺口要讲清方向/位置/测试史，事件要讲清几点发生了什么。
function gapById(id) {
    const s = snap;
    return (s.open_gaps || []).find((g) => g.gap_id === id)
        || (s.closed_gaps_recent || []).find((g) => g.gap_id === id) || null;
}
function lastTestOutcome(gapId) {
    const evs = (snap.events || []).filter((e) => e.type === "TEST_ENDED" && e.payload?.gap_id === gapId);
    return evs.length ? (evs[evs.length - 1].payload?.outcome || null) : null;
}
function gapStory(id) {
    const g = gapById(id);
    if (!g)
        return null;
    const dir = g.direction === "up" ? "向上" : "向下";
    const open = (snap.open_gaps || []).some((x) => x.gap_id === id);
    const px = snap.bars[snap.bars.length - 1].c;
    const rel = g.anchor > px ? `位于现价上方 ${fmtNum(g.anchor - px)} 点`
        : g.anchor < px ? `位于现价下方 ${fmtNum(px - g.anchor)} 点` : "与现价重合";
    if (!open)
        return `${fmtPx(g.anchor)} 的${dir}缺口：已回补关账（共经 ${g.test_count ?? 0} 次回补测试）`;
    let s = `${fmtPx(g.anchor)} 的${dir}缺口仍开放，${rel}`;
    if (g.test_count) {
        const oc = lastTestOutcome(id);
        s += `；已回补测试 ${g.test_count} 次${oc === "anchor_touched" ? "，最近一次已触线" : oc ? "，均未触线、被拒" : ""}`;
        const t = (g.tests || [])[g.tests.length - 1];
        if (t?.started_ms)
            s += `（最近一次 ${fmtTc(t.started_ms, false)}–${t.ended_ms ? fmtTc(t.ended_ms, false) : "进行中"}）`;
    }
    else
        s += "；尚未被回补测试";
    return s;
}
function evStory(ev) {
    const t = fmtTc(evTime(ev), false);
    const g = ev.payload?.gap_id ? gapById(ev.payload.gap_id) : null;
    const anchor = g ? fmtPx(g.anchor) : (ev.payload?.anchor ? fmtPx(Number(ev.payload.anchor)) : "—");
    switch (ev.type) {
        case "GAP_OPENED": return `${t} ${anchor} ${ev.direction === "up" ? "向上" : "向下"}缺口立账`;
        case "GAP_CLOSED": return `${t} ${anchor} 缺口回补关账`;
        case "TEST_STARTED": return `${t} ${anchor} 第 ${ev.payload?.test_index || ""} 次回补测试开始`;
        case "TEST_ENDED": return `${t} ${anchor} 回补测试结束：${ev.payload?.outcome === "anchor_touched" ? "已触线" : "未触线、被拒"}`;
        default: return `${t} ${EV_SHORT[ev.type] || "事件"}（${anchor}）`;
    }
}
function refStory(ref) {
    const gs = gapStory(ref);
    if (gs)
        return gs;
    const ev = EV_MAP[ref];
    if (ev)
        return evStory(ev);
    if (ref in LV_PX)
        return `位置 ${fmtPx(LV_PX[ref])}`;
    return humanize(ref);
}
const DELTA_LABEL = {
    no_material_change: "本轮无实质变化", strengthened: "主推演增强", weakened: "主推演削弱",
    new_branch: "出现新分支", invalidated: "主推演已失效",
};
function renderBrief() {
    const hyps = snap.hypotheses;
    if (!hyps.length) {
        $("hypBody").innerHTML = "暂无假设。";
        return;
    }
    // 选当前主/备（简报 v2）：输出带 role（primary/backup）就认 role；存量
    // v1 假设无 role，退回旧启发式——最近更新的一对、文本含「主推演」者认
    // 主。不能拿数组头两条，那是种子期的化石假设（2026-11-01 用户实报过）
    const score = (h) => Math.max(0, ...(h.history || []).map((x) => x.revision || 0));
    const pool = hyps.filter(h => h.status === "active" || h.status === "challenged");
    // 存量墓碑（旧清理法拿 supersede 写「…作废」文本、反把墓碑立成 active）
    // 不许冒充主/备；有真推演在场时先把墓碑滤掉，新账本用 retire 销账
    const alive = pool.filter(h => !/^旧|^上一轮.*接续|^\s*退役/.test(h.text || ""));
    const sorted = [...(alive.length ? alive : pool.length ? pool : hyps)].sort((a, b) => score(b) - score(a));
    let main = sorted.find(h => h.role === "primary") || sorted[0];
    let backup = sorted.find(h => h.role === "backup" && h !== main)
        || sorted.find(h => h !== main);
    if (main && backup && !main.role && /主推演/.test(backup.text || "") && !/主推演/.test(main.text || "")) {
        [main, backup] = [backup, main];
    }
    const renderRefs = (refs, mark) => {
        if (!refs || !refs.length)
            return `<div class="evItem"><span class="n">${mark}</span><span>—</span></div>`;
        const covered = new Set(refs.filter(r => gapById(r)));
        const lines = [];
        for (const r of refs) {
            const ev = EV_MAP[r];
            if (ev && ev.payload?.gap_id && covered.has(ev.payload.gap_id))
                continue; // 测试事件已并入该缺口的叙事
            lines.push(refStory(r));
        }
        return lines.map(s => `<div class="evItem"><span class="n">${mark}</span><span>${humanize(s)}</span></div>`).join("");
    };
    // v2 三件套（结论/本轮更新/接管条件）随输出全量进快照，各取最近一份带
    // 该字段的；存量 v1 输出没有这些字段，对应块自动回退旧渲染
    const outs = [...(snap.brain_outputs || [])].reverse();
    const conclusion = outs.find(o => o.conclusion)?.conclusion;
    const delta = outs.find(o => o.delta)?.delta;
    const handoff = outs.find(o => o.handoff)?.handoff;
    const phaseB = (h) => h.phase ? `<span class="phaseB">${h.phase}</span>` : "";
    // 证据（claims）：支持项按权重展开核心 ≤2 + 辅助 ≤1；削弱进反证、
    // 未决进未决，两块分开，不再把所有引用一锅烩
    const claims = main.claims || [];
    const wRank = { core: 0, aux: 1, background: 2 };
    const sup = claims.filter(c => c.effect === "supports")
        .sort((a, b) => (wRank[a.weight] ?? 3) - (wRank[b.weight] ?? 3));
    const shownSup = [...sup.filter(c => c.weight === "core").slice(0, 2),
        ...sup.filter(c => c.weight === "aux").slice(0, 1)];
    if (!shownSup.length && sup.length)
        shownSup.push(...sup.slice(0, 2));
    const weak = claims.filter(c => c.effect === "weakens");
    const unres = claims.filter(c => c.effect === "unresolved");
    const claimLine = (c, mark) => `<div class="evItem"><span class="n">${mark}</span><span><b>${humanize(c.claim || "")}</b>${c.fact ? `——${humanize(c.fact)}` : ""}</span></div>`;
    const hist = main.history || [];
    const lastHist = hist[hist.length - 1];
    const opWord = { add: "立论", confirm: "确认", challenge: "受挑战", supersede: "被接管" };
    const evHtml = claims.length
        ? `<div class="evT">核心证据</div>${shownSup.map(c => claimLine(c, "✓")).join("") || `<div class="evItem"><span class="n">✓</span><span>—</span></div>`}`
        : `<div class="evT">支持证据</div>${renderRefs(main.support_refs, "✓")}`;
    const counterHtml = (weak.length || unres.length)
        ? `${weak.length ? `<div class="evT red">反证</div>${weak.map(c => claimLine(c, "!")).join("")}` : ""}
       ${unres.length ? `<div class="evT">尚未决出</div>${unres.map(c => claimLine(c, "?")).join("")}` : ""}`
        : `<div class="evT red">反证因素</div>${renderRefs(main.counter_refs, "!")}`;
    const deltaHtml = delta
        ? `<div class="evT">本轮更新 · ${DELTA_LABEL[delta.kind] || ""}</div><div class="reason">${humanize(delta.what_changed || "")}${delta.what_it_means ? `<br>意味着：${humanize(delta.what_it_means)}` : ""}${delta.effect_on_hypothesis ? `<br>对主要观点：${humanize(delta.effect_on_hypothesis)}` : ""}</div>`
        : (lastHist ? `<div class="evT">最新研判（${opWord[lastHist.op] || lastHist.op}）</div><div class="reason">${humanize(lastHist.reason || "")}</div>` : "");
    const handHtml = handoff
        ? `<div class="handB"><div class="t">接管条件${handoff.status === "triggered" ? "（已触发）" : ""}</div><div>${humanize(handoff.trigger || "")}</div>${(handoff.not_triggered_by || []).length ? `<div class="ntb">以下情况不算接管：${handoff.not_triggered_by.map(s => humanize(s)).join("；")}</div>` : ""}</div>`
        : "";
    $("hypBody").innerHTML = `
    ${conclusion ? `<div class="concl">${humanize(conclusion)}</div>` : ""}
    <div class="hypMain"><div class="t">主要观点${phaseB(main)}</div><div>${humanize(main.text || "")}</div></div>
    ${evHtml}
    ${counterHtml}
    ${deltaHtml}
    ${handHtml}
    ${backup ? `<div class="evT">备推演${phaseB(backup)}</div><div style="color:#c6dcee;font-size:12.5px">${humanize(backup.text || "")}</div>` : ""}`;
    $("hypUpd").textContent = `更新于 ${fmtTc(snap.meta.generated_at_ms, false)}`;
}
function renderPlan() {
    const plans = snap.watch_plans;
    if (!plans.length) {
        $("planBody").innerHTML = "暂无观察计划。";
        return;
    }
    const p = plans[plans.length - 1];
    const step = (n, cls, title, desc, extra = "") => `<div class="step ${cls}"><span class="n">${n}</span><div><div class="st">${title}</div><div class="sd">${desc}</div></div>${extra}</div>`;
    // 简报 v2：计划回四段链——候选/订单是提案区的事，不进简报主区，
    // 免得影子分析看起来像交易指令；计划绑了推演时明示在验证哪一个
    const serveHyp = p.hypothesis_id
        ? (snap.hypotheses || []).find((h) => h.hyp_id === p.hypothesis_id) : null;
    const serveNote = serveHyp
        ? `<div style="color:#55707f;font-size:11.5px;margin-bottom:4px">本计划在验证${serveHyp.role === "backup" ? "备推演" : "主要观点"}</div>` : "";
    $("planBody").innerHTML = serveNote + `<div class="steps">` +
        step(1, "done", "观察位置", numRef(p.watch_level || "") || "—") +
        step(2, "act", "等待行为", humanize(p.watch_behavior || "—"), `<span class="waitB">WAIT</span>`) +
        step(3, "", "复核触发", `${humanize(p.entry_trigger || "—")}<br><span style="color:#55707f;font-size:11.5px">满足后唤醒 AI 复核，不是入场指令</span>`) +
        step(4, "", "取消条件", humanize(p.cancel_if || "—")) + `</div>`;
}
// ---------- 底部：时间线 + 多空对照 ----------
function sparkline(barMs, anchor) {
    const bars = snap.bars;
    let idx = bars.findIndex((b) => b.t >= barMs - 1);
    if (idx < 0)
        idx = bars.length - 1;
    const from = Math.max(0, idx - 10);
    const win = bars.slice(from, Math.min(bars.length, idx + 11));
    if (win.length < 2)
        return "";
    const cs = win.map((b) => b.c);
    const anchors = anchor == null ? [] : (Array.isArray(anchor) ? anchor : [anchor]);
    let mn = Math.min(...cs), mx = Math.max(...cs);
    for (const a of anchors) {
        mn = Math.min(mn, a);
        mx = Math.max(mx, a);
    }
    const rg = (mx - mn) || 1;
    const X = (i) => (i / (win.length - 1) * 86).toFixed(1);
    const Y = (v) => (30 - (v - mn) / rg * 26).toFixed(1);
    const pts = cs.map((c, i) => `${X(i)},${Y(c)}`).join(" ");
    const upNet = cs[cs.length - 1] >= cs[0];
    const evI = Math.min(win.length - 1, Math.max(0, idx - from));
    const anchorLines = anchors.slice(0, 3).map(a => `<line x1="0" y1="${Y(a)}" x2="86" y2="${Y(a)}" stroke="#e8a33d" stroke-width="0.8" stroke-dasharray="3 2"/>`).join("");
    return `<svg width="86" height="32">${anchorLines}<polyline points="${pts}" fill="none" stroke="${upNet ? "#22b573" : "#e5484d"}" stroke-width="1.4"/><circle cx="${X(evI)}" cy="${Y(cs[evI])}" r="2.2" fill="#f5f9fc"/></svg>`;
}
function renderTimeline() {
    // 每类事件长得必须不一样（用户 2026-11-01 点名「看着都一样」）：
    // 颜色/标题/副文案全按类型分化，副文案给锚距现价、测试史、存续根数，
    // 迷你图叠锚线虚线 + 事件点白点，不再是同一条装饰线。
    const bars = snap.bars;
    const px = bars[bars.length - 1].c;
    const lastMs = bars[bars.length - 1].t;
    const ageBars = (ms) => Math.max(0, Math.round((lastMs - ms) / 900000));
    const anchorOf = (e) => {
        const g = e.payload?.gap_id ? gapById(e.payload.gap_id) : null;
        if (g)
            return g.anchor;
        if (e.payload?.anchor)
            return Number(e.payload.anchor);
        return undefined;
    };
    const META = {
        GAP_OPENED: e => {
            const a = anchorOf(e);
            return { color: e.direction === "up" ? "#2fbf71" : "#f0564f",
                t: `${e.direction === "up" ? "↑" : "↓"} 缺口建立`,
                s: a != null ? `${fmtPx(a)} · 位于现价${a >= px ? "上方" : "下方"} ${fmtNum(Math.abs(a - px))} 点 · 已开放 ${ageBars(e.bar_open_ms)} 根` : "新缺口立账" };
        },
        TEST_STARTED: e => {
            const a = anchorOf(e);
            const n = e.payload?.test_index || "";
            return { color: "#e8a33d", t: `回补测试 T${n} 开始`,
                s: a != null ? `${fmtPx(a)} · 此前 ${Math.max(0, (Number(n) || 1) - 1)} 次测试均未破` : "回补测试开始" };
        },
        TEST_ENDED: e => {
            const a = anchorOf(e);
            const touched = e.payload?.outcome === "anchor_touched";
            const g = e.payload?.gap_id ? gapById(e.payload.gap_id) : null;
            const t = (g?.tests || []).filter((x) => x.ended_ms && Math.abs(x.ended_ms - e.bar_open_ms) < 1400000)
                .sort((x, y) => Math.abs(x.ended_ms - e.bar_open_ms) - Math.abs(y.ended_ms - e.bar_open_ms))[0];
            const dur = t?.started_ms ? Math.max(1, Math.round((t.ended_ms - t.started_ms) / 900000)) : null;
            return { color: touched ? "#f0564f" : "#58a6d6", t: touched ? "测试触线" : "测试被拒",
                s: `${a != null ? `${fmtPx(a)} · ` : ""}${touched ? "价格已摸到缺口线" : "未触线即被打回"}${dur ? ` · 历时 ${dur} 根` : ""}` };
        },
        GAP_CLOSED: e => {
            const a = anchorOf(e);
            const g = e.payload?.gap_id ? gapById(e.payload.gap_id) : null;
            return { color: "#f0564f", t: "缺口回补 · 关账",
                s: a != null ? `${fmtPx(a)} · 共经 ${g?.test_count ?? "?"} 次测试后城破` : "回补关账" };
        },
    };
    // 横向时间轴（用户 2026-11-01 定：左右动，不要上下两排）；同一根 K 线
    // 同方向立账多座缺口合并成一个节点，免得一排看上去全是重复卡。
    const raw = snap.events.filter((e) => META[e.type]).slice(-18);
    const nodes = [];
    for (const e of raw) {
        const prev = nodes[nodes.length - 1];
        if (prev && e.type === "GAP_OPENED" && prev.e.type === "GAP_OPENED"
            && e.bar_open_ms === prev.e.bar_open_ms && e.direction === prev.e.direction) {
            prev.merged.push(e);
        }
        else
            nodes.push({ e, merged: [e] });
    }
    $("tlBody").innerHTML = nodes.length ? `<div class="tlTrack">${nodes.map(({ e, merged }) => {
        const m = META[e.type](e);
        if (merged.length > 1) {
            const anchors = merged.map(x => anchorOf(x)).filter((a) => a != null);
            return `<div class="node"><div class="tm">${fmtTc(e.bar_open_ms)}</div><div class="dot" style="background:${m.color}"></div><div class="tt" style="color:${m.color}">${e.direction === "up" ? "↑" : "↓"} 缺口建立 ×${merged.length}</div><div class="ts">${anchors.map(a => fmtPx(a)).join(" / ")} · 已开放 ${ageBars(e.bar_open_ms)} 根</div>${sparkline(e.bar_open_ms, anchors)}</div>`;
        }
        return `<div class="node"><div class="tm">${fmtTc(e.bar_open_ms)}</div><div class="dot" style="background:${m.color}"></div><div class="tt" style="color:${m.color}">${m.t}</div><div class="ts">${m.s}</div>${sparkline(e.bar_open_ms, anchorOf(e))}</div>`;
    }).join("")}</div>` : "暂无缺口事件。";
    const tlEl = $("tlBody");
    requestAnimationFrame(() => { tlEl.scrollLeft = tlEl.scrollWidth; });
}
// 多空行动对照已按用户 2026-11-01 要求下线（数据仍在快照 sides 里，页面不显示）
// ---------- 装配 ----------
let curSymbol = "BTCUSDT";
async function load(sym) {
    curSymbol = sym;
    $("symBTC").classList.toggle("on", sym === "BTCUSDT");
    $("symETH").classList.toggle("on", sym === "ETHUSDT");
    snap = await (await fetch(`data24/${sym}.json`)).json();
    buildLookups();
    const m = snap.meta, bars = snap.bars, last = bars[bars.length - 1];
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
    $("footLine").textContent = `缺口线 = 带的最外沿（支撑带最下 / 阻力带最上），碰到即销账 · MM 目标位未接线，本页不画 · 沙盘只读`;
}
window.addEventListener("resize", positionBands);
$("symBTC").addEventListener("click", () => load("BTCUSDT"));
$("symETH").addEventListener("click", () => load("ETHUSDT"));
load("BTCUSDT");
// 日内滚动：每 60 秒探一次新快照，token 变了才整页重渲染（数据由 roll_site 每 15 分钟整窗更新）
setInterval(async () => {
    try {
        const fresh = await (await fetch(`data24/${curSymbol}.json?t=${Date.now()}`)).json();
        if (!snap || fresh.meta.token !== snap.meta.token) {
            snap = fresh;
            buildLookups();
            const m = snap.meta, bars = snap.bars, last = bars[bars.length - 1];
            const prev = bars[bars.length - 2] || last;
            const chg = last.c - prev.c, pct = (chg / prev.c * 100);
            renderHeader();
            $("ohlcLine").innerHTML = `<span><b>${m.symbol}</b> · 15 · Binance</span><span>开 <b>${fmtPx(last.o)}</b></span><span>高 <b>${fmtPx(last.h)}</b></span><span>低 <b>${fmtPx(last.l)}</b></span><span>收 <b>${fmtPx(last.c)}</b></span><span class="${chg >= 0 ? "up" : "down"}">${chg >= 0 ? "+" : ""}${fmtPx(Math.abs(chg))} (${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)</span>`;
            buildZones();
            renderChart();
            renderBrief();
            renderPlan();
            renderTimeline();
            $("footLine").textContent = `缺口线 = 带的最外沿（支撑带最下 / 阻力带最上），碰到即销账 · MM 目标位未接线，本页不画 · 沙盘只读`;
        }
    }
    catch (e) { /* 网络抖动下轮再探 */ }
}, 60000);
// 时间线横向拖动 + 滚轮横移（只挂一次，tlBody 元素常驻）
{
    const tlEl = $("tlBody");
    let dragX = null, dragL = 0;
    tlEl.addEventListener("pointerdown", e => { dragX = e.clientX; dragL = tlEl.scrollLeft; });
    window.addEventListener("pointermove", e => { if (dragX != null)
        tlEl.scrollLeft = dragL - (e.clientX - dragX); });
    window.addEventListener("pointerup", () => { dragX = null; });
    tlEl.addEventListener("wheel", e => {
        if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
            tlEl.scrollLeft += e.deltaY;
            e.preventDefault();
        }
    }, { passive: false });
}
