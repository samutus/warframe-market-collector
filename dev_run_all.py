"""
Quick local test runner for Warframe Market Collector
- Limits to N items for fast execution (dev mode).
- Uses the packaged imports (collector as a package).
"""
import os
import datetime as dt
from pathlib import Path
import pandas as pd

# Dev-friendly settings
os.environ["WFM_REQS_PER_SEC"] = "3.0"
os.environ["WFM_TOP_DEPTH"] = "3"
os.environ["COLLECT_STATS48H"] = "false"  # keep it fast

from collector import wfm_common as wfm
from collector.snapshots_6h_all import snapshot_orders, fetch_set_components, is_set_url
from transform.build_analytics import main as build_analytics

def run_dev_collect(limit_items: int = 50):
    month_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    month_dir = Path("data") / month_str
    month_dir.mkdir(parents=True, exist_ok=True)

    ORDERBOOK_FILE = month_dir / f"orderbook_{month_str}.csv"
    ORDERBOOK_OLD  = month_dir / f"orderbook_{month_str}_old.csv"
    SETCOMP_FILE   = month_dir / f"set_components_{month_str}.csv"
    SETCOMP_OLD    = month_dir / f"set_components_{month_str}_old.csv"

    items = wfm.list_all_items()
    urls = [it["url_name"] for it in items if "url_name" in it][:limit_items]
    print(f"[DEV] Collecting {len(urls)} items for quick test...")

    ob_rows = []
    comp_rows = []
    for i, u in enumerate(urls, 1):
        ob_rows.append(snapshot_orders(u))
        if is_set_url(u):
            comp_rows.extend(fetch_set_components(u))
        if i % 10 == 0:
            print(f"[DEV] Progress {i}/{len(urls)}")

    prev_ob = wfm.rotate_monthly_csv(ORDERBOOK_FILE, ORDERBOOK_OLD)
    df_ob = pd.DataFrame(ob_rows)
    wfm.append_and_write(ORDERBOOK_FILE, prev_ob, df_ob, subset_keys=["item_url","ts","platform"])
    print(f"[DEV] orderbook → {ORDERBOOK_FILE}")

    prev_comp = wfm.rotate_monthly_csv(SETCOMP_FILE, SETCOMP_OLD)
    df_comp = pd.DataFrame(comp_rows)
    wfm.append_and_write(SETCOMP_FILE, prev_comp, df_comp, subset_keys=["set_url","part_url"])
    print(f"[DEV] set_components → {SETCOMP_FILE}")

if __name__ == "__main__":
    run_dev_collect(limit_items=None)
    print("[DEV] Running analytics build...")
    build_analytics()
    print("[DEV] Done. Check docs/data/analytics for outputs.")
