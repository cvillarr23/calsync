# Contributing

## Checks

Run these before pushing. CI runs the same ones.

```sh
uv run ruff check
uv run ruff format --check
uv run pytest
uv run mkdocs build --strict
```

Every PR updates the `docs/` pages for the behaviour it changes.

## Project layout

Code is split by layer, one concern per module. Add a new file in the right layer instead of growing an existing one.

```
app/
  main.py              app factory and lifespan (opens the database)
  settings.py          environment configuration
  serve.py             container entry point
  adapters/            adapter definitions: schema, templates, fetch layer, registry,
                       the runner contract (events.py) and the engines for each kind
    mapping/           the field `map`, shared by every kind: item → ScrapedEvent
                       (item.py) and date/time handling (times.py)
    html/              the html kind: pages.py (which URLs, static or headless),
                       headless.py (Chromium behind the fetch guard), extract.py
                       (selectolax items and fields), run.py (run_html, HtmlEngine)
  db/
    base.py            declarative Base and shared column types
    engine.py          opening the SQLite file, creating the schema
    migrations.py      SCHEMA_VERSION and the ordered migration steps
    session.py         the per-request session dependency (`Db`)
    models/            one ORM model per file (source.py, event.py, ...)
  schemas/             API request and response bodies (Pydantic), one file per resource
  services/            application logic with no HTTP in it
    sync/              one sync run, one step per module (scrape, event_store, status, ...)
  mappers/             ORM rows and definitions → API schemas, and back
  api/
    deps.py            shared route dependencies (current user, registry, settings)
    errors.py          HTTP error helpers in the API's error shape
    <resource>.py      one router per resource (adapters, sources, feeds, schema)
tests/                 mirrors app/: tests/db, tests/services, tests/api, tests/adapters
  support.py           fakes shared across test packages
```

How the layers depend on each other:

- `api` calls `services` and `mappers`, and raises HTTP errors. Business rules don't go in route modules.
- `services` work on `db.models` and `adapters`. They never import from `api` or `fastapi`, so the scheduler and other clients can reuse them.
- `mappers` only convert between shapes. They make no decisions and no queries.
- `db.models` holds no logic beyond column defaults.

Engines need the instance's fetch limits, so `create_app` registers them in `ENGINES` once settings are loaded.

When you add a table, put its model in `app/db/models/<name>.py`, export it from `app/db/models/__init__.py`, and add a migration step if existing databases need one.
