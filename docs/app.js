// Tailwind UI for craftable Prime sets with normalized KPI* and sort direction toggle

// ---- Data endpoints (relative to docs/) ----
const INDEX_URL = "data/analytics/sets_index.csv";
const SET_TS_DIR = "data/analytics/timeseries/";
const PARTS_LATEST_URL = "data/analytics/parts_latest_by_set.csv";

let setsIndex = [];
let partsLatest = [];
let filtered = [];
let current = null;
let priceChart, depthChart;
let sortAsc = false; // false = décroissant (par défaut)

// cache for per-set latest volume min, to avoid re-fetching
const volCache = new Map();

// ---- Helpers ----
function resetCanvasSize(id) {
  const c = document.getElementById(id);
  if (!c) return;
  c.style.width = "";
  c.style.height = "";
  c.removeAttribute("width");
  c.removeAttribute("height");
}

function buildLineChart(id, labels, datasets) {
  const ctx = document.getElementById(id).getContext("2d");
  return new Chart(ctx, {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      resizeDelay: 120,
      plugins: {
        legend: { position: "top" },
        tooltip: { mode: "index", intersect: false },
      },
      hover: { mode: "nearest", intersect: false },
      scales: {
        x: { ticks: { maxTicksLimit: 6 } },
        y: { beginAtZero: false },
      },
    },
  });
}

// CSV minimal parser
async function csvToRows(url) {
  const res = await fetch(url);
  const txt = await res.text();
  if (!txt.trim()) return [];
  const [head, ...lines] = txt.trim().split("\n");
  const cols = head.split(",");
  return lines.map((l) => {
    const vals = l.split(",");
    const obj = {};
    cols.forEach((c, i) => (obj[c] = vals[i]));
    return obj;
  });
}

function n(x) { const v = parseFloat(x); return Number.isFinite(v) ? v : 0; }
function formatNum(x, d = 1) {
  const v = parseFloat(x);
  if (!Number.isFinite(v)) return "–";
  return v.toFixed(d);
}

// ---- KPI (normalized) ----
const KPI_CONST = {
  ROI_REF: 150,
  ROI_SHARPNESS: 60,
  MARGIN_FLOOR: 5,
  MARGIN_TARGET: 20,
};
function sigmoid(z) { return 1 / (1 + Math.exp(-z)); }
function kpiCompositeRaw({ roi_pct, margin }, volMin) {
  const { ROI_REF, ROI_SHARPNESS, MARGIN_FLOOR, MARGIN_TARGET } = KPI_CONST;
  const f_roi = sigmoid((n(roi_pct) - ROI_REF) / ROI_SHARPNESS); // 0..1
  const f_margin = Math.min(Math.max((n(margin) - MARGIN_FLOOR) / Math.max(1, (MARGIN_TARGET - MARGIN_FLOOR)), 0), 1);
  const v = Math.max(0, n(volMin));
  return v * Math.max(0, n(margin)) * f_roi * f_margin; // unnormalized
}
// Robust normalization to [0,1] with ~P90 mapped to 0.8
let kpiScale = { lo: 0, hi: 1 };
function quantile(arr, q) {
  if (!arr.length) return 0;
  const p = (arr.length - 1) * q;
  const b = Math.floor(p), t = p - b;
  if (arr[b + 1] !== undefined) return arr[b] * (1 - t) + arr[b + 1] * t;
  return arr[b];
}
function recomputeKpiScale() {
  const samples = setsIndex
    .map(r => (r.vol_min == null ? null : kpiCompositeRaw(r, r.vol_min)))
    .filter(x => Number.isFinite(x) && x > 0)
    .sort((a,b)=>a-b);
  if (samples.length < 5) {
    const mx = Math.max(1, ...samples, 1);
    kpiScale = { lo: 0, hi: mx };
    return;
  }
  const p10 = quantile(samples, 0.10);
  const p90 = quantile(samples, 0.90);
  let lo = p10;
  let hi = lo + (p90 - lo) / 0.8; // map ~P90 -> 0.8
  if (!Number.isFinite(hi) || hi <= lo) hi = lo + (p90 || 1) + 1;
  kpiScale = { lo, hi };
}
function kpiCompositeNorm({ roi_pct, margin }, volMin) {
  const raw = kpiCompositeRaw({ roi_pct, margin }, volMin);
  const z = (raw - kpiScale.lo) / (kpiScale.hi - kpiScale.lo);
  return Math.max(0, Math.min(1, z));
}
function getRowKpiNorm(r) {
  if (r.vol_min == null) return null;
  return kpiCompositeNorm(r, r.vol_min);
}

// ---------- LEFT PANEL (list) ----------
async function ensureVolAndUpdateCell(row, idx) {
  const vol = await getLatestVolMin(row.set_url);
  row.vol_min = vol;

  // update volume cell
  const volCell = document.getElementById(`vol-cell-${idx}`);
  if (volCell) volCell.textContent = vol == null ? "–" : formatNum(vol, 0);

  // update KPI cell (needs normalization scale)
  recomputeKpiScale();
  const kpiCell = document.getElementById(`kpi-cell-${idx}`);
  const kpin = getRowKpiNorm(row);
  if (kpiCell) kpiCell.textContent = kpin == null ? "…" : Math.round(kpin * 100);

  // and refresh ordering if sorting by KPI/volume
  applyFilters();
}

function renderTable() {
  const el = document.getElementById("itemTable");
  el.innerHTML = "";

  // header row
  const header = document.createElement("div");
  header.className =
    "grid grid-cols-[1fr,90px,90px,110px,90px] gap-2 px-3 py-2 sticky top-0 bg-white z-10 text-xs font-semibold text-slate-600";
  header.innerHTML = `
    <div>Set</div>
    <div class="text-right">ROI%</div>
    <div class="text-right">Marge</div>
    <div class="text-right">KPI (0–100)</div>
    <div class="text-right">Vol (min)</div>`;
  el.appendChild(header);

  // rows
  filtered.forEach((r, idx) => {
    const row = document.createElement("div");
    row.className =
      "grid grid-cols-[1fr,90px,90px,110px,90px] gap-2 items-center px-3 py-2 border-b border-slate-100 cursor-pointer hover:bg-slate-50";
    const kpin = getRowKpiNorm(r);
    row.innerHTML = `
      <div class="truncate font-medium text-slate-800">${r.set_url}</div>
      <div class="text-right">${formatNum(r.roi_pct)}</div>
      <div class="text-right">${formatNum(r.margin)}</div>
      <div class="text-right" id="kpi-cell-${idx}">${kpin == null ? "…" : Math.round(kpin*100)}</div>
      <div class="text-right" id="vol-cell-${idx}">${r.vol_min == null ? "…" : formatNum(r.vol_min, 0)}</div>
    `;
    row.addEventListener("click", () => selectSet(r));
    el.appendChild(row);

    // lazy load vol if missing
    if (r.vol_min == null) ensureVolAndUpdateCell(r, idx);
  });
}

function applyFilters() {
  const q = document.getElementById("search").value.toLowerCase().trim();
  const sort = document.getElementById("sort").value;

  filtered = setsIndex.filter((r) => (r.set_url || "").toLowerCase().includes(q));

  const key =
    sort === "roi" ? "roi_pct" :
    sort === "margin" ? "margin" :
    sort === "kpi" ? "kpi_norm" :
    sort === "volume" ? "vol_min" :
    "opportunity_score";

  filtered.sort((a, b) => {
    let av, bv;
    if (key === "kpi_norm") { av = getRowKpiNorm(a); bv = getRowKpiNorm(b); }
    else if (key === "vol_min") { av = a.vol_min; bv = b.vol_min; }
    else { av = n(a[key]); bv = n(b[key]); }

    // Unknowns last
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;

    return sortAsc ? (av - bv) : (bv - av);
  });

  renderTable();
}

// ---- Compute latest volume min for a set ----
async function getLatestVolMin(setUrl) {
  if (volCache.has(setUrl)) return volCache.get(setUrl);
  try {
    const rows = await csvToRows(`${SET_TS_DIR}${setUrl}__set.csv`);
    let vol = null;
    for (let i = rows.length - 1; i >= 0; i--) {
      const b = parseFloat(rows[i].buy_depth_med);
      const s = parseFloat(rows[i].min_part_eff_depth);
      if (Number.isFinite(b) || Number.isFinite(s)) {
        vol = Math.min(Number.isFinite(b) ? b : Infinity, Number.isFinite(s) ? s : Infinity);
        if (!Number.isFinite(vol)) vol = (Number.isFinite(b) ? b : s);
        break;
      }
    }
    if (!Number.isFinite(vol)) vol = null;
    volCache.set(setUrl, vol);
    return vol;
  } catch (e) {
    console.warn("Failed to load timeseries for", setUrl, e);
    volCache.set(setUrl, null);
    return null;
  }
}

function renderPartsTable() {
  const container = document.getElementById("partsTable");
  const rows = partsLatest
    .filter((p) => p.set_url === current.set_url && p.platform === current.platform)
    .sort((a, b) => String(a.part_url).localeCompare(String(b.part_url)));

  const uniq = new Map();
  for (const r of rows) {
    const key = String(r.part_url || "");
    const qty = parseInt(r.quantity_for_set || "1", 10);
    const unit = r.unit_cost_latest ?? r.buy_med_latest ?? r.sell_med_latest;
    const price = parseFloat(unit);
    if (!uniq.has(key)) {
      uniq.set(key, {
        part: key,
        price: Number.isFinite(price) ? price : null,
        qty: Number.isFinite(qty) ? qty : 1,
        src: r.unit_cost_source || (n(r.buy_med_latest) > 0 ? "BUY" : (n(r.sell_med_latest) > 0 ? "SELL" : ""))
      });
    } else {
      const u = uniq.get(key);
      u.qty = Math.max(u.qty, Number.isFinite(qty) ? qty : 1);
      if (u.price == null && Number.isFinite(price)) u.price = price;
    }
  }

  let html = `
    <table class="min-w-full text-sm">
      <thead>
        <tr class="text-left text-slate-600 border-b border-slate-200">
          <th class="px-2 py-2">Pièce</th>
          <th class="px-2 py-2 text-right">Coût d'achat</th>
          <th class="px-2 py-2 text-right">Qté</th>
        </tr>
      </thead>
      <tbody>`;

  for (const { part, price, qty, src } of uniq.values()) {
    const priceStr = price == null ? "–" : price.toFixed(1);
    const title = src ? `title="Source: ${src}"` : "";
    html += `<tr class="odd:bg-slate-50">
      <td class="px-2 py-2 font-medium">${part}</td>
      <td class="px-2 py-2 text-right" ${title}>${priceStr}</td>
      <td class="px-2 py-2 text-right">${qty}</td>
    </tr>`;
  }
  html += `</tbody></table>`;
  container.innerHTML = html;
}

function metaBadge(label, value, tone) {
  const base = "inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium";
  const palette = {
    sky: "bg-sky-50 text-sky-700 ring-1 ring-sky-200",
    emerald: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
    amber: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
    slate: "bg-slate-100 text-slate-700 ring-1 ring-slate-200",
    violet: "bg-violet-50 text-violet-700 ring-1 ring-violet-200",
  }[tone] || "bg-slate-100 text-slate-700 ring-1 ring-slate-200";
  return `<span class="${base} ${palette}"><span class="opacity-70">${label}</span><span>${value}</span></span>`;
}

async function selectSet(r) {
  current = r;
  const title = document.getElementById("itemTitle");
  title.textContent = r.set_url;

  // Load time series for the set (two charts + volume)
  const setTs = await csvToRows(`${SET_TS_DIR}${r.set_url}__set.csv`);
  const dates   = setTs.map((x) => x.date);
  const margin  = setTs.map((x) => +x.margin || null);
  const bdepth  = setTs.map((x) => +x.buy_depth_med || null);
  const bottl   = setTs.map((x) => +x.min_part_eff_depth || null);
  const setSell = setTs.map((x) => +x.sell_med || null);
  const partsBuy= setTs.map((x) => +x.parts_cost_buy || null);

  // latest volume (min of the two depths)
  let latestVol = null;
  for (let i = setTs.length - 1; i >= 0; i--) {
    const b = bdepth[i], s = bottl[i];
    if (Number.isFinite(b) || Number.isFinite(s)) {
      latestVol = Math.min(Number.isFinite(b) ? b : Infinity, Number.isFinite(s) ? s : Infinity);
      if (!Number.isFinite(latestVol)) latestVol = Number.isFinite(b) ? b : s;
      break;
    }
  }
  r.vol_min = latestVol;
  volCache.set(r.set_url, latestVol);
  recomputeKpiScale();

  // right meta
  const meta = document.getElementById("meta");
  const kpiStar = kpiCompositeNorm(r, latestVol);
  meta.innerHTML = `
    <div class="flex flex-wrap gap-2 items-center">
      <span class="text-slate-500 text-xs">Dernière MAJ: ${r.latest_date}</span>
      ${metaBadge("SELL(set)", formatNum(r.set_sell_med), "sky")}
      ${metaBadge("Coût pièces (BUY)", formatNum(r.parts_cost_buy), "slate")}
      ${metaBadge("Marge", formatNum(r.margin), "emerald")}
      ${metaBadge("ROI", formatNum(r.roi_pct) + "%", "amber")}
      ${metaBadge("Vol (min)", latestVol == null ? "–" : formatNum(latestVol, 0), "violet")}
      ${metaBadge("KPI* (0–100)", Math.round(kpiStar*100), "sky")}
    </div>`;

  renderPartsTable();

  // Destroy previous charts and reset canvases
  if (priceChart) priceChart.destroy();
  if (depthChart) depthChart.destroy();
  resetCanvasSize("priceChart");
  resetCanvasSize("depthChart");

  // Chart 1: Prices
  priceChart = buildLineChart("priceChart", dates, [
    { label: "SELL (set) – median", data: setSell, borderColor: "#2563eb", backgroundColor: "transparent" },
    { label: "Parts cost (BUY) – median", data: partsBuy, borderColor: "#ef4444", backgroundColor: "transparent" },
    { label: "Margin", data: margin, borderColor: "#0ea5e9", backgroundColor: "transparent" },
  ]);

  // Chart 2: Depths
  depthChart = buildLineChart("depthChart", dates, [
    { label: "Min eff. SELL depth (parts)", data: bottl, borderColor: "#22c55e", backgroundColor: "transparent" },
    { label: "BUY depth (set) – median", data: bdepth, borderColor: "#f59e0b", backgroundColor: "transparent" },
  ]);

  // Re-render left table (may affect KPI/volume values and ordering)
  applyFilters();
}

// ---------- BOOT ----------
async function boot() {
  [setsIndex, partsLatest] = await Promise.all([
    csvToRows(INDEX_URL),
    csvToRows(PARTS_LATEST_URL),
  ]);

  // initialize vol_min from cache (none yet)
  setsIndex.forEach((r) => { r.vol_min = volCache.get(r.set_url) ?? null; });

  // UI: sort direction button
  const sortBtn = document.getElementById("sortDirBtn");
  const sortIcon = document.getElementById("sortDirIcon");
  function updateSortIcon(){ sortIcon.style.transform = sortAsc ? "rotate(180deg)" : "rotate(0deg)"; }
  sortBtn.addEventListener("click", ()=>{ sortAsc = !sortAsc; updateSortIcon(); applyFilters(); });
  updateSortIcon();

  recomputeKpiScale();
  applyFilters();
  document.getElementById("search").addEventListener("input", applyFilters);
  document.getElementById("sort").addEventListener("change", applyFilters);

  // warm up: fetch volume for the first ~20 rows to make sorting by volume/KPI nicer
  const top = setsIndex.slice(0, 20);
  for (const r of top) {
    if (r.vol_min == null) {
      r.vol_min = await getLatestVolMin(r.set_url);
      recomputeKpiScale();
      applyFilters();
    }
  }
}
boot();
