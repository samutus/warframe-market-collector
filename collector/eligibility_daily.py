# Calculates weekly eligible items and refreshes stats & set components once per day.
import json, datetime as dt
from pathlib import Path
import os
from typing import Any, Dict, List, Tuple
import pandas as pd
from wfm_common import (
    get_json, list_all_items, parse_dt,
    rotate_monthly_csv, append_and_write, MONTH_DIR, DATA_DIR
)

WEEKLY_MIN_VOLUME = int(os.getenv("WFM_WEEKLY_MIN_VOLUME", "3"))
ELIGIBLE_PATH = DATA_DIR / "eligibility" / "eligible.json"
ELIGIBLE_PATH.parent.mkdir(parents=True, exist_ok=True)

ORDERBOOK_FILE = MONTH_DIR / f"orderbook_{dt.datetime.now(dt.timezone.utc):%Y-%m}.csv"
ORDERBOOK_OLD  = MONTH_DIR / f"orderbook_{dt.datetime.now(dt.timezone.utc):%Y-%m}_old.csv"
STATS_FILE     = MONTH_DIR / f"stats48h_{dt.datetime.now(dt.timezone.utc):%Y-%m}.csv"
STATS_OLD      = MONTH_DIR / f"stats48h_{dt.datetime.now(dt.timezone.utc):%Y-%m}_old.csv"
SETCOMP_FILE   = MONTH_DIR / f"set_components_{dt.datetime.now(dt.timezone.utc):%Y-%m}.csv"
SETCOMP_OLD    = MONTH_DIR / f"set_components_{dt.datetime.now(dt.timezone.utc):%Y-%m}_old.csv"

def weekly_volume(item_url: str, days: int = 7) -> int:
    stats = get_json(f"/items/{item_url}/statistics")["payload"]["statistics_closed"]
    rows = stats.get("90days") or []
    rows = sorted(rows, key=lambda b: parse_dt(b["datetime"]), reverse=True)[:days]
    return sum(int(b.get("volume", 0)) for b in rows)

def fetch_set_components(item_url: str) -> List[Dict[str, Any]]:
    nodes = get_json(f"/items/{item_url}")["payload"]["item"]["items_in_set"]
    parts = []
    for n in nodes:
        if not n.get("set_root"):
            parts.append({
                "set_url": item_url,
                "part_url": n.get("url_name"),
                "quantity_for_set": int(n.get("quantity_for_set", 1))
            })
    return parts

def snapshot_stats48h(item_url: str) -> List[Dict[str, Any]]:
    out = []
    stats = get_json(f"/items/{item_url}/statistics")["payload"]["statistics_closed"]
    for b in stats.get("48hours", []) or []:
        out.append({
            "item_url": item_url,
            "ts_bucket": b.get("datetime"),
            "volume": b.get("volume"),
            "min": b.get("min_price"),
            "max": b.get("max_price"),
            "avg": b.get("avg_price"),
            "median": b.get("median"),
            "platform": "pc"
        })
    return out

def main():
    items = list_all_items()
    urls = [it["url_name"] for it in items if "url_name" in it]

    eligible, stats_rows, comp_rows = [], [], []

    print(f"[DAILY] Checking weekly volumes for {len(urls)} items…")
    for i, u in enumerate(urls, 1):
        try:
            if weekly_volume(u) > WEEKLY_MIN_VOLUME:
                eligible.append(u)
                # Refresh components and 48h stats once per day (light enough)
                comp_rows.extend(fetch_set_components(u))
                stats_rows.extend(snapshot_stats48h(u))
        except Exception as e:
            print(f"[WARN] {u} weekly/stats/components failed: {e}")

        if i % 200 == 0:
            print(f"[DAILY] Progress {i}/{len(urls)} | eligible={len(eligible)}")

    # Save eligibility list (JSON)
    ELIGIBLE_PATH.write_text(json.dumps({"updated_at": dt.datetime.now(dt.timezone.utc).isoformat()+"Z",
                                         "count": len(eligible), "items": eligible}, indent=2))
    print(f"[DAILY] Eligible items: {len(eligible)} → {ELIGIBLE_PATH}")

    # Write/update stats48h monthly
    prev_stats = rotate_monthly_csv(STATS_FILE, STATS_OLD)
    df_stats = pd.DataFrame(stats_rows)
    append_and_write(STATS_FILE, prev_stats, df_stats, subset_keys=["item_url", "ts_bucket", "platform"])

    # Write/update set components monthly (static-ish, but refreshed daily in case of changes)
    prev_comp = rotate_monthly_csv(SETCOMP_FILE, SETCOMP_OLD)
    df_comp = pd.DataFrame(comp_rows)
    append_and_write(SETCOMP_FILE, prev_comp, df_comp, subset_keys=["set_url", "part_url"])

    print("[DAILY] Done.")

if __name__ == "__main__":
    import os
    main()