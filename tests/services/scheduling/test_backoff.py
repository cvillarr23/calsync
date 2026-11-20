from datetime import UTC, datetime, timedelta

from app.db.models import Source
from app.services.scheduling.backoff import next_run_at, run_delay

NOW = datetime(2026, 12, 1, 12, tzinfo=UTC)


def source(interval=60, failures=0, last_run_at=None):
    return Source(interval_min=interval, consecutive_failures=failures, last_run_at=last_run_at)


def test_each_failure_doubles_the_delay():
    delays = [run_delay(source(failures=n), 30) for n in range(4)]
    assert delays == [timedelta(minutes=m) for m in (60, 120, 240, 480)]


def test_backoff_is_capped_at_a_day():
    assert run_delay(source(failures=50), 30) == timedelta(hours=24)


def test_an_interval_longer_than_the_cap_is_kept():
    assert run_delay(source(interval=48 * 60, failures=3), 30) == timedelta(hours=48)


def test_minimum_interval_raises_short_intervals():
    assert run_delay(source(interval=10), 30) == timedelta(minutes=30)


def test_a_source_that_never_ran_is_due_now():
    assert next_run_at(source(), NOW, 30) == NOW


def test_next_run_is_one_delay_after_the_last():
    last = NOW - timedelta(minutes=10)
    assert next_run_at(source(last_run_at=last), NOW, 30) == NOW + timedelta(minutes=50)


def test_an_overdue_source_is_due_now():
    last = NOW - timedelta(days=2)
    assert next_run_at(source(last_run_at=last), NOW, 30) == NOW
