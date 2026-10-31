const CST = 8 * 3600;
let snap = null;
let symbol = "BTCUSDT";
let edgeWalls = [];
const $ = (id) => document.getElementById(id);
const fmtTc = (ms) => {
    const d = new Date(ms + CST * 1000);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getUTCMonth() + 1}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
};
const fmtPx = (x) => x >= 1000 ? x.toFixed(2) : x.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
function gapSemantics(g) {
    if (g.direction === "up")
        return { color: "#1f7a5c", guard: "多方", trapped: "空方被套于锚下", attacker: "空方自上回补攻城" };
    return { color: "#bc3f22", guard: "空方", trapped: "多方被套于锚上", attacker: "多方自下回补攻城" };
}
// 沿墙群：从最近的缺口起，同址（相对种子锚 <=0.35%）成群
function edgeGroup(gapsSortedAsc, px, side) {
    const cand = side === "below"
        ? [...gapsSortedAsc].filter(g => g.anchor < px).reverse()
        : gapsSortedAsc.filter(g => g.anchor > px);
    if (!cand.length)
        return null;
    const seed = cand[0].anchor;
    const members = cand.filter(g => Math.abs(g.anchor - seed) / seed <= 0.0035);
    const tests = members.reduce((s, g) => s + g.test_count, 0);
    return {
        side, members, seed,
        lo: Math.min(...members.map(g => g.anchor)), hi: Math.max(...members.map(g => g.anchor)),
        tests, grade: (tests >= 2 || members.length >= 5) ? "要塞" : "据点",
        color: gapSemantics(members[0]).color,
        mixed: new Set(members.map(g => g.direction)).size > 1,
    };
}
function wallTitle(w) {
    const g0 = w.members[0];
    const sem = gapSemantics(g0);
    const siege = w.tests > 0 ? `已挡攻城 ⚔×${w.tests}` : "尚未被攻";
    return `${fmtPx(w.lo)}${w.hi !== w.lo ? "–" + fmtPx(w.hi) : ""} · ${w.mixed ? "双向" : sem.guard + "方"}沿墙·${w.grade} · ${w.members.length}座缺口 · ${siege}`;
}
function drawBoard() {
    const bars = snap.bars;
    const px = bars[bars.length - 1].c;
    const gapsAsc = [...snap.open_gaps].sort((a, b) => a.anchor - b.anchor);
    const lower = edgeGroup(gapsAsc, px, "below");
    const upper = edgeGroup(gapsAsc, px, "above");
    edgeWalls = [lower, upper].filter(Boolean);
    const outerBelow = gapsAsc.filter(g => lower && g.anchor < lower.lo).length + (lower ? 0 : 0);
    const outerAbove = gapsAsc.filter(g => upper && g.anchor > upper.hi).length;
    const belowCount = gapsAsc.filter(g => g.anchor < px).length;
    const aboveCount = gapsAsc.filter(g => g.anchor > px).length;
    const bandLo = lower ? lower.lo : px * 0.985;
    const bandHi = upper ? upper.hi : px * 1.015;
    const topPrice = bandHi * 1.006, botPrice = bandLo * 0.994;
    const W = 1060, H = 700, X0 = 170, X1 = 640;
    const y = (p) => H - (p - botPrice) / (topPrice - botPrice) * H;
    let svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;background:#fff;border:1px solid #ddd8cb">`;
    // 波段外折叠条
    svg += `<rect x="${X0}" y="${y(topPrice)}" width="${X1 - X0}" height="${Math.max(y(bandHi) - y(topPrice), 26)}" fill="#f7f4ec" stroke="#ddd8cb"/>
    <text x="${X0 + 10}" y="${y(topPrice) + 20}" font-size="12" fill="#666">波段外 · 上方另有 ${Math.max(aboveCount - (upper ? upper.members.length : 0), 0)} 堵墙（里程参考，不在当前战场）</text>`;
    svg += `<rect x="${X0}" y="${y(bandLo)}" width="${X1 - X0}" height="${Math.max(y(botPrice) - y(bandLo), 26)}" fill="#f7f4ec" stroke="#ddd8cb"/>
    <text x="${X0 + 10}" y="${y(bandLo) + 20}" font-size="12" fill="#666">波段外 · 下方另有 ${Math.max(belowCount - (lower ? lower.members.length : 0), 0)} 堵墙${lower && belowCount - lower.members.length === 0 ? "——下沿一破，下方再无开放缺口" : ""}</text>`;
    // 当前波段（唯一的城）
    const posPct = ((px - bandLo) / (bandHi - bandLo) * 100).toFixed(0);
    const thickPct = ((bandHi - bandLo) / px * 100).toFixed(2);
    svg += `<rect x="${X0}" y="${y(bandHi)}" width="${X1 - X0}" height="${y(bandLo) - y(bandHi)}" fill="#fdf3e3" stroke="#b07d2b" stroke-width="2"/>
    <text x="${X0 + 12}" y="${y(bandHi) + 24}" font-size="15" font-weight="700" fill="#16140f">当前波段（争夺中）</text>
    <text x="${X0 + 12}" y="${y(bandHi) + 44}" font-size="12" fill="#555">城厚 ${thickPct}% · 现价位于城内 ${posPct}% 处（自下沿起）</text>`;
    // 城内地形：波段内 major 摆动位（只是地形，不是墙）；标签按像素去重防叠字
    let lastLabelY = -100;
    const terrain = snap.levels
        .filter(lv => lv.kind === "swing_major" && lv.lo != null && lv.lo > bandLo && lv.lo < bandHi && Math.abs(lv.lo - px) / px >= 0.0008)
        .sort((a, b) => b.lo - a.lo);
    for (const lv of terrain) {
        svg += `<line x1="${X0 + 6}" y1="${y(lv.lo)}" x2="${X1 - 6}" y2="${y(lv.lo)}" stroke="#c9c2ae" stroke-width="1" stroke-dasharray="3 5"/>`;
        if (Math.abs(y(lv.lo) - lastLabelY) >= 12) {
            svg += `<text x="${X1 - 10}" y="${y(lv.lo) - 3}" font-size="10" fill="#a39a83" text-anchor="end">${lv.level_key} ${fmtPx(lv.lo)}</text>`;
            lastLabelY = y(lv.lo);
        }
    }
    // 沿墙：厚带 + 垛口 + 标签
    const drawWall = (w, tag) => {
        if (!w) {
            const yy = tag === "上沿" ? y(bandHi) : y(bandLo);
            return `<text x="${X1 + 12}" y="${yy + 4}" font-size="12.5" fill="#b07d2b" font-weight="700">${tag}无墙（该侧无开放缺口）</text>`;
        }
        const yT = y(w.hi), yB = y(w.lo);
        const hBand = Math.max(yB - yT, 9);
        let cren = "";
        for (let x = X0; x < X1 - 12; x += 18)
            cren += `<rect x="${x}" y="${yT - 5}" width="9" height="5" fill="${w.color}"/>`;
        return `<g class="wall" data-tag="${tag}" style="cursor:pointer">${cren}
      <rect class="wallBody" x="${X0}" y="${yT}" width="${X1 - X0}" height="${hBand}" fill="${w.color}"/>
      <text x="${X1 + 12}" y="${yT + hBand / 2 + 4}" font-size="12" fill="${w.color}" font-weight="700">${tag} ${wallTitle(w)}</text></g>`;
    };
    svg += drawWall(upper, "上沿") + drawWall(lower, "下沿");
    // 现价旗
    svg += `<line x1="${X0 - 8}" y1="${y(px)}" x2="${X1 + 8}" y2="${y(px)}" stroke="#16140f" stroke-width="1.4" stroke-dasharray="7 4"/>
    <text x="${X1 + 12}" y="${y(px) - 8}" font-size="13" font-weight="700" fill="#16140f">⚑ 现价 ${fmtPx(px)}</text>`;
    // 双军最近一击（城内行动道）
    const lane = (sideKey, x) => {
        const sd = snap.sides[sideKey];
        if (!sd || !sd.segments.length)
            return "";
        const seg = [...sd.segments].reverse().find((g) => !g.open) || sd.segments[sd.segments.length - 1];
        if (seg.p0 == null || seg.net_progress == null)
            return "";
        const dir = seg.direction === "up" ? 1 : -1;
        const p0 = Math.max(Math.min(seg.p0, bandHi), bandLo);
        const ext = Math.max(Math.min(seg.p0 + dir * (seg.favorable ?? seg.net_progress), bandHi), bandLo);
        const end = Math.max(Math.min(seg.p0 + dir * seg.net_progress, bandHi), bandLo);
        const bend = sideKey === "up" ? x + 16 : x - 16;
        const col = sideKey === "up" ? "#1f7a5c" : "#bc3f22";
        return `<g><polyline points="${x},${y(p0)} ${bend},${y(ext)} ${x},${y(end)}" fill="none" stroke="${col}" stroke-width="2.4" ${seg.open ? 'stroke-dasharray="5 3"' : ""}/>
      <circle cx="${x}" cy="${y(end)}" r="4.5" fill="${col}"/></g>`;
    };
    svg += lane("up", 62) + lane("down", 122);
    svg += `<text x="62" y="16" font-size="11" fill="#1f7a5c" text-anchor="middle">多方道</text>
          <text x="122" y="16" font-size="11" fill="#bc3f22" text-anchor="middle">空方道</text>`;
    svg += "</svg>";
    const chip = (sideKey) => {
        const sd = snap.sides[sideKey];
        if (!sd || !sd.segments.length)
            return "";
        const seg = [...sd.segments].reverse().find((g) => !g.open) || sd.segments[sd.segments.length - 1];
        const col = sideKey === "up" ? "#1f7a5c" : "#bc3f22";
        return `<span style="color:${col};font-weight:700">${sideKey === "up" ? "多方" : "空方"}最近一击</span> ${seg.segment_id} @${seg.level_key}${seg.open ? "（进行中）" : ""}：净推进 ${seg.net_progress ?? "—"}，回吐 ${seg.giveback ?? "—"}（回吐比 ${seg.giveback_ratio != null ? Number(seg.giveback_ratio).toFixed(2) : "—"}），用时 ${seg.elapsed_bars ?? "—"} 根`;
    };
    $("laneChips").innerHTML = [chip("up"), chip("down")].filter(Boolean).join("　·　");
    $("board").innerHTML = svg;
    document.querySelectorAll(".wall").forEach(n => n.addEventListener("click", () => {
        const w = n.dataset.tag === "上沿" ? upper : lower;
        if (w)
            showWall(w, n.dataset.tag);
    }));
    showBand(lower, upper, px, bandLo, bandHi);
}
function showWall(w, tag) {
    $("detailBody").innerHTML = `<b>${tag}沿墙 · ${wallTitle(w)}</b><br>` +
        w.members.map((g) => {
            const sem = gapSemantics(g);
            return `<div class="seg">${g.gap_id} @${g.level_key}：锚 ${fmtPx(g.anchor)}，${g.direction === "up" ? "向上" : "向下"}缺口，立账 ${g.opened_ms ? fmtTc(g.opened_ms) : "—"}<br>
        <span class="meta">守军=${sem.guard}方 · ${sem.trapped} · ${sem.attacker} · 已攻 ${g.test_count} 次</span></div>`;
        }).join("");
}
function showBand(lower, upper, px, bandLo, bandHi) {
    const line = (w, tag) => w
        ? `<div class="seg"><b>${tag}</b>${wallTitle(w)}</div>`
        : `<div class="seg"><b>${tag}</b>无开放缺口（无墙）</div>`;
    $("detailBody").innerHTML =
        `<b>当前波段总览</b>（${fmtPx(bandLo)}${!lower ? "（展示下界）" : ""} – ${fmtPx(bandHi)}${!upper ? "（展示上界）" : ""}，现价 ${fmtPx(px)}）<br>` +
            line(upper, "上沿") + line(lower, "下沿") +
            `<div class="meta">只看两沿的理由：波段边缘是成交最密、被套库存最厚的地方；波段内与波段外的缺口不在当前战场。点任一沿墙看逐座缺口。</div>`;
}
function renderPanels() {
    const m = snap.meta;
    $("metaLine").innerHTML =
        `<span class="badge">${m.token}</span><span class="badge">rev ${m.state_revision}</span>` +
            `<span class="badge">最新收盘 ${fmtTc(m.cursor_close_ms)}</span>` +
            (m.ai.stale ? `<span class="badge stale">AI 基于旧快照，待复核</span>` : `<span class="badge">AI 已复核至当前</span>`);
    $("hypBody").innerHTML = snap.hypotheses.length ? snap.hypotheses.map((h) => `
    <div class="hyp ${h.status || ""}"><b>${h.hyp_id}</b> · ${h.status || ""}
      <div>${h.text || ""}</div>
      <div class="meta">支持：${(h.support_refs || []).join("、") || "—"}<br>反证：${(h.counter_refs || []).join("、") || "—"}</div>
    </div>`).join("") : "暂无假设。";
    $("planBody").innerHTML = snap.watch_plans.length ? snap.watch_plans.map((p) => `
    <div><div class="seg"><b>计划</b>${p.plan_id}（${p.status || ""}）</div>
    <div class="seg"><b>观察位置</b>${p.watch_level || "—"}</div>
    <div class="seg"><b>等待行为</b>${p.watch_behavior || "—"}</div>
    <div class="seg"><b>入场触发</b>${p.entry_trigger || "—"}</div>
    <div class="seg"><b>取消条件</b>${p.cancel_if || "—"}</div></div>`).join("") : "暂无观察计划。";
    $("brokenBody").innerHTML = snap.closed_gaps_recent.length ? [...snap.closed_gaps_recent].reverse().map((g) => `<div class="seg">💥 ${g.gap_id}：锚 ${fmtPx(g.anchor)}，${g.direction === "up" ? "向上" : "向下"}缺口，生前被攻 ${g.test_count} 次后关账（城破）</div>`).join("") : "近期无破城。";
    $("tlBody").innerHTML = [...snap.events].reverse().slice(0, 60).map((e) => `<div class="ev" data-lvl="${e.level_key || ""}"><b>${e.type}</b> ${e.level_key || ""} <span class="meta">${e.event_id}</span></div>`).join("");
    document.querySelectorAll(".ev").forEach(n => n.addEventListener("click", () => {
        const lvl = n.dataset.lvl;
        const w = edgeWalls.find(x => x.members.some((g) => g.level_key === lvl));
        if (w) {
            showWall(w, w.side === "above" ? "上沿" : "下沿");
            window.scrollTo({ top: 0, behavior: "smooth" });
        }
        else
            $("detailBody").innerHTML = `事件关联位置 ${lvl} 不在波段两沿（属波段内地形或波段外），不在当前战场重点内。`;
    }));
    $("footLine").textContent =
        `快照 ${m.token} · 生成 ${fmtTc(m.generated_at_ms)}（账本重放重建）· ${m.symbol} ${m.timeframe} 共 ${m.bars_count} 根 · ${m.source} · 沙盘只读，无下单入口`;
}
async function load(sym) {
    symbol = sym;
    $("symBTC").classList.toggle("on", sym === "BTCUSDT");
    $("symETH").classList.toggle("on", sym === "ETHUSDT");
    snap = await (await fetch(`data/${sym}.json`)).json();
    drawBoard();
    renderPanels();
}
$("symBTC").addEventListener("click", () => load("BTCUSDT"));
$("symETH").addEventListener("click", () => load("ETHUSDT"));
load("BTCUSDT");
