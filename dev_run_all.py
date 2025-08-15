# dev_run_all.py
# Run the production collector (with Prime filtering) + analytics locally.
import os

# Dev-friendly env (toggle as you like)
os.environ.update({
    "WFM_PLATFORM": "pc",
    "WFM_LANGUAGE": "en",
    "WFM_REQS_PER_SEC": "3.0",
    "WFM_TOP_DEPTH": "3",

    # Ensure Prime-only + sets&parts strict filtering
    "WFM_ONLY_PRIME": "true",
    "WFM_STRICT_SETS_PARTS": "true",

    # Optional: limit target universe for quick tests
    "WFM_MAX_ITEMS": "50",        # put "0" to disable the dev limit
    "COLLECT_STATS48H": "false",  # keep fast; switch to true if needed
})

from collector.snapshots_6h_all import main as collect_main
from transform.build_analytics import main as build_analytics

if __name__ == "__main__":
    collect_main()       # uses the same filtering as production
    build_analytics()
    print("[DEV] Done. Open docs/ with a static server to view the UI.")
