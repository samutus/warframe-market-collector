// UI for craftable Prime sets only (two fixed charts + KPI integration)
const INDEX_URL = "data/analytics/sets_index.csv";
const SET_TS_DIR = "data/analytics/timeseries/";
const PARTS_LATEST_URL = "data/analytics/parts_latest_by_set.csv";

let setsIndex = [];
let partsLatest = [];
let filtered = [];
let current = null;
let priceChart, depthChart;

// Reset any inline sizes left by Chart.js (prevents runaway growth)
function resetCanvasSize(id) {
  const c = document.getElementById(id);
  if (!c) return;
  c.style.width = "";
  c.style.height = "";
  c.removeAttribute("width");
  c.removeAttribute("height");
}

// Helper to build a line chart with safe defaults (fixed box via CSS)
function buildLineChart(id, labels, datasets) {
  const ctx = document.getElementById(id).getContext("2d");
  return new Chart(ctx, {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,  // rely on .chart-box height
      animation: false,
      resizeDelay: 150,
      plugins: { legend: { position: "top" } },
      scales: { x: { ticks: { maxTicksLimit: 6 } } }
    }
  });
}

async function csvToRows(url) {
  const res = await fetch(url);
  const txt = await res.text();
  if (!txt.trim()) return [];
  const [head, ...lines] = txt.trim().split("\n");
  const cols = head.split(",");
  return lines.map(l => {
    const vals = l.split(","); // ok for our simple CSVs
    const obj = {};
    cols.forEach((c, i) => obj[c] = vals[i]);
    return obj;
  });
}

function formatNum(x, d=1) {
  const v = parseFloat(x);
  if (Number.isNaN(v)) return "-";
  return v.toFixed(d);
}

function renderTable() {
  const el = document.getElementById("itemTable");
  el.innerHTML = "";
  const header = document.createElement("div");
  header.className = "row header";
  header.innerHTML = `<div>Set</div><div>ROI%</div><div>Marge</div><div>KPI</div><div>BUY(set)</div>`;
  el.appendChild(header);

  filtered.forEach(r => {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = `
      <div>${r.set_url}</div>
      <div>${formatNum(r.roi_pct)}</div>
      <div>${formatNum(r.margin)}</div>
      <div>${formatNum(r.kpi_daily)}</div>
      <div>${formatNum(r.set_sell_med)}</div>
    `;
    row.addEventListener("click", () => selectSet(r));
    el.appendChild(row);
  });
}

function applyFilters() {
  const q = document.getElementById("search").value.toLowerCase().trim();
  const sort = document.getElementById("sort").value;

  filtered = setsIndex.filter(r => (r.set_url || "").toLowerCase().includes(q));

  const key = sort === "roi" ? "roi_pct"
            : sort === "margin" ? "margin"
            : sort === "kpi" ? "kpi_daily"
            : sort === "buy" ? "buy_med"
            : "opportunity_score"; // liquidity proxy
  filtered.sort((a,b) => (parseFloat(b[key]||0) - parseFloat(a[key]||0)));

  renderTable();
}

function renderPartsTable(setUrl) {
  const container = document.getElementById("partsTable");
  const rows = partsLatest.filter(r => (r.set_url || "").toLowerCase() === setUrl.toLowerCase());

  // Deduplicate by part_url; keep first non-NaN price and max qty
  const uniq = new Map();
  for (const r of rows) {
    const key = String(r.part_url || "");
    const qty = parseInt(r.quantity_for_set || "1", 10);
    const price = parseFloat(r.buy_med_latest);
    if (!uniq.has(key)) {
      uniq.set(key, { part: key, price: isNaN(price) ? null : price, qty: isNaN(qty) ? 1 : qty });
    } else {
      const u = uniq.get(key);
      u.qty = Math.max(u.qty, isNaN(qty) ? 1 : qty);
      if (u.price == null && !isNaN(price)) u.price = price;
    }
  }

  let html = `
    <table class="parts">
      <thead><tr><th>Pièce</th><th>Coût d'achat</th><th>Qté</th></tr></thead>
      <tbody>
  `;
  for (const { part, price, qty } of uniq.values()) {
    html += `<tr><td>${part}</td><td class="num">${price == null ? "-" : price.toFixed(1)}</td><td class="num">${qty}</td></tr>`;
  }
  html += `</tbody></table>`;
  container.innerHTML = html;
}

async function selectSet(r) {
  current = r;
  document.getElementById("itemTitle").textContent = r.set_url;
  document.getElementById("meta").textContent =
    `Dernière MAJ: ${r.latest_date} | SELL(set): ${formatNum(r.set_sell_med)} | `
    + `Coût pièces (BUY): ${formatNum(r.parts_cost_buy)} | Marge: ${formatNum(r.margin)} | ROI: ${formatNum(r.roi_pct)}% | `
    + `KPI 30j moy: ${formatNum(r.kpi_30d_avg)}`;


  renderPartsTable(r.set_url);

  // Load per-set time series (two charts only)
  const setTs = await csvToRows(`${SET_TS_DIR}${r.set_url}__set.csv`);
  const dates  = setTs.map(x => x.date);
  const margin = setTs.map(x => +x.margin || null);
  const bdepth = setTs.map(x => +x.buy_depth_med || null);      // orange (set buy side)
  const bottl  = setTs.map(x => +x.min_part_eff_depth || null); // green  (parts sell bottleneck)
  const setSell = setTs.map(x => +x.sell_med || null);        // SELL(set)
  const partsBuy= setTs.map(x => +x.parts_cost_buy || null);  // BUY(parts)

  // Destroy previous charts and reset canvases
  if (priceChart) priceChart.destroy();
  if (depthChart) depthChart.destroy();
  resetCanvasSize("priceChart");
  resetCanvasSize("depthChart");
  

  // Chart 1: Prices (3 curves)
  priceChart = buildLineChart("priceChart", dates, [
    { label: "SELL (set) – median", data: setSell, borderColor: "#2563eb", backgroundColor: "transparent" },
    { label: "Parts cost (BUY) – median", data: partsBuy, borderColor: "#ef4444", backgroundColor: "transparent" },
    { label: "Margin", data: margin, borderColor: "#0ea5e9", backgroundColor: "transparent" }
    ]);

  // Chart 2: Depths (2 curves) — green = parts (sell), orange = set (buy)
  depthChart = buildLineChart("depthChart", dates, [
    { label: "Min eff. SELL depth (parts)", data: bottl, borderColor: "#22c55e", backgroundColor: "transparent" },
    { label: "BUY depth (set) – median",    data: bdepth, borderColor: "#f59e0b", backgroundColor: "transparent" }
  ]);
}

async function boot() {
  [setsIndex, partsLatest] = await Promise.all([
    csvToRows(INDEX_URL),
    csvToRows(PARTS_LATEST_URL)
  ]);
  applyFilters();
  document.getElementById("search").addEventListener("input", applyFilters);
  document.getElementById("sort").addEventListener("change", applyFilters);
}
boot();
