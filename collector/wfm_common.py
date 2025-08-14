# All code/comments in English as requested.

import os, time, datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests
import pandas as pd
from dateutil import parser as dtparser

BASE = "https://api.warframe.market/v1"
PLATFORM = os.getenv("WFM_PLATFORM", "pc")
LANGUAGE = os.getenv("WFM_LANGUAGE", "en")
USER_AGENT = os.getenv("WFM_UA", "wfm-collector/1.1")
REQS_PER_SEC = float(os.getenv("WFM_REQS_PER_SEC", "3.0"))
SLEEP = 1.0 / REQS_PER_SEC + 0.02
ONLINE_STATES = {"ingame", "online"}

HEADERS = {
    "accept": "application/json",
    "platform": PLATFORM,
    "language": LANGUAGE,
    "User-Agent": USER_AGENT
}

UTC_NOW = dt.datetime.utcnow()
MONTH_STR = UTC_NOW.strftime("%Y-%m")
DATA_DIR = Path("data")
MONTH_DIR = DATA_DIR / MONTH_STR
MONTH_DIR.mkdir(parents=True, exist_ok=True)

def get_json(path: str) -> Dict[str, Any]:
    """Simple GET with throttling."""
    url = f"{BASE}{path}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    time.sleep(SLEEP)
    return r.json()

def list_all_items() -> List[Dict[str, Any]]:
    """Return the raw item entries from /items; normalize to list."""
    payload = get_json("/items")["payload"]["items"]
    if isinstance(payload, dict):
        for v in payload.values():
            if isinstance(v, list):
                payload = v
                break
    return payload

def parse_dt(s: str, fallback: dt.datetime = UTC_NOW) -> dt.datetime:
    try:
        return dtparser.parse(s)
    except Exception:
        return fallback

def rotate_monthly_csv(current_path: Path, old_path: Path) -> Optional[pd.DataFrame]:
    """Delete previous *_old.csv, rename current to *_old.csv, return previous content."""
    old_path.unlink(missing_ok=True)
    if current_path.exists():
        try:
            prev_df = pd.read_csv(current_path)
        except Exception:
            prev_df = None
        current_path.rename(old_path)
        return prev_df
    current_path.parent.mkdir(parents=True, exist_ok=True)
    return None

def append_and_write(current_path: Path, old_df: Optional[pd.DataFrame], new_df: pd.DataFrame, subset_keys: List[str]):
    """Append + drop duplicates on subset_keys."""
    df = pd.concat([old_df, new_df], ignore_index=True) if old_df is not None else new_df
    if not df.empty:
        df = df.drop_duplicates(subset=subset_keys)
    df.to_csv(current_path, index=False)