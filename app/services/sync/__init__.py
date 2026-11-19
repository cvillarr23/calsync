"""One sync run for one source: scrape, store, filter, push to targets, record status.

The run stores every event the adapter returns, matched or not, so changing a
source's filters takes effect without re-scraping. Filtering happens on the
way out: in `matched_events` for the feed and for each sync target.
"""

from app.services.sync.hashing import content_hash
from app.services.sync.matching import matched_events
from app.services.sync.result import SyncResult
from app.services.sync.run import run_source
from app.services.sync.target import SyncTarget

__all__ = ["SyncResult", "SyncTarget", "content_hash", "matched_events", "run_source"]
