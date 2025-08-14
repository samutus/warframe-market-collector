# Build analytics tables for dashboarding:
# - Daily medians per item (price & depth)
# - For sets: daily parts→set margin, ROI%, liquidity score
# - Produces:
#   docs/data/analytics/index.csv        (latest snapshot per item)
#   docs/data/analytics/timeseries/*.csv (daily series per item)

import os, glob, datetime as dt
from pathlib import Path
from typing import Dict, List
import pandas as pd

ANALYTICS_DIR = Path("docs/data/analytics")
ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)

def load_all_csv(pattern: str) -> pd.DataFrame:
    files = sorted(glob.glob(pattern))
    if not files: return pd.DataFrame()
    return pd.concat([pd.read_csv(f) for f in files if os.path.getsize(f) > 0], ignore_index=True)

def daily_medians_orderbook(df_orders: pd.DataFrame) -> pd.DataFrame:
    if df_orders.empty: return df_orders
    df = df_orders.copy()
    df["date"] = pd.to_datetime(df["ts"]).dt.date
    agg = df.groupby(["item_url", "platform", "date"]).agg(
        buy_med=("top_buy_avg", "median"),
        sell_med=("top_sell_avg", "median"),
        buy_depth_med=("buy_count", "median"),
        sell_depth_med=("sell_count", "median")
    ).reset_index()
    return agg

def build_set_costs(daily_prices: pd.DataFrame, df_components: pd.DataFrame) -> pd.DataFrame:
    """
    Compute daily parts cost per set: sum(qty * sell_med(part)).
    """
    if daily_prices.empty or df_components.empty:
        return pd.DataFrame(columns=["set_url","platform","date","parts_cost","min_part_eff_depth"])

    # Prepare part daily prices
    p = daily_prices.rename(columns={"item_url":"part_url"})
    # Effective part depth: we approximate availability by raw sell depth
    # (you can refine to sell_depth_med // qty later).
    comp = df_components.copy()
    merged = comp.merge(p, on="part_url", how="left")
    merged["weighted_cost"] = merged["quantity_for_set"] * merged["sell_med"]
    # For depth bottleneck, divide depth by qty (integer floor)
    merged["eff_part_depth"] = (merged["sell_depth_med"] // merged["quantity_for_set"]).fillna(0)

    # Sum by set/date
    agg = merged.groupby(["set_url","platform","date"]).agg(
        parts_cost=("weighted_cost","sum"),
        min_part_eff_depth=("eff_part_depth","min"),
        n_parts=("part_url","nunique")
    ).reset_index()
    return agg

def main():
    # Load raw monthly CSVs (current + past months)
    df_orders = load_all_csv("data/*/orderbook_*.csv")
    df_stats  = load_all_csv("data/*/stats48h_*.csv")
    df_comps  = load_all_csv("data/*/set_components_*.csv")

    # Daily medians (prices & depths)
    daily = daily_medians_orderbook(df_orders)

    # Sets: parts cost (with quantities) and liquidity bottleneck
    set_costs = build_set_costs(daily, df_comps)

    # Join set BUY side to compute margin & ROI
    sets_daily = daily.rename(columns={"item_url":"set_url"})
    sets_daily = sets_daily.merge(set_costs, on=["set_url","platform","date"], how="left")
    sets_daily["margin"] = sets_daily["buy_med"] - sets_daily["parts_cost"]
    sets_daily["roi_pct"] = 100.0 * (sets_daily["margin"] / sets_daily["parts_cost"])
    # Liquidity notion (similar to before)
    sets_daily["volume_score"] = (sets_daily["buy_depth_med"] * sets_daily["min_part_eff_depth"]).pow(0.5)
    sets_daily["opportunity_score"] = sets_daily["margin"] * (sets_daily["volume_score"] + 1.0).apply(lambda x: pd.np.log(x))  # log1p approx

    # Export per-item timeseries (all items)
    # 1) index: latest state per item (either generic item or set metrics if available)
    latest_dates = daily.groupby("item_url")["date"].max().reset_index().rename(columns={"date":"latest_date"})
    last = daily.merge(latest_dates, on=["item_url","date"])
    last = last[["item_url","platform","date","buy_med","sell_med","buy_depth_med","sell_depth_med"]]
    # For sets, attach latest margin if available
    last_sets = sets_daily.sort_values(["set_url","date"]).dropna(subset=["margin"]).groupby("set_url").tail(1)
    last = last.merge(last_sets[["set_url","margin","roi_pct","opportunity_score"]], left_on="item_url", right_on="set_url", how="left").drop(columns=["set_url"])
    last = last.rename(columns={"date":"latest_date"})
    last.to_csv(ANALYTICS_DIR / "index.csv", index=False)

    # 2) split daily into per-item files (keeps page load small via lazy loading)
    for item, g in daily.groupby("item_url"):
        path = ANALYTICS_DIR / "timeseries" / f"{item}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        g.to_csv(path, index=False)

    # 3) sets timeseries with margins (optional, used by UI when item is a set)
    for item, g in sets_daily.groupby("set_url"):
        path = ANALYTICS_DIR / "timeseries" / f"{item}__set.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        g.to_csv(path, index=False)

    print("[ANALYTICS] Built index + timeseries.")

if __name__ == "__main__":
    main()
