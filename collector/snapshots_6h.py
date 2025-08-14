# Snapshots the orderbook for eligible items (every 6h), monthly CSV with rotation.
import json, datetime as dt
from pathlib import Path
from typing import Any, Dict, List
import pandas as pd
from wfm_common import get_json, rotate_monthly_csv, append_and_write, ONLINE_STATES, MONTH_DIR, DATA_DIR

ORDERBOOK_FILE = MONTH_DIR / f"orderbook_{dt.datetime.utcnow():%Y-%m}.csv"
ORDERBOOK_OLD  = MONTH_DIR / f"orderbook_{dt.datetime.utcnow():%Y-%m}_old.csv"
ELIGIBLE_PATH  = DATA_DIR / "eligibility" / "eligible.json"
TOP_DEPTH      = int(os.getenv("WFM_TOP_DEPTH", "3"))

def snapshot_orders(item_url: str) -> Dict[str, Any]:
    ts = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    try:
        orders = get_json(f"/items/{item_url}/orders")["payload"]["orders"]
    except Exception as e:
        return {"item_url": item_url, "ts": ts, "error": f"orders_fetch_failed: {e}", "platform": "pc"}

    def filt(typ: str):
        return [o for o in orders if o.get("order_type")==typ and o.get("visible",True)
                and o.get("user",{}).get("status") in ONLINE_STATES]

    buy = sorted(filt("buy"), key=lambda x: x["platinum"], reverse=True)
    sell= sorted(filt("sell"), key=lambda x: x["platinum"])

    def avg_top(lst, k):
        if not lst: return float("nan")
        k = min(k, len(lst))
        return sum(o["platinum"] for o in lst[:k]) / k

    return {
        "item_url": item_url, "ts": ts, "platform": "pc",
        "top_buy_avg": round(avg_top(buy, TOP_DEPTH), 3), "buy_count": len(buy),
        "top_sell_avg": round(avg_top(sell, TOP_DEPTH), 3), "sell_count": len(sell)
    }

def main():
    # Load eligibility list (must exist from daily job)
    if not ELIGIBLE_PATH.exists():
        raise SystemExit("eligible.json missing; run the daily workflow first.")
    eligible = json.loads(ELIGIBLE_PATH.read_text())["items"]
    print(f"[6H] Eligible items: {len(eligible)}")

    rows = []
    for i, u in enumerate(eligible, 1):
        rows.append(snapshot_orders(u))
        if i % 200 == 0:
            print(f"[6H] Snapshots {i}/{len(eligible)}")

    df = pd.DataFrame(rows)
    prev = rotate_monthly_csv(ORDERBOOK_FILE, ORDERBOOK_OLD)
    append_and_write(ORDERBOOK_FILE, prev, df, subset_keys=["item_url", "ts", "platform"])
    print(f"[6H] Orderbook appended → {ORDERBOOK_FILE}")

if __name__ == "__main__":
    import os
    main()