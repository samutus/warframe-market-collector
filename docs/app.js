// Simple UI: left = list with sorting/filtering; right = details with charts.
// Data files produced by transform/build_analytics.py
const INDEX_URL = "data/analytics/index.csv";
const TS_DIR    = "data/analytics/timeseries/";

let indexRows = [];   // parsed index.csv
let filtered = [];    // current filtered view
let current = null;   // current selected item
let priceChart, depthChart, marginChart;

async function csvToRows(url) {
  const res = await fetch(url);
  const txt = await res.text();
  const [head, ...lines] = txt.trim().split("\n");
  const cols = head.split(",");
  return lines.map(l => {
    const vals = l.split(",");
    const obj = {};
    cols.forEach((c, i) => obj[c] = vals[i]);
    return obj;
  });
}

function renderTable() {
  const el = document.getElementById("itemTable");
  el.innerHTML = "";
  const header = document.createElement("div");
  header.className = "row header";
  header.innerHTML = `<div>Item</div><div>ROI%</div><div>Marge</div><div>BUY</div>`;
  el.appendChild(header);

  filtered.forEach(r => {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = `
      <div>${r.item_url}</div>
      <div>${(parseFloat(r.roi_pct)||0).toFixed(1)}</div>
      <div>${(parseFloat(r.margin)||0).toFixed(1)}</div>
      <div>${(parseFloat(r.buy_med)||0).toFixed(1)}</div>
    `;
    row.addEventListener("click", () => selectItem(r));
    el.appendChild(row);
  });
}

function applyFilters() {
  const q = document.getElementById("search").value.toLowerCase().trim();
  const sort = document.getElementById("sort").value;
  filtered = indexRows.filter(r => r.item_url.toLowerCase().includes(q));

  const key = sort === "roi" ? "roi_pct"
            : sort === "margin" ? "margin"
            : sort === "buy" ? "buy_med"
            : "buy_depth_med";

  filtered.sort((a,b) => (parseFloat(b[key]||0) - parseFloat(a[key]||0)));
  renderTable();
}

async function selectItem(r) {
  current = r;
  document.getElementById("itemTitle").textContent = r.item_url;
  document.getElementById("meta").textContent =
    `Dernière MAJ: ${r.latest_date} | BUY(med): ${(+r.buy_med||0).toFixed(1)} | SELL(med): ${(+r.sell_med||0).toFixed(1)} | Profondeur BUY: ${(+r.buy_depth_med||0).toFixed(0)}`;

  // Load daily series
  const ts = await csvToRows(`${TS_DIR}${r.item_url}.csv`);
  const dates = ts.map(x => x.date);
  const buy = ts.map(x => +x.buy_med || null);
  const sell= ts.map(x => +x.sell_med || null);
  const bdepth = ts.map(x => +x.buy_depth_med || null);
  const sdepth = ts.map(x => +x.sell_depth_med || null);

  // Manage charts (destroy old to avoid leaks)
  if (priceChart) priceChart.destroy();
  if (depthChart) depthChart.destroy();

  const pc = document.getElementById("priceChart").getContext("2d");
  priceChart = new Chart(pc, {
    type: "line",
    data: { labels: dates, datasets: [{label:"BUY (median top-3)", data: buy}, {label:"SELL (median top-3)", data: sell}] },
    options: { responsive: true, maintainAspectRatio: false }
  });

  const dc = document.getElementById("depthChart").getContext("2d");
  depthChart = new Chart(dc, {
    type: "line",
    data: { labels: dates, datasets: [{label:"BUY depth (median)", data: bdepth}, {label:"SELL depth (median)", data: sdepth}] },
    options: { responsive: true, maintainAspectRatio: false }
  });

  // If this item is a set with margin series, show it
  const setPath = `${TS_DIR}${r.item_url}__set.csv`;
  try {
    const setTs = await csvToRows(setPath);
    const sdates = setTs.map(x => x.date);
    const margin = setTs.map(x => +x.margin || null);
    if (marginChart) marginChart.destroy();
    document.getElementById("setBlock").classList.remove("hidden");
    marginChart = new Chart(document.getElementById("marginChart").getContext("2d"), {
      type: "line",
      data: { labels: sdates, datasets: [{label:"Margin (BUY set - sum(parts SELL))", data: margin}] },
      options: { responsive: true, maintainAspectRatio: false }
    });
  } catch {
    document.getElementById("setBlock").classList.add("hidden");
    if (marginChart) marginChart.destroy();
  }
}

async function boot() {
  indexRows = await csvToRows(INDEX_URL);
  applyFilters();
  document.getElementById("search").addEventListener("input", applyFilters);
  document.getElementById("sort").addEventListener("change", applyFilters);
}
boot();
