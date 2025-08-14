# 6-hour collector for ALL items (no daily eligibility stage)
import os, datetime as dt
from typing import Any, Dict, List
import pandas as pd
from pathlib import Path
from .wfm_common import (
    get_json, list_all_items, rotate_monthly_csv, append_and_write,
    ONLINE_STATES, MONTH_DIR, PLATFORM
)

TOP_DEPTH = int(os.getenv("WFM_TOP_DEPTH", "3"))
COLLECT_STATS48H = os.getenv("COLLECT_STATS48H", "false").lower() in {"1","true","yes"}

# Monthly files
MONTH = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
ORDERBOOK_FILE = MONTH_DIR / f"orderbook_{MONTH}.csv"
ORDERBOOK_OLD  = MONTH_DIR / f"orderbook_{MONTH}_old.csv"
STATS_FILE     = MONTH_DIR / f"stats48h_{MONTH}.csv"
STATS_OLD      = MONTH_DIR / f"stats48h_{MONTH}_old.csv"
SETCOMP_FILE   = MONTH_DIR / f"set_components_{MONTH}.csv"
SETCOMP_OLD    = MONTH_DIR / f"set_components_{MONTH}_old.csv"

def is_set_url(url: str) -> bool:
    return url.endswith("_set")

def snapshot_orders(item_url: str) -> Dict[str, Any]:
    ts = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    out = {"item_url": item_url, "ts": ts, "platform": "pc"}
    try:
        orders = get_json(f"/items/{item_url}/orders")["payload"]["orders"]
    except Exception as e:
        out["error"] = f"orders_fetch_failed: {e}"
        return out

    def filt(typ: str):
        return [
            o for o in orders
            if o.get("order_type")==typ and o.get("visible", True)
            and o.get("user", {}).get("status") in ONLINE_STATES
        ]

    buy = sorted(filt("buy"), key=lambda x: x["platinum"], reverse=True)
    sell= sorted(filt("sell"), key=lambda x: x["platinum"])

    def avg_top(lst, k):
        if not lst: return float("nan")
        k = min(k, len(lst))
        return sum(o["platinum"] for o in lst[:k]) / k

    out.update({
        "top_buy_avg": round(avg_top(buy, TOP_DEPTH), 3),
        "buy_count": len(buy),
        "top_sell_avg": round(avg_top(sell, TOP_DEPTH), 3),
        "sell_count": len(sell),
    })
    return out

def snapshot_stats48h(item_url: str) -> List[Dict[str, Any]]:
    if not COLLECT_STATS48H:
        return []
    rows: List[Dict[str, Any]] = []
    try:
        stats = get_json(f"/items/{item_url}/statistics")["payload"]["statistics_closed"]
    except Exception:
        return rows
    for b in stats.get("48hours", []) or []:
        rows.append({
            "item_url": item_url,
            "ts_bucket": b.get("datetime"),
            "volume": b.get("volume"),
            "min": b.get("min_price"),
            "max": b.get("max_price"),
            "avg": b.get("avg_price"),
            "median": b.get("median"),
            "platform": "pc"
        })
    return rows

def fetch_set_components(item_url: str) -> List[Dict[str, Any]]:
    """Only call for set URLs to minimize API calls."""
    if not is_set_url(item_url):
        return []
    rows: List[Dict[str, Any]] = []
    try:
        nodes = get_json(f"/items/{item_url}")["payload"]["item"]["items_in_set"]
    except Exception:
        return rows
    for n in nodes:
        if not n.get("set_root"):
            rows.append({
                "set_url": item_url,
                "part_url": n.get("url_name"),
                "quantity_for_set": int(n.get("quantity_for_set", 1)),
                "platform": PLATFORM,
            })
    return rows

def main():
    items = list_all_items()
    urls = [it["url_name"] for it in items if "url_name" in it]
    print(f"[6H] Collecting ALL items: {len(urls)}")

    ob_rows: List[Dict[str, Any]] = []
    stats_rows: List[Dict[str, Any]] = []
    comp_rows: List[Dict[str, Any]] = []

    for i, u in enumerate(urls, 1):
        ob_rows.append(snapshot_orders(u))
        if COLLECT_STATS48H:
            stats_rows.extend(snapshot_stats48h(u))
        if is_set_url(u):
            comp_rows.extend(fetch_set_components(u))
        if i % 200 == 0:
            print(f"[6H] Progress {i}/{len(urls)}")

    # Write orderbook (rotate + dedup)
    prev_ob = rotate_monthly_csv(ORDERBOOK_FILE, ORDERBOOK_OLD)
    df_ob = pd.DataFrame(ob_rows)
    append_and_write(ORDERBOOK_FILE, prev_ob, df_ob, subset_keys=["item_url","ts","platform"])
    print(f"[6H] orderbook → {ORDERBOOK_FILE}")

    # Write stats48h if collected
    if COLLECT_STATS48H:
        prev_stats = rotate_monthly_csv(STATS_FILE, STATS_OLD)
        df_stats = pd.DataFrame(stats_rows)
        append_and_write(STATS_FILE, prev_stats, df_stats, subset_keys=["item_url","ts_bucket","platform"])
        print(f"[6H] stats48h → {STATS_FILE}")

    # Write set components (rotate monthly; dedup by set/part)
    prev_comp = rotate_monthly_csv(SETCOMP_FILE, SETCOMP_OLD)
    df_comp = pd.DataFrame(comp_rows)
    append_and_write(SETCOMP_FILE, prev_comp, df_comp, subset_keys=["set_url","part_url","platform"])
    print(f"[6H] set_components → {SETCOMP_FILE}")

if __name__ == "__main__":
    main()
