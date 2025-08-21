// Tailwind UI for craftable Prime sets – KPI normalisé (back) + heatmap + tri asc/desc

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

// Minimal CSV parser (valeurs simples, séparateur virgule)
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

// ---- KPI (fourni par le back) ----
// On lit kpi_norm (0..1) ou à défaut kpi_0_100/100
function getKpi01(r) {
  const a = parseFloat(r.kpi_norm);
  if (Number.isFinite(a)) return a;
  const b = parseFloat(r.kpi_0_100);
  if (Number.isFinite(b)) return b / 100;
  return null;
}

// Map KPI [0,1] -> couleur (0=rouge → 1=vert)
function kpiColorFrom01(x) {
  const v = Number.isFinite(+x) ? +x : 0;
  const hue = 0 + (140 * v); // 0 (rouge) -> 140 (vert)
  const sat = 85;            // %
  const light = 45;          // %
  return `hsl(${hue} ${sat}% ${light}%)`;
}

// ---------- LEFT PANEL (list) ----------
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

    const kpin = getKpi01(r);
    const kpiTxt = (kpin == null ? "…" : Math.round(kpin * 100));
    const kpiStyle = `style="color:${kpiColorFrom01(kpin)}"`;

    const vol = parseFloat(r.vol_min);
    const volTxt = Number.isFinite(vol) ? formatNum(vol, 0) : "…";

    row.innerHTML = `
      <div class="truncate font-medium text-slate-800">${r.set_url}</div>
      <div class="text-right">${formatNum(r.roi_pct)}</div>
      <div class="text-right">${formatNum(r.margin)}</div>
      <div class="text-right" id="kpi-cell-${idx}" ${kpiStyle}>${kpiTxt}</div>
      <div class="text-right" id="vol-cell-${idx}">${volTxt}</div>
    `;
    row.addEventListener("click", () => selectSet(r));
    el.appendChild(row);
  });
}

function applyFilters() {
  const q = document.getElementById("search").value.toLowerCase().trim();
  const sort = document.getElementById("sort").value;

  filtered = setsIndex.filter((r) => (r.set_url || "").toLowerCase().includes(q));

  // Clé de tri -> valeur numérique
  filtered.sort((a, b) => {
    let av, bv;
    if (sort === "kpi") {
      av = getKpi01(a);
      bv = getKpi01(b);
    } else if (sort === "volume") {
      av = parseFloat(a.vol_min);
      bv = parseFloat(b.vol_min);
    } else if (sort === "roi") {
      av = parseFloat(a.roi_pct);
      bv = parseFloat(b.roi_pct);
    } else if (sort === "margin") {
      av = parseFloat(a.margin);
      bv = parseFloat(b.margin);
    } else {
      av = parseFloat(a.opportunity_score);
      bv = parseFloat(b.opportunity_score);
    }

    // Unknowns last
    const aU = !(Number.isFinite(av));
    const bU = !(Number.isFinite(bv));
    if (aU && bU) return 0;
    if (aU) return 1;
    if (bU) return -1;

    return sortAsc ? (av - bv) : (bv - av);
  });

  renderTable();
}

// ---------- RIGHT PANEL (detail) ----------
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
        src: r.unit_cost_source || (n(r.buy_med_latest) > 0 ? "BUY" : (n(r.sell_med_latest) > 0 ? "SELL" : "")),
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

  // KPI + Vol (back)
  const kpin = getKpi01(r);
  const kpiHtml = (kpin == null)
    ? "…"
    : `<span style="color:${kpiColorFrom01(kpin)}">${Math.round(kpin*100)}</span>`;

  // right meta
  const meta = document.getElementById("meta");
  meta.innerHTML = `
    <div class="flex flex-wrap gap-2 items-center">
      <span class="text-slate-500 text-xs">Dernière MAJ: ${r.latest_date}</span>
      ${metaBadge("SELL(set)", formatNum(r.set_sell_med), "sky")}
      ${metaBadge("Coût pièces (BUY)", formatNum(r.parts_cost_buy), "slate")}
      ${metaBadge("Marge", formatNum(r.margin), "emerald")}
      ${metaBadge("ROI", formatNum(r.roi_pct) + "%", "amber")}
      ${metaBadge("Vol (min)", Number.isFinite(parseFloat(r.vol_min)) ? formatNum(r.vol_min, 0) : "–", "violet")}
      ${metaBadge("KPI (0–100)", kpiHtml, "sky")}
    </div>`;

  renderPartsTable();

  // Charger la timeserie pour les graphiques (prix + profondeurs)
  const setTs = await csvToRows(`${SET_TS_DIR}${r.set_url}__set.csv`);
  const dates   = setTs.map((x) => x.date);
  const margin  = setTs.map((x) => +x.margin || null);
  const bdepth  = setTs.map((x) => +x.buy_depth_med || null);
  const bottl   = setTs.map((x) => +x.min_part_eff_depth || null);
  const setSell = setTs.map((x) => +x.sell_med || null);
  const partsBuy= setTs.map((x) => +x.parts_cost_buy || null);

  // Reset + render charts
  if (priceChart) priceChart.destroy();
  if (depthChart) depthChart.destroy();
  resetCanvasSize("priceChart");
  resetCanvasSize("depthChart");

  priceChart = buildLineChart("priceChart", dates, [
    { label: "SELL (set) – median", data: setSell, borderColor: "#2563eb", backgroundColor: "transparent" },
    { label: "Parts cost (BUY) – median", data: partsBuy, borderColor: "#ef4444", backgroundColor: "transparent" },
    { label: "Margin", data: margin, borderColor: "#0ea5e9", backgroundColor: "transparent" },
  ]);

  depthChart = buildLineChart("depthChart", dates, [
    { label: "Min eff. SELL depth (parts)", data: bottl, borderColor: "#22c55e", backgroundColor: "transparent" },
    { label: "BUY depth (set) – median", data: bdepth, borderColor: "#f59e0b", backgroundColor: "transparent" },
  ]);

  // Re-render list (pour refléter sélection si besoin)
  applyFilters();
}

// ---------- BOOT ----------
async function boot() {
  [setsIndex, partsLatest] = await Promise.all([
    csvToRows(INDEX_URL),
    csvToRows(PARTS_LATEST_URL),
  ]);

  // UI: bouton de direction du tri
  const sortBtn = document.getElementById("sortDirBtn");
  const sortIcon = document.getElementById("sortDirIcon");
  function updateSortIcon(){ sortIcon.style.transform = sortAsc ? "rotate(180deg)" : "rotate(0deg)"; }
  sortBtn.addEventListener("click", ()=>{ sortAsc = !sortAsc; updateSortIcon(); applyFilters(); });
  updateSortIcon();

  applyFilters();
  document.getElementById("search").addEventListener("input", applyFilters);
  document.getElementById("sort").addEventListener("change", applyFilters);
}
boot();
