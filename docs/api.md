# JSON API

The web UI uses a plain JSON API under `/api`. Scripts and other clients can use the same API to manage sources and adapter definitions.

## Authentication

The API uses the same session as the web UI. Sign in in a browser first; requests without a valid session get `401`.

Every `POST`, `PUT`, `PATCH` and `DELETE` must also send the session's CSRF token in an `X-CSRF-Token` header, or it gets `403`. The token is in each page's `<meta name="csrf-token">`. This stops other sites from using your signed-in browser to change your sources.

Adapter definitions and sources belong to the account that created them. You only see and use your own, plus the built-in definitions.

## Errors

Validation errors return `422` with a list of field paths and messages:

```json
{"detail": [{"loc": "fetch.url", "msg": "unknown variable(s): nope"}]}
```

Other errors return `404` (not found) or `409` (conflict), with a message in `detail`.

## Adapter definitions

| Method and path | Description |
|---|---|
| `GET /api/adapters` | Lists the built-in definitions and yours: `id`, `name`, `kind`, `version` and `builtin`. |
| `GET /api/adapters/{id}` | One definition, with its parsed `definition` and its `yaml` text. |
| `POST /api/adapters` | Creates a definition. Returns `201`. |
| `PUT /api/adapters/{id}` | Replaces a definition. The `id` in the body must match the one in the path. |
| `DELETE /api/adapters/{id}` | Deletes a definition. Returns `204`, or `409` while a source uses it. |

Send a definition either as a JSON object or as YAML with `Content-Type: application/yaml`. calsync keeps YAML exactly as you sent it, comments included. It is validated against the [adapter schema](adapters/concepts.md). User definitions can't use the `python` kind, and built-in definitions are read-only.

## Sources

| Method and path | Description |
|---|---|
| `GET /api/sources` | Lists your sources. |
| `POST /api/sources` | Creates a source. Returns `201`. |
| `GET /api/sources/{id}` | One source. |
| `PATCH /api/sources/{id}` | Changes the fields you send. |
| `DELETE /api/sources/{id}` | Deletes the source and its stored events. Returns `204`. |
| `POST /api/sources/{id}/sync` | Sync now: runs the source straight away and returns what the run did. Returns `409` while the source is already syncing. |

A source has these fields:

| Field | Default | Description |
|---|---|---|
| `name` | *(required)* | Shown in the UI, and used as the feed's calendar name. |
| `adapter_id` | *(required)* | The adapter definition that reads the site. |
| `params` | `{}` | Values for the adapter's `params`. Each param without a default is required, and the value must match the param's type. |
| `include_kw` | `[]` | Keep events whose title contains any of these. An empty list keeps everything. |
| `exclude_kw` | `[]` | Drop events whose title contains any of these. Excludes win over includes. |
| `interval_min` | `360` | Minutes between syncs. Must be at least `CALSYNC_MIN_INTERVAL_MIN`. |
| `lookahead_days` | `60` | How far ahead to fetch, from 1 to 366 days. |
| `target_calendar_id` | `null` | The Google Calendar to sync to, an `id` from `GET /api/calendars`. `null` means the source is served as an `.ics` feed only. Changing or clearing it removes the source's future events from the old calendar on the next sync; see [Google Calendar sync](google-calendar.md). |
| `enabled` | `true` | Whether the source syncs on its schedule. A disabled source can still be synced with Sync now. |

Keyword matching ignores case and treats any run of whitespace as one space. Responses also include these read-only fields:

| Field | Description |
|---|---|
| `id` | The source's id. |
| `feed_url` | The source's `.ics` feed. See [Calendar feeds](feeds.md). |
| `last_run_at`, `last_status`, `last_error` | When the last sync ran, whether it was `ok` or an `error`, and the error message. |
| `consecutive_failures` | How many syncs in a row have failed. A success resets it to `0`. |
| `next_run_at` | When the next scheduled sync is due. `null` for a disabled source. |

### Scheduling

calsync syncs each enabled source on its own, in the background:

- A new source syncs right away. After that, each sync is due `interval_min` minutes after the previous one, whether that one was scheduled or a Sync now.
- After a failed sync, the wait doubles with each failure in a row: twice the interval, then four times, and so on, up to 24 hours. An interval longer than 24 hours is never shortened. The next success resets the wait to the interval.
- The schedule is worked out from `last_run_at` and `consecutive_failures`, so it carries over a restart. A sync that fell due while calsync was down runs at startup.
- A source never syncs twice at once. A scheduled sync that finds the source busy is skipped, and Sync now returns `409`.

Example, with the session cookie and CSRF token copied from a signed-in browser:

```sh
curl -X POST https://calsync.example/api/sources \
  -b 'calsync_session=your-session-cookie' \
  -H 'X-CSRF-Token: your-csrf-token' \
  -H 'Content-Type: application/json' \
  -d '{"name": "Public skate", "adapter_id": "my-rink",
       "params": {"page_url": "https://rink.example/schedule"},
       "include_kw": ["public skate"], "exclude_kw": ["theme night"]}'
```

Sync it now:

```sh
curl -X POST https://calsync.example/api/sources/1/sync
```

```json
{"status": "ok", "error": null, "fetched": 42, "inserted": 3, "updated": 1,
 "unchanged": 38, "removed": 0, "matched": 12}
```

The counts are zero when the run failed before storing anything; `error` then says why.

## Calendars

| Route | What it does |
|---|---|
| `GET /api/calendars` | The Google Calendars you can add events to, as `[{"id", "summary", "primary"}]`, primary first. Returns `409` when Google needs reconnecting, and `502` when Google can't be reached. |
