from sqlalchemy import inspect, select, text

from app.db.engine import init_db, make_engine
from app.db.migrations import SCHEMA_VERSION
from app.db.models import SchemaVersion


def test_version_1_database_gains_the_google_map_columns(tmp_path):
    engine = make_engine(tmp_path / "data")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO schema_version VALUES (1)"))
        conn.execute(
            text(
                "CREATE TABLE google_map (source_id INTEGER, uid VARCHAR, "
                "google_event_id VARCHAR, content_hash VARCHAR, PRIMARY KEY (source_id, uid))"
            )
        )

    sessions = init_db(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("google_map")}
    assert {"calendar_id", "start_utc"} <= columns
    with sessions() as db:
        assert db.scalars(select(SchemaVersion.version)).all() == [SCHEMA_VERSION]
    engine.dispose()
