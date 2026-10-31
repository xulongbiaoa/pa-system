const CST = 8 * 3600; // 图表按 UTC 渲染，时间戳 +8h 显示为北京时间
let snap = null;
let symbol = "BTCUSDT";
let chart = null;
let series = null;
let priceLines = [];
let selectedEvent = null;
let mode = "live"; // live | asknown:<idx>
const $ = (id) => document.getElementById(id);
const fmtT = (ms) => {
    const d = new Date(ms);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getMonth() + 1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};
const fmtTc = (ms) => {
    const d = new Date(ms + CST * 1000);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getUTCMonth() + 1}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
};
function barSec(ms) { return Math.floor(ms / 1000) + CST; }
function annotations() {
    try {
        return JSON.parse(localStorage.getItem("bf-anno-" + snap.meta.token) || "[]");
    }
    catch {
        return [];
    }
}
function saveAnnotations(a) {
    localStorage.setItem("bf-anno-" + snap.meta.token, JSON.stringify(a));
}
function clearPriceLines() {
    for (const pl of priceLines) {
        try {
            series.removePriceLine(pl);
        }
        catch { /* noop */ }
    }
    priceLines = [];
}
function drawChart(bars, gaps, levels, events) {
    if (!chart) {
        chart = LightweightCharts.createChart($("chart"), {
            layout: { background: { color: "#ffffff" }, textColor: "#16140f" },
            grid: { vertLines: { color: "#eee9dc" }, horzLines: { color: "#eee9dc" } },
            timeScale: { timeVisible: true, secondsVisible: false },
        });
        series = chart.addCandlestickSeries({
            upColor: "#1f7a5c", downColor: "#bc3f22", borderVisible: false,
            wickUpColor: "#1f7a5c", wickDownColor: "#bc3f22",
        });
        new ResizeObserver(() => chart.applyOptions({ width: $("chart").clientWidth })).observe($("chart"));
    }
    series.setData(bars.map(b => ({
        time: barSec(b.t), open: b.o, high: b.h, low: b.l, close: b.c,
    })));
    clearPriceLines();
    const last = bars[bars.length - 1];
    const px = last ? last.c : 0;
    let hidden = 0;
    if ($("lyGaps").checked) {
        const sorted = [...gaps].sort((a, b) => Math.abs(a.anchor - px) - Math.abs(b.anchor - px));
        const show = sorted.slice(0, 10);
        hidden += sorted.length - show.length;
        for (const g of show) {
            priceLines.push(series.createPriceLine({
                price: g.anchor, color: g.direction === "up" ? "#1f7a5c" : "#bc3f22",
                lineWidth: 1, lineStyle: 2, axisLabelVisible: true,
                title: `${g.gap_id} 测${g.test_count}`,
            }));
        }
    }
    if ($("lyLevels").checked) {
        const majors = levels.filter(lv => lv.lo != null && (lv.kind === "swing_major" || lv.level_key.startsWith("SWM-")));
        const sorted = majors.sort((a, b) => Math.abs(a.lo - px) - Math.abs(b.lo - px));
        const show = sorted.slice(0, 8);
        hidden += sorted.length - show.length;
        for (const lv of show) {
            priceLines.push(series.createPriceLine({
                price: lv.lo, color: "#8a8474", lineWidth: 1, lineStyle: 1,
                axisLabelVisible: false, title: lv.level_key,
            }));
        }
    }
    $("layerInfo").textContent = hidden > 0 ? `图层按距现价最近优先，另有 ${hidden} 个对象已折叠` : "";
    drawMarkers(events);
    chart.timeScale().setVisibleLogicalRange({ from: bars.length - 180, to: bars.length + 5 });
}
function drawMarkers(events) {
    if (!series)
        return;
    if (!$("lyEvents").checked) {
        series.setMarkers([]);
        return;
    }
    const showTests = $("lyTests").checked;
    const style = {
        GAP_OPENED: { shape: "circle", color: "#b07d2b", pos: "aboveBar", text: "立账" },
        GAP_CLOSED: { shape: "circle", color: "#555", pos: "aboveBar", text: "关账" },
        TEST_STARTED: { shape: "arrowDown", color: "#b07d2b", pos: "aboveBar", text: "测始" },
        TEST_ENDED: { shape: "arrowUp", color: "#b07d2b", pos: "belowBar", text: "测终" },
        RECLAIMED: { shape: "square", color: "#bc3f22", pos: "belowBar", text: "收回" },
    };
    const ms = [];
    const lastBarT = snap && snap.bars.length ? snap.bars[snap.bars.length - 1].t : null;
    for (const e of events) {
        const s = style[e.type];
        if (!s)
            continue;
        if (!showTests && (e.type === "TEST_STARTED" || e.type === "TEST_ENDED"))
            continue;
        const t = e.bar_open_ms != null ? e.bar_open_ms : barMsFromId(e.bar_id);
        if (t == null)
            continue;
        if (lastBarT != null && lastBarT - t > 250 * 900000)
            continue; // 只标最近 250 根的事件，防堆叠
        const isSel = selectedEvent && selectedEvent.event_id === e.event_id;
        ms.push({
            time: barSec(t), position: s.pos, shape: s.shape, color: s.color,
            text: isSel ? "▶" + s.text : (e.type.startsWith("TEST") || e.type === "RECLAIMED" ? "" : s.text),
        });
    }
    ms.sort((a, b) => a.time - b.time);
    series.setMarkers(ms);
}
function barMsFromId(id) {
    if (!id)
        return null;
    const n = Number(String(id).split("/").pop());
    return Number.isFinite(n) ? n : null;
}
function renderSides(sides) {
    const one = (name, s) => {
        if (!s || !s.recorded)
            return `<div><b>${name}</b><br>未观测到活动（≠力量为零）</div>`;
        const rows = s.segments.map((g) => `<div class="seg">${g.segment_id} @${g.level_key}${g.open ? "（进行中）" : ""}：净推进 ${g.net_progress ?? "—"}，回吐 ${g.giveback ?? "—"}，用时 ${g.elapsed_bars ?? "—"} 根</div>`).join("");
        return `<div><b>${name}</b>（事件 ${s.events_count} 条）${rows}</div>`;
    };
    $("sidesBody").innerHTML = `<div class="side">${one("多方", sides.up)}${one("空方", sides.down)}</div>`;
}
function refSpan(r) {
    return `<span class="ref" data-ref="${r}">${r}</span>`;
}
function renderHyps(hyps, staleNote) {
    const el = $("hypBody");
    if (!hyps.length) {
        el.innerHTML = staleNote + "暂无假设。";
        return;
    }
    el.innerHTML = staleNote + hyps.map(h => `
    <div class="hyp ${h.status || ""}">
      <b>${h.hyp_id}</b> · ${h.status || ""}
      <div>${h.text || ""}</div>
      <div class="meta">支持：${(h.support_refs || []).map(refSpan).join("、") || "—"}<br>
      反证：${(h.counter_refs || []).map(refSpan).join("、") || "—"}<br>
      修订史：${(h.history || []).length} 条</div>
    </div>`).join("");
    el.querySelectorAll(".ref").forEach(n => n.addEventListener("click", () => jumpRef(n.dataset.ref)));
}
function renderPlans(plans) {
    const el = $("planBody");
    if (!plans.length) {
        el.innerHTML = "暂无观察计划。";
        return;
    }
    el.innerHTML = plans.map(p => `
    <div>
      <div class="seg"><b>计划</b>${p.plan_id}（${p.status || ""}）</div>
      <div class="seg"><b>观察位置</b>${p.watch_level || "—"}</div>
      <div class="seg"><b>等待行为</b>${p.watch_behavior || "—"}</div>
      <div class="seg"><b>入场触发</b>${p.entry_trigger || "—"}</div>
      <div class="seg"><b>取消条件</b>${p.cancel_if || "—"}</div>
    </div>`).join("");
}
function renderTimeline(events) {
    const el = $("tlBody");
    const annos = annotations();
    const rows = [...events].reverse().slice(0, 120).map(e => {
        const t = e.bar_open_ms != null ? e.bar_open_ms : barMsFromId(e.bar_id);
        const hasAnno = annos.some(a => a.event_id === e.event_id);
        return `<div class="ev ${selectedEvent && selectedEvent.event_id === e.event_id ? "sel" : ""}" data-ev="${e.event_id}">
      <span class="t">${e.type}</span> <span class="lens-${(e.lens || "actor").replace("+", "_")}">${e.level_key || ""}</span>
      <span class="meta">${t != null ? fmtTc(t) : ""} ${e.event_id}${hasAnno ? " · 有批注" : ""}</span></div>`;
    }).join("");
    el.innerHTML = rows || "无事件。";
    el.querySelectorAll(".ev").forEach(n => n.addEventListener("click", () => {
        const ev = events.find(e => e.event_id === n.dataset.ev);
        if (ev)
            selectEvent(ev, events);
    }));
}
function selectEvent(ev, events) {
    selectedEvent = ev;
    $("annoCtx").textContent = `已选事件 ${ev.event_id}（${ev.type} @ ${ev.level_key || ""}）。批注将绑定当前快照 ${snap.meta.token}。`;
    const t = ev.bar_open_ms != null ? ev.bar_open_ms : barMsFromId(ev.bar_id);
    if (chart && t != null) {
        const idx = snap.bars.findIndex((b) => b.t === t);
        if (idx >= 0)
            chart.timeScale().setVisibleLogicalRange({ from: idx - 30, to: idx + 30 });
    }
    drawMarkers(events);
    renderTimeline(events);
    renderAnnotations();
}
function jumpRef(r) {
    if (!snap)
        return;
    if (r.startsWith("GAP-")) {
        const g = snap.open_gaps.find((x) => x.gap_id === r);
        if (g && g.opened_ms != null && chart) {
            const idx = snap.bars.findIndex((b) => b.t === g.opened_ms);
            if (idx >= 0)
                chart.timeScale().setVisibleLogicalRange({ from: idx - 30, to: idx + 40 });
        }
    }
    else if (r.startsWith("ev-")) {
        const ev = currentEvents().find((e) => e.event_id === r);
        if (ev)
            selectEvent(ev, currentEvents());
    }
}
function currentEvents() {
    if (mode === "live")
        return snap.events;
    const idx = Number(mode.split(":")[1]);
    const ak = snap.as_known[idx];
    return (ak ? ak.events_tail : []).map((e) => ({ ...e, bar_open_ms: barMsFromId(e.bar_id) }));
}
function foldHyps(upto) {
    const hyps = [];
    let seq = 0;
    for (let i = 0; i <= upto; i++) {
        const out = snap.brain_outputs[i];
        if (!out)
            continue;
        for (const op of out.hypothesis_ops || []) {
            if (op.op === "add") {
                seq++;
                hyps.push({ hyp_id: "H" + seq, status: "active", text: op.text, support_refs: op.support_refs || [], counter_refs: op.counter_refs || [], history: [{ op: "add", reason: op.reason }] });
            }
            else {
                const h = hyps.find(x => x.hyp_id === op.hyp_id);
                if (h) {
                    h.history = h.history || [];
                    h.history.push({ op: op.op, reason: op.reason });
                    if (op.op === "challenge")
                        h.status = "challenged";
                    if (op.op === "supersede")
                        h.status = "superseded";
                    if (op.op === "confirm")
                        h.status = "active";
                }
            }
        }
    }
    return hyps;
}
function applyMode() {
    if (!snap)
        return;
    const m = snap.meta;
    if (mode === "live") {
        $("metaLine").innerHTML =
            `<span class="badge">${m.token}</span><span class="badge">rev ${m.state_revision}</span>` +
                `<span class="badge">最新收盘 ${fmtTc(m.cursor_close_ms)}</span>` +
                (m.data_health.missing_bars > 0 || m.data_health.continuity_broken
                    ? `<span class="badge bad">数据健康异常：缺根 ${m.data_health.missing_bars}</span>`
                    : `<span class="badge">数据完整</span>`) +
                (m.ai.stale ? `<span class="badge stale">AI 基于旧快照（cursor ${m.ai.last_read_cursor}），待复核</span>`
                    : `<span class="badge">AI 已复核至当前</span>`);
        drawChart(snap.bars, snap.open_gaps, snap.levels, snap.events);
        renderSides(snap.sides);
        renderHyps(snap.hypotheses, m.ai.stale ? `<div class="badge stale">以下解释基于 rev ${m.ai.last_read_cursor}，新事实已到、尚未复核</div>` : "");
        renderPlans(snap.watch_plans);
        renderTimeline(snap.events);
    }
    else {
        const idx = Number(mode.split(":")[1]);
        const out = snap.brain_outputs[idx];
        const ak = snap.as_known[idx];
        const bars = snap.bars.slice(0, out.read_cursor);
        $("metaLine").innerHTML =
            `<span class="badge">AS_KNOWN</span><span class="badge">大脑输出 #${idx + 1} · read_cursor ${out.read_cursor}</span>` +
                `<span class="badge">动作 ${out.action}</span><span class="badge stale">历史时点，非当前判断</span>`;
        drawChart(bars, [], ak ? ak.levels : [], currentEvents());
        renderSides(snap.sides); // 双方行动为当前投影，历史模式下仅作参考——下方注明
        $("sidesBody").innerHTML = `<div class="meta">历史模式：双方行动段为当前投影，不代表当时已知；地形/事件/假设已按当时时点截断。</div>` + $("sidesBody").innerHTML;
        renderHyps(foldHyps(idx).filter(h => h.status !== "superseded"), "");
        const plans = [];
        for (let i = 0; i <= idx; i++)
            if (snap.brain_outputs[i].watch_plan)
                plans[0] = snap.brain_outputs[i].watch_plan;
        renderPlans(plans.map(p => ({ ...p, status: "proposed" })));
        renderTimeline(currentEvents());
    }
    renderAnnotations();
    $("footLine").textContent =
        `快照 ${m.token} · 生成 ${fmtTc(m.generated_at_ms)}（账本重放重建，算法=当前代码，即 RECONSTRUCTED 口径）· 范围 ${m.symbol} ${m.timeframe} 共 ${m.bars_count} 根 · ${m.source} · 本页只读，无下单与改判入口`;
}
function renderAnnotations() {
    const el = $("annoList");
    const annos = annotations();
    el.innerHTML = annos.map(a => `<div class="anno">${fmtT(a.ts)} · ${a.event_id} · ${a.text}</div>`).join("");
}
async function load(sym) {
    symbol = sym;
    $("symBTC").classList.toggle("on", sym === "BTCUSDT");
    $("symETH").classList.toggle("on", sym === "ETHUSDT");
    snap = await (await fetch(`data/${sym}.json`)).json();
    const sel = $("modeSel");
    sel.innerHTML = `<option value="live">LIVE（最新投影）</option>` +
        snap.brain_outputs.map((o, i) => `<option value="asknown:${i}">AS_KNOWN · 输出#${i + 1}（cursor ${o.read_cursor}）</option>`).join("");
    mode = "live";
    selectedEvent = null;
    applyMode();
}
$("symBTC").addEventListener("click", () => load("BTCUSDT"));
$("symETH").addEventListener("click", () => load("ETHUSDT"));
$("modeSel").addEventListener("change", e => { mode = e.target.value; applyMode(); });
for (const id of ["lyGaps", "lyLevels", "lyEvents", "lyTests"])
    $(id).addEventListener("change", () => applyMode());
$("annoAdd").addEventListener("click", () => {
    const text = $("annoText").value.trim();
    if (!text || !selectedEvent)
        return;
    const a = annotations();
    a.push({ ts: Date.now(), event_id: selectedEvent.event_id, text, author: "user" });
    saveAnnotations(a);
    $("annoText").value = "";
    renderAnnotations();
    renderTimeline(currentEvents());
});
load("BTCUSDT");
