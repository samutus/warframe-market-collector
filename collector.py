#!/usr/bin/env python3
"""
Warframe Market long-term collector (PC) for GitHub Actions.

What it does (every 6h):
1) List ALL items from /v1/items.
2) For each item, fetch /v1/items/{url}/statistics and compute weekly volume = sum of last 7 days.
3) Keep ONLY items with weekly_volume > WEEKLY_MIN_VOLUME (default: 3).
4) For eligible items, snapshot:
   - ORDERBOOK: top-3 BUY/SELL averages + counts from /orders.
   - STATS 48H: official 48h buckets (volume, min/max/avg/median).
   - SET COMPONENTS: (url, part_url, quantity_for_set) for items that are sets.
5) Append to this month's CSVs with rotation:
   - data/YYYY-MM/orderbook_YYYY-MM.csv (+ _old.csv)
   - data/YYYY-MM/stats48h_YYYY-MM.csv (+ _old.csv)
   - data/YYYY-MM/set_components_YYYY-MM.csv (+ _old.csv)
"""

import os
import math
import time
import json
import shutil
import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import requests
import pandas as pd
from dateutil import parser as dtparser

# ----------------------
# Config (tweak via env)
# ----------------------
PLATFORM = os.getenv("WFM_PLATFORM", "pc")
LANGUAGE = os.getenv("WFM_LANGUAGE", "en")
USER_AGENT = os.getenv("WFM_UA", "wfm-longterm-collector/1.0")
REQS_PER_SEC = float(os.getenv("WFM_REQS_PER_SEC", "3.0"))  # be kind to Cloudflare
TOP_DEPTH = int(os.getenv("WFM_TOP_DEPTH", "3"))            # top-of-book depth to average
WEEKLY_MIN_VOLUME = int(os.getenv("WFM_WEEKLY_MIN_VOLUME", "3"))
MAX_ITEMS = os.getenv("WFM_MAX_ITEMS")  # optional cap for safety; e.g. "1500" or None
MAX_ITEMS = int(MAX_ITEMS) if MAX_ITEMS and MAX_ITEMS.isdigit() else None

BASE = "https://api.warframe.market/v1"
SLEEP = 1.0 / REQS_PER_SEC + 0.02

HEADERS = {
    "accept": "application/json",
    "platform": PLATFORM,
    "language": LANGUAGE,
    "User-Agent": USER_AGENT
}

DATA_DIR = Path("data")
UTC_NOW = dt.datetime.utcnow()
MONTH_STR = UTC_NOW.strftime("%Y-%m")
MONTH_DIR = DATA_DIR / MONTH_STR
MONTH_DIR.mkdir(parents=True, exist_ok=True)

# Filenames (monthly)
ORDERBOOK_FILE = MONTH_DIR / f"orderbook_{MONTH_STR}.csv"
ORDERBOOK_OLD  = MONTH_DIR / f"orderbook_{MONTH_STR}_old.csv"

STATS_FILE     = MONTH_DIR / f"stats48h_{MONTH_STR}.csv"
STATS_OLD      = MONTH_DIR / f"stats48h_{MONTH_STR}_old.csv"

SETCOMP_FILE   = MONTH_DIR / f"set_components_{MONTH_STR}.csv"
SETCOMP_OLD    = MONTH_DIR / f"set_components_{MONTH_STR}_old.csv"

ONLINE_STATES = {"ingame", "online"}  # we only consider active users' orders


# ----------------------
# HTTP helpers
# ----------------------
def get_json(path: str) -> Dict[str, Any]:
    url = f"{BASE}{path}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    time.sleep(SLEEP)
    return r.json()


# ----------------------
# Items and eligibility
# ----------------------
def list_all_items() -> List[str]:
    """Return url_name for all items in the game."""
    payload = get_json("/items")["payload"]["items"]
    if isinstance(payload, dict):
        # Some snapshots show language-keyed dict; normalize to a list.
        for v in payload.values():
            if isinstance(v, list):
                payload = v
                break
    urls = [it["url_name"] for it in payload if "url_name" in it]
    if MAX_ITEMS:
        urls = urls[:MAX_ITEMS]
    return urls


def weekly_volume_over_threshold(item_url: str, days: int = 7, threshold: int = WEEKLY_MIN_VOLUME) -> Tuple[bool, int]:
    """
    Compute weekly volume from '90days' statistics (sum of last <days> buckets).
    Returns (eligible, weekly_volume).
    """
    stats = get_json(f"/items/{item_url}/statistics")["payload"]["statistics_closed"]
    buckets = stats.get("90days") or []
    if not buckets:
        return (False, 0)

    # Buckets are daily. Sort by datetime desc and sum last <days> volumes.
    def parse_ts(s: str) -> dt.datetime:
        try:
            return dtparser.parse(s)
        except Exception:
            return UTC_NOW  # fallback

    buckets_sorted = sorted(buckets, key=lambda b: parse_ts(b["datetime"]), reverse=True)
    last_week = buckets_sorted[:days]
    weekly_vol = sum(int(b.get("volume", 0)) for b in last_week)
    return (weekly_vol > threshold, weekly_vol)


# ----------------------
# Snapshots
# ----------------------
def snapshot_orders(item_url: str) -> Dict[str, Any]:
    """
    Take a lightweight orderbook snapshot: top-3 avg BUY/SELL + counts.
    """
    ts = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    try:
        orders = get_json(f"/items/{item_url}/orders")["payload"]["orders"]
    except Exception as e:
        return {"item_url": item_url, "ts": ts, "error": f"orders_fetch_failed: {e}"}

    def filt(typ: str) -> List[Dict[str, Any]]:
        return [
            o for o in orders
            if o.get("order_type") == typ and o.get("visible", True) and o.get("user", {}).get("status") in ONLINE_STATES
        ]

    buys = sorted(filt("buy"), key=lambda x: x["platinum"], reverse=True)
    sells = sorted(filt("sell"), key=lambda x: x["platinum"])

    def avg_top(lst: List[Dict[str, Any]], k: int) -> float:
        if not lst:
            return float("nan")
        k = min(k, len(lst))
        return sum(o["platinum"] for o in lst[:k]) / k

    return {
        "item_url": item_url,
        "ts": ts,
        "top_buy_avg": round(avg_top(buys, TOP_DEPTH), 3),
        "buy_count": len(buys),
        "top_sell_avg": round(avg_top(sells, TOP_DEPTH), 3),
        "sell_count": len(sells),
        "platform": PLATFORM
    }


def snapshot_stats48h(item_url: str) -> List[Dict[str, Any]]:
    """
    Return official '48hours' buckets as rows.
    """
    out: List[Dict[str, Any]] = []
    try:
        stats = get_json(f"/items/{item_url}/statistics")["payload"]["statistics_closed"]
    except Exception as e:
        return [{"item_url": item_url, "ts_bucket": None, "error": f"stats_fetch_failed: {e}", "platform": PLATFORM}]
    for b in stats.get("48hours", []) or []:
        out.append({
            "item_url": item_url,
            "ts_bucket": b.get("datetime"),
            "volume": b.get("volume"),
            "min": b.get("min_price"),
            "max": b.get("max_price"),
            "avg": b.get("avg_price"),
            "median": b.get("median"),
            "platform": PLATFORM
        })
    return out


def fetch_set_components(item_url: str) -> List[Dict[str, Any]]:
    """
    If item_url is a set, return its components and quantities.
    """
    try:
        nodes = get_json(f"/items/{item_url}")["payload"]["item"]["items_in_set"]
    except Exception:
        return []
    root = None
    parts = []
    for n in nodes:
        if n.get("set_root"):
            root = n
        else:
            parts.append(n)
    if not root:
        return []
    # If it is not a set, 'parts' will be empty; still return empty.
    rows = []
    for p in parts:
        rows.append({
            "set_url": item_url,
            "part_url": p.get("url_name"),
            "quantity_for_set": int(p.get("quantity_for_set", 1))
        })
    return rows


# ----------------------
# CSV rotation & append
# ----------------------
def rotate_monthly_csv(current_path: Path, old_path: Path) -> Optional[pd.DataFrame]:
    """
    Prepare for writing a new monthly CSV:
    - If old_path exists, delete it (keep only one generation of backup).
    - If current_path exists: rename it to old_path and return its DataFrame (old content).
    - Else: ensure parent dir exists and return None.
    """
    old_path.unlink(missing_ok=True)
    if current_path.exists():
        # Read old data before renaming (so we can append & dedup)
        try:
            prev_df = pd.read_csv(current_path)
        except Exception:
            prev_df = None
        current_path.rename(old_path)
        return prev_df
    current_path.parent.mkdir(parents=True, exist_ok=True)
    return None


def append_and_write(current_path: Path, old_df: Optional[pd.DataFrame], new_rows: pd.DataFrame, subset_keys: List[str]):
    """
    Concatenate old_df (if any) with new_rows, drop duplicates on subset_keys, and write to current_path.
    """
    if old_df is not None:
        combined = pd.concat([old_df, new_rows], ignore_index=True)
    else:
        combined = new_rows
    combined = combined.drop_duplicates(subset=subset_keys)
    combined.to_csv(current_path, index=False)


# ----------------------
# Main
# ----------------------
def main():
    print(f"[INFO] Start {UTC_NOW.isoformat()}Z | platform={PLATFORM} lang={LANGUAGE}")
    all_items = list_all_items()
    print(f"[INFO] Items in catalog: {len(all_items)} (MAX_ITEMS cap: {MAX_ITEMS})")

    # Eligibility by weekly volume
    eligible: List[str] = []
    weekly_map: Dict[str, int] = {}
    for i, url in enumerate(all_items, start=1):
        try:
            ok, wv = weekly_volume_over_threshold(url)
            if ok:
                eligible.append(url)
                weekly_map[url] = wv
        except requests.HTTPError as e:
            print(f"[WARN] weekly_volume error {url}: {e}")
        except Exception as e:
            print(f"[WARN] weekly_volume fail {url}: {e}")
        if i % 100 == 0:
            print(f"[INFO] Checked {i}/{len(all_items)} items… eligible so far: {len(eligible)}")

    print(f"[INFO] Eligible items (weekly_volume > {WEEKLY_MIN_VOLUME}): {len(eligible)}")

    # ORDERBOOK snapshots
    order_rows: List[Dict[str, Any]] = []
    for j, url in enumerate(eligible, start=1):
        row = snapshot_orders(url)
        row["weekly_volume_est"] = weekly_map.get(url, None)
        order_rows.append(row)
        if j % 100 == 0:
            print(f"[INFO] Orderbook snap {j}/{len(eligible)}")

    df_orders = pd.DataFrame(order_rows)
    # STATS 48H snapshots
    stats_rows: List[Dict[str, Any]] = []
    for j, url in enumerate(eligible, start=1):
        stats_rows.extend(snapshot_stats48h(url))
        if j % 100 == 0:
            print(f"[INFO] Stats48h snap {j}/{len(eligible)}")
    df_stats = pd.DataFrame(stats_rows)

    # SET COMPONENTS (for sets among eligible)
    comp_rows: List[Dict[str, Any]] = []
    for j, url in enumerate(eligible, start=1):
        comp_rows.extend(fetch_set_components(url))
    df_comps = pd.DataFrame(comp_rows)

    # ----- Rotation + append -----
    # Orderbook
    prev_orders = rotate_monthly_csv(ORDERBOOK_FILE, ORDERBOOK_OLD)
    append_and_write(ORDERBOOK_FILE, prev_orders, df_orders,
                     subset_keys=["item_url", "ts", "platform"])

    # Stats48h
    prev_stats = rotate_monthly_csv(STATS_FILE, STATS_OLD)
    append_and_write(STATS_FILE, prev_stats, df_stats,
                     subset_keys=["item_url", "ts_bucket", "platform"])

    # Set components (structure is static-ish; keep latest snapshot per month)
    prev_comps = rotate_monthly_csv(SETCOMP_FILE, SETCOMP_OLD)
    append_and_write(SETCOMP_FILE, prev_comps, df_comps,
                     subset_keys=["set_url", "part_url"])

    print(f"[INFO] Wrote:")
    print(f" - {ORDERBOOK_FILE}")
    print(f" - {STATS_FILE}")
    print(f" - {SETCOMP_FILE}")
    print("[INFO] Done.")


if __name__ == "__main__":
    main()
