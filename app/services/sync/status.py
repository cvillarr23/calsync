import logging
from datetime import datetime

from app.adapters.events import AdapterRunError
from app.adapters.fetch import FetchError
from app.db.models import Source
from app.services.sync.result import SyncResult

log = logging.getLogger(__name__)

_EXPECTED_ERRORS = (AdapterRunError, FetchError)
"""Failures the user can act on; anything else is also logged with a traceback."""


def record_success(source: Source, now: datetime) -> None:
    source.last_run_at = now
    source.last_status = "ok"
    source.last_error = None
    source.consecutive_failures = 0


def record_failure(source: Source, err: Exception, now: datetime) -> SyncResult:
    _log_failure(source, err)
    source.last_run_at = now
    source.last_status = "error"
    source.last_error = str(err) or type(err).__name__
    source.consecutive_failures += 1
    return SyncResult(status="error", error=source.last_error)


def _log_failure(source: Source, err: Exception) -> None:
    if isinstance(err, _EXPECTED_ERRORS):
        log.warning("sync of source %s failed: %s", source.id, err)
    else:
        log.exception("sync of source %s failed unexpectedly", source.id)
