// UI for craftable Prime sets only
const INDEX_URL = "data/analytics/sets_index.csv";
const SET_TS_DIR = "data/analytics/timeseries/";
const PARTS_LATEST_URL = "data/analytics/parts_latest_by_set.csv";

let setsIndex = [];      // rows from sets_index.csv
let partsLatest = [];    // all parts snapshot
let filtered = [];
let current = null;
let priceChart, depthChart, marginChart;

async function csvToRows(url) {
  const res = await fetch(url);
  const txt = await res.text();
  if (!txt.trim()) return [];
  const [head, ...lines] = txt.trim().split("\n");
  const cols = head.split(",");
  return lines.map(l => {
    // basic CSV split; ok for our simple content
    const vals = l.split(",");
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
  header.innerHTML = `<div>Set</div><div>ROI%</div><div>Marge</div><div>BUY(set)</div>`;
  el.appendChild(header);

  filtered.forEach(r => {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = `
      <div>${r.set_url}</div>
      <div>${formatNum(r.roi_pct)}</div>
      <div>${formatNum(r.margin)}</div>
      <div>${formatNum(r.buy_med)}</div>
    `;
    row.addEventListener("click", () => selectSet(r));
    el.appendChild(row);
  });
}

function applyFilters() {
  const q = document.getElementById("search").value.toLowerCase().trim();
  const sort = document.getElementById("sort").value;

  filtered = setsIndex.filter(r => r.set_url.toLowerCase().includes(q));

  const key = sort === "roi" ? "roi_pct"
            : sort === "margin" ? "margin"
            : sort === "buy" ? "buy_med"
            : "opportunity_score"; // proxy for liquidity
  filtered.sort((a,b) => (parseFloat(b[key]||0) - parseFloat(a[key]||0)));

  renderTable();
}

function renderPartsTable(setUrl) {
  const root = document.getElementById("partsTable");
  root.innerHTML = "";

  const headNames = ["Part", "Qty", "SELL (latest)", "SELL depth"];
  headNames.forEach(h => {
    const cell = document.createElement("div");
    cell.className = "cell head";
    cell.textContent = h;
    root.appendChild(cell);
  });

  const rows = partsLatest.filter(r => r.set_url === setUrl);
  rows.forEach(r => {
    const cells = [
      r.part_url,
      r.quantity_for_set,
      formatNum(r.sell_med_latest),
      formatNum(r.sell_depth_med_latest, 0)
    ];
    cells.forEach(txt => {
      const cell = document.createElement("div");
      cell.className = "cell";
      cell.textContent = txt;
      root.appendChild(cell);
    });
  });
}

async function selectSet(r) {
  current = r;
  document.getElementById("itemTitle").textContent = r.set_url;
  document.getElementById("meta").textContent =
    `Dernière MAJ: ${r.latest_date} | BUY(set): ${formatNum(r.buy_med)} | Coût pièces: ${formatNum(r.parts_cost)} | Marge: ${formatNum(r.margin)} | ROI: ${formatNum(r.roi_pct)}%`;

  // Parts snapshot
  renderPartsTable(r.set_url);

  // Load per-set time series (margin & co)
  const setTs = await csvToRows(`${SET_TS_DIR}${r.set_url}__set.csv`);
  const dates = setTs.map(x => x.date);
  const buy = setTs.map(x => +x.buy_med || null);
  const pcost = setTs.map(x => +x.parts_cost || null);
  const margin = setTs.map(x => +x.margin || null);
  const bdepth = setTs.map(x => +x.buy_depth_med || null);
  const bottl = setTs.map(x => +x.min_part_eff_depth || null);

  // Destroy previous charts
  if (priceChart) priceChart.destroy();
  if (depthChart) depthChart.destroy();
  if (marginChart) marginChart.destroy();

  // Prices chart
  priceChart = new Chart(document.getElementById("priceChart").getContext("2d"), {
    type: "line",
    data: { labels: dates, datasets: [
      { label: "BUY (set) – median", data: buy },
      { label: "Parts cost – median", data: pcost }
    ]},
    options: { responsive: true, maintainAspectRatio: false }
  });

  // Depths chart
  depthChart = new Chart(document.getElementById("depthChart").getContext("2d"), {
    type: "line",
    data: { labels: dates, datasets: [
      { label: "BUY depth (set) – median", data: bdepth },
      { label: "Min eff. SELL depth (parts)", data: bottl }
    ]},
    options: { responsive: true, maintainAspectRatio: false }
  });

  // Margin chart
  marginChart = new Chart(document.getElementById("marginChart").getContext("2d"), {
    type: "line",
    data: { labels: dates, datasets: [
      { label: "Margin = BUY(set) − Σ parts SELL", data: margin }
    ]},
    options: { responsive: true, maintainAspectRatio: false }
  });
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
