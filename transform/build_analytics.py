# Build analytics only for craftable Prime sets (assembled from multiple parts).
# Outputs:
#   docs/data/analytics/sets_index.csv            ← left list (latest row per set)
#   docs/data/analytics/timeseries/<set>__set.csv ← daily series per set (incl. KPI)
#   docs/data/analytics/parts_latest_by_set.csv   ← latest parts snapshot

import glob
from pathlib import Path
import pandas as pd
import numpy as np

ANALYTICS_DIR = Path("docs/data/analytics")
(ANALYTICS_DIR / "timeseries").mkdir(parents=True, exist_ok=True)

def load_all_csv(pattern: str) -> pd.DataFrame:
    files = sorted(glob.glob(pattern))
    frames = []
    for f in files:
        try:
            if Path(f).stat().st_size > 0:
                frames.append(pd.read_csv(f))
        except Exception:
            pass
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

def normalize_str(df: pd.DataFrame, col: str, default: str | None = None, lower: bool = True):
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

def daily_medians_orderbook(df_orders: pd.DataFrame) -> pd.DataFrame:
    if df_orders.empty:
        return df_orders
    df = df_orders.copy()
    normalize_str(df, "platform", "pc")
    normalize_str(df, "item_url")
    df["date"] = pd.to_datetime(df["ts"], utc=True, errors="coerce").dt.date
    agg = df.groupby(["item_url","platform","date"], as_index=False).agg(
        buy_med=("top_buy_avg","median"),
        sell_med=("top_sell_avg","median"),
        buy_depth_med=("buy_count","median"),
        sell_depth_med=("sell_count","median"),
    )
    return agg

def main():
    df_orders = load_all_csv("data/*/orderbook_*.csv")
    df_comps  = load_all_csv("data/*/set_components_*.csv")

    if df_orders.empty or df_comps.empty:
        (ANALYTICS_DIR / "sets_index.csv").write_text("")
        return

    # Normalize
    normalize_str(df_orders, "platform", "pc")
    normalize_str(df_orders, "item_url")
    normalize_str(df_comps, "platform", "pc")
    normalize_str(df_comps, "set_url")
    normalize_str(df_comps, "part_url")
    if "quantity_for_set" not in df_comps.columns:
        df_comps["quantity_for_set"] = 1
    df_comps["quantity_for_set"] = df_comps["quantity_for_set"].fillna(1).astype(int)

    # Daily medians for all items
    daily = daily_medians_orderbook(df_orders)

    # Identify craftable PRIME sets (>=2 parts or total qty>=2 and url contains 'prime_set')
    parts_per_set = (df_comps
        .groupby(["set_url","platform"], as_index=False)
        .agg(n_parts=("part_url","nunique"),
             total_qty=("quantity_for_set","sum"))
    )
    parts_per_set["is_craftable"] = (parts_per_set["n_parts"] >= 2) | (parts_per_set["total_qty"] >= 2)
    parts_per_set["is_prime"] = parts_per_set["set_url"].str.contains("prime_set", na=False)
    craftable_prime = parts_per_set.query("is_craftable and is_prime")

    # BUY side for sets
    sets_daily = daily.rename(columns={"item_url":"set_url"}).merge(
        craftable_prime[["set_url","platform","n_parts"]],
        on=["set_url","platform"], how="inner"
    )

    # SELL side for parts (per-part daily medians)
    parts_daily = daily.rename(columns={"item_url":"part_url"})

    # Join components with part prices/depths
    comp = df_comps.merge(craftable_prime[["set_url","platform","n_parts"]],
                          on=["set_url","platform"], how="inner")
    comp_prices = comp.merge(parts_daily, on=["part_url","platform"], how="left")
    comp_prices["weighted_cost"] = comp_prices["quantity_for_set"] * comp_prices["sell_med"]
    # Effective depth per part: sell_depth // qty
    comp_prices["eff_part_depth"] = (comp_prices["sell_depth_med"] // comp_prices["quantity_for_set"]).fillna(0)

    # Aggregate parts → set/day
    set_costs = (comp_prices
        .groupby(["set_url","platform","date"], as_index=False)
        .agg(parts_cost=("weighted_cost","sum"),
             min_part_eff_depth=("eff_part_depth","min"))
    )

    # Merge with sets BUY side and compute margin/ROI
    sets_daily = sets_daily.merge(set_costs, on=["set_url","platform","date"], how="left")
    sets_daily["margin"] = sets_daily["buy_med"] - sets_daily["parts_cost"]
    sets_daily["roi_pct"] = np.where(sets_daily["parts_cost"] > 0,
                                     100.0 * sets_daily["margin"] / sets_daily["parts_cost"],
                                     np.nan)

    # Opportunity score (legacy volume-flavored ranking)
    vol_score = np.sqrt(
        np.maximum(0, sets_daily["buy_depth_med"].fillna(0)) *
        np.maximum(0, sets_daily["min_part_eff_depth"].fillna(0))
    )
    sets_daily["opportunity_score"] = sets_daily["margin"] * np.log1p(vol_score)

    # KPI: daily potential = margin × min(buy_depth_med, min_part_eff_depth)
    assembly_cap = np.maximum(0, sets_daily["min_part_eff_depth"].fillna(0))
    buyer_cap    = np.maximum(0, sets_daily["buy_depth_med"].fillna(0))
    sets_daily["daily_volume_cap"]    = np.minimum(assembly_cap, buyer_cap)
    sets_daily["kpi_daily_potential"] = np.maximum(0, sets_daily["margin"].fillna(0)) * sets_daily["daily_volume_cap"]

    # KPI 30d average (last 30 samples)
    kpi_30d = (sets_daily
        .sort_values(["set_url","date"])
        .groupby("set_url")["kpi_daily_potential"]
        .apply(lambda s: s.tail(30).mean())
        .reset_index(name="kpi_30d_avg")
    )

    # Export per-set daily series (includes KPI columns)
    for set_url, g in sets_daily.groupby("set_url"):
        g.to_csv(ANALYTICS_DIR / "timeseries" / f"{set_url}__set.csv", index=False)

    # Latest row per set for the left table
    latest_by_set = (sets_daily
        .sort_values(["set_url","date"])
        .groupby("set_url", as_index=False)
        .tail(1)
    )
    sets_index = latest_by_set[[
        "set_url","platform","date","buy_med","parts_cost","margin","roi_pct",
        "buy_depth_med","min_part_eff_depth","kpi_daily_potential","opportunity_score"
    ]].rename(columns={
        "date":"latest_date",
        "kpi_daily_potential":"kpi_daily"
    })

    # Attach 30d KPI avg
    sets_index = sets_index.merge(kpi_30d, on="set_url", how="left")
    sets_index.to_csv(ANALYTICS_DIR / "sets_index.csv", index=False)

    # Latest parts snapshot for the UI (dedup)
    latest_part = (parts_daily
        .sort_values(["part_url","date"])
        .groupby(["part_url"], as_index=False)
        .tail(1)[["part_url","platform","date","sell_med","sell_depth_med"]]
        .rename(columns={"date":"latest_date_part",
                         "sell_med":"sell_med_latest",
                         "sell_depth_med":"sell_depth_med_latest"})
    )
    parts_latest = comp.merge(latest_part, on=["part_url","platform"], how="left")
    parts_latest = parts_latest.drop_duplicates(subset=["set_url","part_url","platform"])
    parts_latest = parts_latest[[
        "set_url","platform","part_url","quantity_for_set",
        "sell_med_latest","sell_depth_med_latest","latest_date_part"
    ]]
    parts_latest.to_csv(ANALYTICS_DIR / "parts_latest_by_set.csv", index=False)

    print("[ANALYTICS] sets_index/timeseries/parts_latest built (incl. KPI).")

if __name__ == "__main__":
    main()
