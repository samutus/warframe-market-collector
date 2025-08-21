# transform/build_analytics.py
# Build analytics for craftable PRIME sets assembled from multiple parts.
# Adds detailed logging for diagnosis (use env WFM_LOG_LEVEL=DEBUG for more).
#
# Outputs:
#   docs/data/analytics/sets_index.csv
#   docs/data/analytics/timeseries/<set_url>__set.csv
#   docs/data/analytics/parts_latest_by_set.csv
#
# Cost model:
#   - Parts cost  = sum(quantity_for_set * effective BUY price of each part)
#                   where effective BUY = BUY median if available, else SELL median (same day)
#   - Set value   = SELL median of the set
#   - Margin      = SELL(set) - PartsCost(effective BUY)
# Liquidity:
#   - min_part_eff_depth = min( SELL depth of part // required qty ) across parts
#   - buy_depth_med (set) = BUY depth of the set
# KPI:
#   - daily_volume_cap    = min(buy_depth_med, min_part_eff_depth)
#   - kpi_daily_potential = max(0, margin) * daily_volume_cap

from pathlib import Path
import glob
import os
import time
import logging
import numpy as np
import pandas as pd

ANALYTICS_DIR = Path("docs/data/analytics")
(ANALYTICS_DIR / "timeseries").mkdir(parents=True, exist_ok=True)

# ---------- logging ----------
LOG_LEVEL = os.getenv("WFM_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="[ANALYTICS] %(message)s",
)
log = logging.getLogger("analytics").info
dbg = logging.getLogger("analytics").debug
warn = logging.getLogger("analytics").warning


# ---------------------------- helpers ----------------------------------------
def load_all_csv(pattern: str) -> pd.DataFrame:
    """Load and concat all non-empty CSVs matching `pattern`."""
    frames = []
    for f in sorted(glob.glob(pattern)):
        try:
            if Path(f).stat().st_size > 0:
                frames.append(pd.read_csv(f))
        except Exception as e:
            warn(f"Skipping unreadable file {f}: {e}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def normalize_str(df: pd.DataFrame, col: str, default: str | None = None, lower: bool = True):
    """Ensure a string column exists and is normalized."""
    if col not in df.columns:
        if default is not None:
            df[col] = default
        else:
            return df
    if default is not None:
        df[col] = df[col].fillna(default)
    df[col] = df[col].astype(str)
    if lower:
        df[col] = df[col].str.lower()
    return df


def to_numeric(df: pd.DataFrame, cols: list[str]):
    """Safely cast columns to numeric (coerce errors to NaN)."""
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")


def daily_medians_orderbook(df_orders: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse raw orderbook snapshots (already aggregated per item in collector) to daily medians:
      - buy_med:  median of top_buy_avg (price)
      - sell_med: median of top_sell_avg (price)
      - buy_depth_med:  median of buy_count
      - sell_depth_med: median of sell_count
    """
    if df_orders.empty:
        return df_orders

    df = df_orders.copy()
    normalize_str(df, "platform", "pc")
    normalize_str(df, "item_url")
    to_numeric(df, ["top_buy_avg", "top_sell_avg", "buy_count", "sell_count"])

    # Parse timestamp -> UTC date
    df["date"] = pd.to_datetime(df["ts"], utc=True, errors="coerce").dt.date

    agg = df.groupby(["item_url", "platform", "date"], as_index=False).agg(
        buy_med=("top_buy_avg", "median"),
        sell_med=("top_sell_avg", "median"),
        buy_depth_med=("buy_count", "median"),
        sell_depth_med=("sell_count", "median"),
    )
    # Ensure Timestamp for asof joins later
    agg["date"] = pd.to_datetime(agg["date"], utc=True)
    return agg


# ------------------------------ main -----------------------------------------
def main():
    t0 = time.perf_counter()

    # Load raw monthly CSVs
    df_orders = load_all_csv("data/*/orderbook_*.csv")
    df_comps = load_all_csv("data/*/set_components_*.csv")
    log(f"Loaded: orderbook rows={len(df_orders):,} | components rows={len(df_comps):,}")

    if df_orders.empty or df_comps.empty:
        (ANALYTICS_DIR / "sets_index.csv").write_text("")
        (ANALYTICS_DIR / "parts_latest_by_set.csv").write_text("")
        log("No input data; wrote empty outputs.")
        return

    # Normalize / basic cleaning
    normalize_str(df_orders, "platform", "pc")
    normalize_str(df_orders, "item_url")
    normalize_str(df_comps, "platform", "pc")
    normalize_str(df_comps, "set_url")
    normalize_str(df_comps, "part_url")
    if "quantity_for_set" not in df_comps.columns:
        df_comps["quantity_for_set"] = 1
    df_comps["quantity_for_set"] = df_comps["quantity_for_set"].fillna(1).astype(int)

    # --- Collapse duplicates: one component row per set/platform/part ---
    before = len(df_comps)
    df_comps = (
        df_comps.dropna(subset=["set_url", "part_url"])
                .groupby(["set_url", "platform", "part_url"], as_index=False)
                .agg(quantity_for_set=("quantity_for_set", "max"))
    )
    after = len(df_comps)
    log(f"Components de-duplicated: {before:,} → {after:,} rows (unique set/part/platform)")

    # Daily medians (prices & depths)
    daily = daily_medians_orderbook(df_orders)
    nn_buy = int(daily["buy_med"].notna().sum())
    nn_sell = int(daily["sell_med"].notna().sum())
    log(f"Daily medians: rows={len(daily):,} | buy_med non-null={nn_buy:,} | sell_med non-null={nn_sell:,}")

    # Effective BUY price per item/day: prefer BUY, fallback to SELL
    daily["eff_buy_price"] = daily["buy_med"]
    fb_mask = daily["eff_buy_price"].isna() | (daily["eff_buy_price"] <= 0)
    fb_cnt = int(fb_mask.sum())
    daily.loc[fb_mask, "eff_buy_price"] = daily["sell_med"]
    share_fb = (fb_cnt / max(1, len(daily)))
    log(f"Effective BUY fallback used on {fb_cnt:,}/{len(daily):,} rows ({share_fb:.1%})")

    # Identify craftable PRIME sets
    parts_per_set = (df_comps
        .groupby(["set_url", "platform"], as_index=False)
        .agg(n_parts=("part_url", "nunique"),
             total_qty=("quantity_for_set", "sum"))
    )
    parts_per_set["is_craftable"] = (parts_per_set["n_parts"] >= 2) | (parts_per_set["total_qty"] >= 2)
    parts_per_set["is_prime"] = parts_per_set["set_url"].str.contains("prime_set", na=False)
    craftable_prime = parts_per_set.query("is_craftable and is_prime")
    log(f"Craftable PRIME sets: {craftable_prime['set_url'].nunique():,} (rows={len(craftable_prime):,})")

    # Build daily series for sets and parts
    parts_daily = daily.rename(columns={"item_url": "part_url"})
    sets_daily = daily.rename(columns={"item_url": "set_url"}).merge(
        craftable_prime[["set_url", "platform", "n_parts"]],
        on=["set_url", "platform"], how="inner"
    )
    log(f"Sets daily: rows={len(sets_daily):,} | unique sets={sets_daily['set_url'].nunique():,}")

    # Join components with per-part daily medians
    comp = df_comps.merge(
        craftable_prime[["set_url", "platform", "n_parts"]],
        on=["set_url", "platform"], how="inner"
    )
    comp_prices = comp.merge(parts_daily, on=["part_url", "platform"], how="left")

    # COST: effective BUY price (BUY if present, else SELL)
    comp_prices["weighted_cost"] = comp_prices["quantity_for_set"] * comp_prices["eff_buy_price"]
    comp_prices["eff_part_depth"] = (
        comp_prices["sell_depth_med"] // comp_prices["quantity_for_set"]
    ).fillna(0)

    # Aggregate parts → set/day (sum costs, min bottleneck)
    set_costs = (comp_prices
        .groupby(["set_url", "platform", "date"], as_index=False)
        .agg(parts_cost_buy=("weighted_cost", "sum"),
             min_part_eff_depth=("eff_part_depth", "min"))
    )

    # Merge with sets BUY/SELL side and compute margin/ROI
    sets_daily = sets_daily.merge(set_costs, on=["set_url", "platform", "date"], how="left")
    sets_daily["margin"] = sets_daily["sell_med"] - sets_daily["parts_cost_buy"]
    sets_daily["roi_pct"] = np.where(
        sets_daily["parts_cost_buy"] > 0,
        100.0 * sets_daily["margin"] / sets_daily["parts_cost_buy"],
        np.nan
    )
    log(f"Merged daily: rows={len(sets_daily):,} | non-null margin={int(sets_daily['margin'].notna().sum()):,}")

    # Opportunity score (legacy)
    vol_score = np.sqrt(
        np.maximum(0, sets_daily["buy_depth_med"].fillna(0)) *
        np.maximum(0, sets_daily["min_part_eff_depth"].fillna(0))
    )
    sets_daily["opportunity_score"] = sets_daily["margin"] * np.log1p(vol_score)

    # KPI
    assembly_cap = np.maximum(0, sets_daily["min_part_eff_depth"].fillna(0))
    buyer_cap = np.maximum(0, sets_daily["buy_depth_med"].fillna(0))
    sets_daily["daily_volume_cap"] = np.minimum(assembly_cap, buyer_cap)
    sets_daily["kpi_daily_potential"] = np.maximum(0, sets_daily["margin"].fillna(0)) * sets_daily["daily_volume_cap"]
    kpi_nonzero = int((sets_daily["kpi_daily_potential"] > 0).sum())
    log(f"KPI non-zero rows: {kpi_nonzero:,}/{len(sets_daily):,}")

    # KPI 30d avg
    kpi_30d = (
        sets_daily.sort_values(["set_url", "date"])
                  .groupby("set_url")["kpi_daily_potential"]
                  .apply(lambda s: s.tail(30).mean())
                  .reset_index(name="kpi_30d_avg")
    )

    # --------------------- exports ---------------------

    # 1) Per-set daily series
    for set_url, g in sets_daily.groupby("set_url"):
        outp = ANALYTICS_DIR / "timeseries" / f"{set_url}__set.csv"
        g.to_csv(outp, index=False)
    log(f"Wrote timeseries for {sets_daily['set_url'].nunique():,} sets")

    # 2) sets_index.csv (latest row per set/platform)
    latest_by_set = (
        sets_daily.sort_values(["set_url", "platform", "date"])
                .groupby(["set_url", "platform"], as_index=False)
                .tail(1)
                .rename(columns={"date": "latest_date"})
    )

    # === AJOUT : échelle de normalisation basée sur l’instantané courant ===
    # On calibre l’échelle à partir des KPI "du jour" (une ligne par set)
    samples = latest_by_set["kpi_daily_potential"].dropna().values
    if len(samples) >= 5:
        p10, p90 = np.quantile(samples, [0.10, 0.90])
        lo = float(p10)
        hi = float(lo + (p90 - lo) / 0.8) if (p90 > lo) else float(lo + max(1.0, p90) + 1.0)
    else:
        lo, hi = 0.0, float(max(1.0, np.nanmax(samples) if len(samples) else 1.0))

    def _norm(vec: pd.Series, lo: float, hi: float) -> pd.Series:
        z = (vec - lo) / max(1e-9, (hi - lo))
        return z.clip(lower=0.0, upper=1.0)

    # Vol min (bouchon) + KPI normalisé pour TOUTES les dates (timeseries)
    sets_daily["vol_min"] = np.minimum(
        np.maximum(0, sets_daily["buy_depth_med"].fillna(0)),
        np.maximum(0, sets_daily["min_part_eff_depth"].fillna(0))
    )
    sets_daily["kpi_norm"] = _norm(sets_daily["kpi_daily_potential"], lo, hi)
    sets_daily["kpi_0_100"] = (sets_daily["kpi_norm"] * 100).round().astype("Int64")

    # === AJOUT : vol_min + KPI normalisé dans l’instantané latest_by_set ===
    latest_by_set["vol_min"] = np.minimum(
        np.maximum(0, latest_by_set["buy_depth_med"].fillna(0)),
        np.maximum(0, latest_by_set["min_part_eff_depth"].fillna(0))
    )
    latest_by_set["kpi_norm"] = _norm(latest_by_set["kpi_daily_potential"], lo, hi)
    latest_by_set["kpi_0_100"] = (latest_by_set["kpi_norm"] * 100).round().astype("Int64")

    # --- APRES : sets_index enrichi avec vol_min + KPI normalisé ---
    sets_index = latest_by_set[[
        "set_url", "platform", "latest_date",
        "sell_med", "parts_cost_buy", "margin", "roi_pct",
        "buy_depth_med", "min_part_eff_depth", "vol_min",
        "kpi_daily_potential", "kpi_norm", "kpi_0_100", "opportunity_score"
    ]].rename(columns={
        "sell_med": "set_sell_med",
        "kpi_daily_potential": "kpi_daily",
    })

    # KPI 30 jours moyen (inchangé) + export
    sets_index = sets_index.merge(kpi_30d, on="set_url", how="left")
    sets_index.to_csv(ANALYTICS_DIR / "sets_index.csv", index=False)

    log(f"Wrote sets_index: rows={len(sets_index):,}")

    # 3) parts_latest_by_set.csv aligned on latest set date (unit effective BUY per part)
    if latest_by_set.empty:
        (ANALYTICS_DIR / "parts_latest_by_set.csv").write_text("")
        warn("No latest_by_set rows; wrote empty parts_latest_by_set.csv")
        return

    # RIGHT side for asof: parts daily (must be sorted by 'date' first)
    parts_daily_sorted = parts_daily.copy()
    parts_daily_sorted["date"] = pd.to_datetime(parts_daily_sorted["date"], utc=True, errors="coerce")
    parts_daily_sorted = parts_daily_sorted.dropna(subset=["part_url", "platform", "date"])
    parts_daily_sorted = parts_daily_sorted.sort_values(["date", "part_url", "platform"]).reset_index(drop=True)

    # Attach latest set date to each component
    latest_dates = latest_by_set[["set_url", "platform", "latest_date"]]
    comp_with_date = df_comps.merge(latest_dates, on=["set_url", "platform"], how="left")

    # Clean left side keys BEFORE asof
    comp_with_date = comp_with_date.dropna(subset=["part_url", "platform", "latest_date"]).copy()
    comp_with_date["latest_date"] = pd.to_datetime(comp_with_date["latest_date"], utc=True, errors="coerce")
    comp_with_date = comp_with_date.dropna(subset=["latest_date"])

    # LEFT side — sort with 'date' first as required by merge_asof
    left = (
        comp_with_date.rename(columns={"latest_date": "date"})
                      .sort_values(["date", "part_url", "platform"])
                      .reset_index(drop=True)
    )

    if left.empty or parts_daily_sorted.empty:
        (ANALYTICS_DIR / "parts_latest_by_set.csv").write_text("")
        warn("Empty left or right side for asof; wrote empty parts_latest_by_set.csv")
        return

    parts_latest = pd.merge_asof(
        left, parts_daily_sorted,
        on="date", by=["part_url", "platform"],
        direction="backward", allow_exact_matches=True
    )

    parts_latest = parts_latest.rename(columns={
        "date": "latest_date_part",
        "buy_med": "buy_med_latest",
        "sell_med": "sell_med_latest",
        "eff_buy_price": "unit_cost_latest",
        "sell_depth_med": "sell_depth_med_latest",
    })[[
        "set_url", "platform", "part_url", "quantity_for_set",
        "unit_cost_latest", "buy_med_latest", "sell_med_latest",
        "sell_depth_med_latest", "latest_date_part"
    ]]
    
    # Robust unit cost + explicit source for the UI
    parts_latest["unit_cost_latest"] = parts_latest["unit_cost_latest"].where(
        parts_latest["unit_cost_latest"].notna() & (parts_latest["unit_cost_latest"] > 0),
        parts_latest["sell_med_latest"]
    )
    parts_latest["unit_cost_source"] = np.where(
        parts_latest["buy_med_latest"].notna() & (parts_latest["buy_med_latest"] > 0),
        "BUY", "SELL"
    )


    parts_latest.to_csv(ANALYTICS_DIR / "parts_latest_by_set.csv", index=False)
    miss_uc = int(parts_latest["unit_cost_latest"].isna().sum())
    log(f"Wrote parts_latest_by_set: rows={len(parts_latest):,} | unit_cost missing={miss_uc:,} ({miss_uc/max(1,len(parts_latest)):.1%})")

    # ---------- sanity check snapshot vs index ----------
    snap_cost = (
        parts_latest.assign(prod=lambda d: d["unit_cost_latest"] * d["quantity_for_set"])
                    .groupby(["set_url", "platform"], as_index=False)["prod"].sum()
                    .rename(columns={"prod": "snapshot_parts_cost"})
    )
    cmp = sets_index.merge(snap_cost, on=["set_url", "platform"], how="left")
    cmp["abs_diff"] = (cmp["parts_cost_buy"] - cmp["snapshot_parts_cost"]).abs()
    cmp["rel_diff"] = cmp["abs_diff"] / cmp["parts_cost_buy"].replace(0, np.nan)

    mean_abs = float(cmp["abs_diff"].fillna(0).mean())
    max_abs = float(cmp["abs_diff"].fillna(0).max())
    mean_rel = float(cmp["rel_diff"].fillna(0).mean())
    log(f"Sanity — parts_cost (index) vs snapshot sum: mean_abs={mean_abs:.2f}, max_abs={max_abs:.2f}, mean_rel={mean_rel:.2%}")

    bad = cmp[(cmp["rel_diff"] > 0.05) & cmp["abs_diff"].notna()].nlargest(5, "rel_diff")
    if not bad.empty:
        warn("Top 5 sets with >5% cost discrepancy:")
        warn(bad[["set_url","parts_cost_buy","snapshot_parts_cost","abs_diff","rel_diff"]].to_string(index=False))

    # ---------- done ----------
    log(f"Completed in {time.perf_counter() - t0:.2f}s (log level={LOG_LEVEL})")
    log("sets_index / timeseries / parts_latest built (effective BUY parts, SELL set, KPI).")


if __name__ == "__main__":
    main()