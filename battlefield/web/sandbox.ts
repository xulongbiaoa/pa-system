// W09 战略沙盘：主舞台不是 K 线，是城池。
// 城池 = 上下两堵缺口墙之间的价格带（用户定版透镜：缺口边缘=城墙、被套者=守军、
// 回补测试=攻城、触锚关账=城破）。全部对象来自 export_web.py 的同源快照，
// 本页只做「锚点聚成墙带、墙带隔出城池」的展示聚合，不新造任何事实数值。
type AnyObj = { [k: string]: any };

const CST = 8 * 3600;
let snap: AnyObj | null = null;
let symbol = "BTCUSDT";
let walls: AnyObj[] = [];
let wallByLevel: { [k: string]: AnyObj } = {};

const $ = (id: string) => document.getElementById(id)!;
const fmtTc = (ms: number) => {
  const d = new Date(ms + CST * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCMonth() + 1}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
};
const fmtPx = (x: number) => x >= 1000 ? x.toFixed(2) : x.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");

// ---------- 墙带聚合：相邻锚（相对距离 <=0.35%）聚为一堵墙 ----------
function buildWalls(gaps: AnyObj[]): AnyObj[] {
  const sorted = [...gaps].sort((a, b) => b.anchor - a.anchor);
  const out: AnyObj[] = [];
  for (const g of sorted) {
    const w = out[out.length - 1];
    if (w && Math.abs(w.seed - g.anchor) / w.seed <= 0.0035) {
      w.gaps.push(g); w.lo = Math.min(w.lo, g.anchor); w.hi = Math.max(w.hi, g.anchor);
      w.tests += g.test_count; w.dirs.add(g.direction);
    } else {
      out.push({ seed: g.anchor, hi: g.anchor, lo: g.anchor, gaps: [g], tests: g.test_count, dirs: new Set([g.direction]) });
    }
  }
  for (const w of out) {
    w.mid = (w.hi + w.lo) / 2;
    w.side = w.dirs.has("up") && w.dirs.has("down") ? "mixed" : (w.dirs.has("up") ? "up" : "down");
    w.grade = (w.tests >= 2 || w.gaps.length >= 5) ? "要塞" : "据点";
    for (const g of w.gaps) wallByLevel[g.level_key] = w;
  }
  return out;
}

const SIDE = {
  up: { color: "#1f7a5c", name: "多方", wall: "多方城墙", guard: "多方守军（空方被套于墙下，回补须自下攻城）" },
  down: { color: "#bc3f22", name: "空方", wall: "空方城墙", guard: "空方守军（多方被套于墙上，回补须自上攻城）" },
  mixed: { color: "#b07d2b", name: "双向", wall: "争夺墙", guard: "双向缺口同址，守军混杂" },
} as AnyObj;

function wallLabel(w: AnyObj): string {
  const s = SIDE[w.side];
  const siege = w.tests > 0 ? `已挡 ⚔×${w.tests} 次攻城` : "尚未被攻";
  return `${fmtPx(w.lo)}${w.hi !== w.lo ? "–" + fmtPx(w.hi) : ""} · ${s.name}墙·${w.grade} · ${w.gaps.length}座 · ${siege}`;
}

function drawBoard() {
  const px = snap!.bars[snap!.bars.length - 1].c;
  const all = buildWalls(snap!.open_gaps);
  const inWin = all.filter(w => w.mid >= px * 0.93 && w.mid <= px * 1.07);
  const foldedUp = all.filter(w => w.mid > px * 1.07).length;
  const foldedDown = all.filter(w => w.mid < px * 0.93).length;
  walls = inWin;
  const topPrice = (inWin.length ? inWin[0].hi : px) * 1.012;
  const botPrice = (inWin.length ? inWin[inWin.length - 1].lo : px) * 0.988;
  const W = 1060, H = 780, X0 = 170, X1 = 640;
  const y = (p: number) => H - (p - botPrice) / (topPrice - botPrice) * H;

  let svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;background:#fff;border:1px solid #ddd8cb">`;
  // 城池：相邻两墙之间 + 两端无墙地带
  const edges: AnyObj[] = [];
  edges.push({ top: topPrice, bottom: inWin.length ? inWin[0].hi : topPrice, above: null, below: inWin[0] || null, outer: true });
  for (let i = 0; i + 1 < inWin.length; i++)
    edges.push({ top: inWin[i].lo, bottom: inWin[i + 1].hi, above: inWin[i], below: inWin[i + 1], outer: false });
  if (inWin.length)
    edges.push({ top: inWin[inWin.length - 1].lo, bottom: botPrice, above: inWin[inWin.length - 1], below: null, outer: true });

  let cityNo = 0, pxCitySeen = false;
  const cityNames: string[] = [];
  for (const e of edges) {
    const containsPx = px <= e.top && px >= e.bottom;
    if (!e.outer) cityNo++;
    const name = e.outer ? "无墙地带" : (containsPx ? "现价城" : "");
    cityNames.push(name);
    if (containsPx) pxCitySeen = true;
  }
  // 自现价城向两侧编号
  const pxIdx = edges.findIndex(e => px <= e.top && px >= e.bottom);
  edges.forEach((e, i) => {
    if (e.outer) e.name = i < pxIdx ? "上方无墙地带" : "下方无墙地带";
    else if (i === pxIdx) e.name = "现价城（争夺中）";
    else e.name = i < pxIdx ? `上方第 ${pxIdx - i} 城` : `下方第 ${i - pxIdx} 城`;
  });

  edges.forEach((e, i) => {
    const yT = y(e.top), yB = y(e.bottom);
    const isPx = i === pxIdx;
    const thick = ((e.top - e.bottom) / px * 100).toFixed(2);
    svg += `<g class="city" data-city="${i}" style="cursor:pointer">
      <rect x="${X0}" y="${yT}" width="${X1 - X0}" height="${Math.max(yB - yT, 3)}"
        fill="${isPx ? "#fdf3e3" : (e.outer ? "#f7f4ec" : "#fbfaf6")}"
        stroke="${isPx ? "#b07d2b" : "#ddd8cb"}" stroke-width="${isPx ? 2 : 1}"/>
      ${(yB - yT) >= 20 ? `<text x="${X0 + 10}" y="${yT + 16}" font-size="12.5" font-weight="${isPx ? 700 : 400}" fill="#16140f">${e.name}</text>` : ""}
      ${(yB - yT) >= 38 ? `<text x="${X0 + 10}" y="${yT + 33}" font-size="11" fill="#666">城厚 ${thick}%（${fmtPx(e.bottom)} – ${fmtPx(e.top)}）</text>` : ""}
    </g>`;
  });

  // 城墙：带垛口的厚线 + 右侧标签 + 攻城徽记
  inWin.forEach((w, wi) => {
    const s = SIDE[w.side];
    const yT = y(w.hi), yB = y(w.lo);
    const hBand = Math.max(yB - yT, 7);
    let cren = "";
    for (let x = X0; x < X1 - 12; x += 18)
      cren += `<rect x="${x}" y="${yT - 5}" width="9" height="5" fill="${s.color}"/>`;
    svg += `<g class="wall" data-wall="${wi}" style="cursor:pointer">
      ${cren}
      <rect class="wallBody" x="${X0}" y="${yT}" width="${X1 - X0}" height="${hBand}" fill="${s.color}" opacity="0.88"/>
      <text x="${X1 + 12}" y="${yT + hBand / 2 + 4}" font-size="11.5" fill="${s.color}" font-weight="700">${wallLabel(w)}</text>
    </g>`;
  });

  // 现价旗
  svg += `<line x1="${X0 - 8}" y1="${y(px)}" x2="${X1 + 8}" y2="${y(px)}" stroke="#16140f" stroke-width="1.4" stroke-dasharray="7 4"/>
    <text x="${X1 + 12}" y="${y(px) - 8}" font-size="13" font-weight="700" fill="#16140f">⚑ 现价 ${fmtPx(px)}</text>`;

  // 双军最近一击：左双道箭头（起点 p0 → 极值 → 落点）
  const lane = (sideKey: string, x: number) => {
    const sd = snap!.sides[sideKey];
    if (!sd || !sd.segments.length) return "";
    const seg = [...sd.segments].reverse().find((g: AnyObj) => !g.open) || sd.segments[sd.segments.length - 1];
    if (seg.p0 == null || seg.net_progress == null) return "";
    const dir = seg.direction === "up" ? 1 : -1;
    const p0 = seg.p0, ext = p0 + dir * (seg.favorable ?? seg.net_progress), end = p0 + dir * seg.net_progress;
    const bend = sideKey === "up" ? x + 16 : x - 16;
    const col = SIDE[sideKey].color;
    return `<g opacity="0.95">
      <polyline points="${x},${y(p0)} ${bend},${y(ext)} ${x},${y(end)}" fill="none" stroke="${col}" stroke-width="2.4" ${seg.open ? 'stroke-dasharray="5 3"' : ""}/>
      <circle cx="${x}" cy="${y(end)}" r="4.5" fill="${col}"/>
    </g>`;
  };
  svg += lane("up", 62) + lane("down", 122);
  svg += `<text x="62" y="16" font-size="11" fill="#1f7a5c" text-anchor="middle">多方道</text>
          <text x="122" y="16" font-size="11" fill="#bc3f22" text-anchor="middle">空方道</text>`;
  svg += "</svg>";
  const chip = (sideKey: string) => {
    const sd = snap!.sides[sideKey];
    if (!sd || !sd.segments.length) return "";
    const seg = [...sd.segments].reverse().find((g: AnyObj) => !g.open) || sd.segments[sd.segments.length - 1];
    const col = SIDE[sideKey].color;
    return `<span style="color:${col};font-weight:700">${SIDE[sideKey].name}最近一击</span> ${seg.segment_id} @${seg.level_key}${seg.open ? "（进行中）" : ""}：净推进 ${seg.net_progress ?? "—"}，回吐 ${seg.giveback ?? "—"}（回吐比 ${seg.giveback_ratio != null ? Number(seg.giveback_ratio).toFixed(2) : "—"}），用时 ${seg.elapsed_bars ?? "—"} 根`;
  };
  $("laneChips").innerHTML = [chip("up"), chip("down")].filter(Boolean).join("　·　");
  $("board").innerHTML =
    ((foldedUp || foldedDown) ? `<div class="meta" style="padding:2px 2px 6px">${foldedUp ? `↑ 画外上方还有 ${foldedUp} 堵墙（超出 ±7% 窗）` : ""}${foldedUp && foldedDown ? " · " : ""}${foldedDown ? `↓ 画外下方还有 ${foldedDown} 堵墙` : ""}</div>` : "") + svg;

  // 交互：点墙/城出详情
  document.querySelectorAll(".wall").forEach(n => n.addEventListener("click", () => {
    const w = walls[Number((n as HTMLElement).dataset.wall)];
    showWall(w);
    document.querySelectorAll(".wallBody").forEach(b => b.classList.remove("wallFlash"));
    (n.querySelector(".wallBody") as Element).classList.add("wallFlash");
  }));
  document.querySelectorAll(".city").forEach(n => n.addEventListener("click", () => {
    const e = edges[Number((n as HTMLElement).dataset.city)];
    showCity(e);
  }));
  (window as AnyObj)._edges = edges;
}

function showWall(w: AnyObj) {
  const s = SIDE[w.side];
  $("detailBody").innerHTML =
    `<b>${wallLabel(w)}</b><br>${s.guard}<br>` +
    w.gaps.map((g: AnyObj) =>
      `<div class="seg">${g.gap_id} @${g.level_key}：锚 ${fmtPx(g.anchor)}，立账 ${g.opened_ms ? fmtTc(g.opened_ms) : "—"}，攻城 ${g.test_count} 次` +
      (g.tests.length ? `（最近 ${g.tests[g.tests.length - 1].started_ms ? fmtTc(g.tests[g.tests.length - 1].started_ms) : "—"} 起）` : "") + `</div>`).join("");
}
function showCity(e: AnyObj) {
  const line = (w: AnyObj | null, tag: string) => w ? `<div class="seg"><b>${tag}</b>${wallLabel(w)}</div>` : `<div class="seg"><b>${tag}</b>无墙（画外）</div>`;
  $("detailBody").innerHTML = `<b>${e.name}</b>（${fmtPx(e.bottom)} – ${fmtPx(e.top)}）<br>` +
    line(e.above, "上沿") + line(e.below, "下沿") +
    `<div class="meta">城池的上下沿就是这两堵缺口墙：上沿被自下攻破（关账）= 城向上易手，下沿被自上攻破 = 城向下易手。</div>`;
}

function renderPanels() {
  const m = snap!.meta;
  $("metaLine").innerHTML =
    `<span class="badge">${m.token}</span><span class="badge">rev ${m.state_revision}</span>` +
    `<span class="badge">最新收盘 ${fmtTc(m.cursor_close_ms)}</span>` +
    (m.ai.stale ? `<span class="badge stale">AI 基于旧快照，待复核</span>` : `<span class="badge">AI 已复核至当前</span>`);
  $("hypBody").innerHTML = snap!.hypotheses.length ? snap!.hypotheses.map((h: AnyObj) => `
    <div class="hyp ${h.status || ""}"><b>${h.hyp_id}</b> · ${h.status || ""}
      <div>${h.text || ""}</div>
      <div class="meta">支持：${(h.support_refs || []).join("、") || "—"}<br>反证：${(h.counter_refs || []).join("、") || "—"}</div>
    </div>`).join("") : "暂无假设。";
  $("planBody").innerHTML = snap!.watch_plans.length ? snap!.watch_plans.map((p: AnyObj) => `
    <div><div class="seg"><b>计划</b>${p.plan_id}（${p.status || ""}）</div>
    <div class="seg"><b>观察位置</b>${p.watch_level || "—"}</div>
    <div class="seg"><b>等待行为</b>${p.watch_behavior || "—"}</div>
    <div class="seg"><b>入场触发</b>${p.entry_trigger || "—"}</div>
    <div class="seg"><b>取消条件</b>${p.cancel_if || "—"}</div></div>`).join("") : "暂无观察计划。";
  $("brokenBody").innerHTML = snap!.closed_gaps_recent.length ? [...snap!.closed_gaps_recent].reverse().map((g: AnyObj) =>
    `<div class="seg">💥 ${g.gap_id}：锚 ${fmtPx(g.anchor)}，${g.direction === "up" ? "向上" : "向下"}缺口，生前被攻 ${g.test_count} 次后关账（城破）</div>`).join("") : "近期无破城。";
  $("tlBody").innerHTML = [...snap!.events].reverse().slice(0, 60).map((e: AnyObj) =>
    `<div class="ev" data-lvl="${e.level_key || ""}"><b>${e.type}</b> ${e.level_key || ""} <span class="meta">${e.event_id}</span></div>`).join("");
  document.querySelectorAll(".ev").forEach(n => n.addEventListener("click", () => {
    const lvl = (n as HTMLElement).dataset.lvl!;
    const w = wallByLevel[lvl];
    if (w && walls.includes(w)) { showWall(w); window.scrollTo({ top: 0, behavior: "smooth" }); }
    else $("detailBody").innerHTML = `事件关联位置 ${lvl} 不在当前沙盘窗口内（或无对应开放缺口墙）。`;
  }));
  $("footLine").textContent =
    `快照 ${m.token} · 生成 ${fmtTc(m.generated_at_ms)}（账本重放重建）· ${m.symbol} ${m.timeframe} 共 ${m.bars_count} 根 · ${m.source} · 沙盘只读，无下单入口`;
}

async function load(sym: string) {
  symbol = sym;
  $("symBTC").classList.toggle("on", sym === "BTCUSDT");
  $("symETH").classList.toggle("on", sym === "ETHUSDT");
  wallByLevel = {};
  snap = await (await fetch(`data/${sym}.json`)).json();
  drawBoard();
  renderPanels();
}

$("symBTC").addEventListener("click", () => load("BTCUSDT"));
$("symETH").addEventListener("click", () => load("ETHUSDT"));
load("BTCUSDT");
