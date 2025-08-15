# Run the production collector (Prime filtering) + analytics locally.
import os

os.environ.update({
    "WFM_PLATFORM": "pc",
    "WFM_LANGUAGE": "en",
    "WFM_REQS_PER_SEC": "3.0",
    "WFM_TOP_DEPTH": "3",
    "WFM_ONLY_PRIME": "true",
    "WFM_STRICT_SETS_PARTS": "true",
    "COLLECT_STATS48H": "false",
    "WFM_MAX_ITEMS": "0",  # set "0" to disable dev limit
})

from collector.snapshots_6h_all import main as collect_main
from transform.build_analytics import main as build_analytics

if __name__ == "__main__":
    collect_main()
    build_analytics()
    print("[DEV] Done. Open docs/ with a static server to view the UI.")