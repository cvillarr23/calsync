from dataclasses import asdict

from app.schemas.sync_run import SyncRunOut
from app.services.sync import SyncResult


def sync_run_out(result: SyncResult) -> SyncRunOut:
    return SyncRunOut(**asdict(result))
