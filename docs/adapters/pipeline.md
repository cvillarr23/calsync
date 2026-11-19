# Pipeline adapters

A `pipeline` definition is an ordered list of `steps`. It suits sites whose calendar is backed by a JSON API, including APIs that need a value scraped from a page first.

```yaml
kind: pipeline
steps:
  - http: {url: "{{page_url}}"}               # fetch something
  - extract: {jsonpath: "$.data"}             # pull a value out of it
  - paginate: {step_days: 7, as: date}        # repeat what follows for each week
  - http: {url: "{{page_url}}?from={{date:%Y-%m-%d}}"}
  - items: {jsonpath: "$.events[*]"}          # the event records
map:
  title: {jsonpath: "$.name"}
  start: {jsonpath: "$.start"}
```

[Concepts](concepts.md) covers the parts every kind shares: params, the field `map`, templates and safety limits.

## How a run works

Steps run top to bottom and share two things:

- **Variables.** These start as the source's params. An `extract` or `paginate` step with `as` adds one. Templates such as `{{page_url}}` read variables.
- **The document.** This is the value the next step works on. Each `http` step replaces it with the response body. An `extract` without `as` replaces it with what it extracted.

The `items` step turns the document into a list of records. `map` turns each record into an event. Events are then deduped by [uid](#uids-and-duplicates) and sorted by start time.

### Step order

Each step is a mapping with exactly one key: `http`, `extract`, `paginate` or `items`. When you save, calsync checks these rules and reports any break at the step's path, such as `steps.0`:

- There is exactly one `items` step, and it is the **last** step.
- There is at most one `paginate` step, and at least one `http` step comes **after** it, because the steps after it are the ones it repeats.
- A template may only use params and variables saved by **earlier** steps.

## Steps

### `http`

Fetches a URL. The response body becomes the document.

| Field | Default | Meaning |
|---|---|---|
| `url` | required | A template. |
| `method` | `GET` | `GET` or `POST`. |
| `headers` | none | A map of header name to template. |
| `json` | none | A JSON request body. Every string in it is a template. A string that is only a template, such as `"{{config}}"`, embeds the variable's value as JSON, so an object stays an object. |
| `form` | none | A form-encoded body, as a map of field to template. Use `json` or `form`, not both. |
| `follow_redirects` | `true` | Set it to `false` to keep a redirect response, body included, instead of following it. Some sites put the data you need in the body of a 302. |

The run keeps one cookie jar, so a cookie set by an earlier step goes out with later requests. A response with status 400 or higher fails the step. Every request counts towards the run's [safety limits](concepts.md#safety-limits).

### `extract`

Pulls one value out of the document. Set exactly one of these:

| Field | Extracts |
|---|---|
| `regex` | The first capture group of the first match in the document's text. The regex must have a capture group. |
| `jsonpath` | The first match of a JSONPath. A text document, such as a response body, is decoded as JSON first. |
| `css` | Not supported in pipelines yet. Use the [html kind](html.md) for CSS selectors. |

Optional fields:

- `parse: json` decodes the extracted string as JSON. Use it when a page embeds a JS object, or when an API returns JSON wrapped in a string, such as `{"d": "{\"Bookings\": [...]}"}`.
- `as: name` saves the value as a variable. Without `as`, the value replaces the document.

The step fails if nothing matches.

### `paginate`

Repeats the steps after it once per date across the window being synced. The window starts at the time of the sync and runs for the source's lookahead (60 days by default). Pages start at midnight UTC on the window's first date and run through its last date. Pages often reach past the window, so after the run, events that end before the window or start after it are dropped.

| Field | Meaning |
|---|---|
| `window` | `lookahead`, the only option today. |
| `step_days` | Days between dates, from 1 to 366. |
| `as` | The variable that holds each date. |

The variable holds midnight on each date as a date-time value, not a string. Format it in a template with `{{date:%Y-%m-%d}}` or `{{date:%Y-%m-%d %H:%M:%S}}`. A bare `{{date}}` writes ISO 8601, for example `2026-12-01T00:00:00`.

Each date runs on its own copy of the variables and document. Its items are added to the run's list. Pages that overlap return some events more than once, and the dedupe step removes the extras.

### `items`

Turns the document into the list of event records, using every match of `jsonpath`. A text document is decoded as JSON first. `$.Bookings[*]` yields each element of `Bookings`. Matching nothing is not an error; that page simply has no events. `css` is not supported in pipelines yet.

## Mapping records to events

Each `map` field reads the first match of its `jsonpath` in the record. Every adapter kind maps fields the same way after that: `regex`, `strip`, dates and times, time zones, time ranges, default durations and `skip_if` work as [Concepts](concepts.md#the-field-map) describes. In pipelines:

- A JSONPath reads JSON values, so `skip_if: {jsonpath: "$.Status", equals: -12}` compares numbers. A field that reads a list or an object uses its JSON value. Point the path at the scalar you want, such as `$.Times[0]`.
- `selector` and `from_context` fields aren't supported in pipelines yet. Items that use them are reported as unreadable.

### Uids and duplicates

Every event gets a `uid`, a hash of some of its mapped fields. By default it hashes `title`, `start` and `location`. If a site has a better key, list the fields to hash in the top-level `uid`:

```yaml
uid: [title, start]
```

calsync uses the uid to recognise an event again on later runs, so choose fields that don't change when unrelated details do. Within one run, events with the same uid are deduped, and the first one is kept.

## Errors

A failing step names its index (counting from 0) and its kind:

```text
step 1 (extract): regex 'app\.config = (\{.*?\});' matched nothing
step 3 (http): POST https://calendar.example.org/api/events returned HTTP 500
```

A step error stops the run. A field that can't be read only drops its own record. calsync reports the record's position in the item list, counting from 0, plus the field and the reason:

```text
item 4: start: can't read a date or time from 'TBA'
```

If no record could be read at all, the sync fails with the first reason, so a broken definition can't empty the calendar. The command line below prints each dropped record on stderr.

## Trying a definition from the command line

You can run a definition file without the web UI. The command prints the events it would sync:

```bash
uv run python -m app.adapters.pipeline my-site.yaml page_url=https://calendar.example.org/rink \
    --days 21
```

| Option | Meaning |
|---|---|
| `key=value` | Params. Params with a default can be left out. |
| `--days N` | The lookahead window. Defaults to 60. |
| `--start YYYY-MM-DD` | The first day of the window. Defaults to today. |
| `--json` | Print JSON instead of a table. |
| `--allow-private` | Allow private and loopback addresses, for a calendar on your own network. Without it, the [SSRF guard](concepts.md#safety-limits) applies. |

## Worked example: a two-step API

Some booking systems split the calendar across two requests:

1. **`GET /calendar`** returns an HTML page with a configuration object embedded in a script tag. The server also sets a session cookie and answers with a redirect to an error page. The body of that redirect is the page you want:

    ```html
    <script>app.config = {"roomId": 7, "token": "abc=="};</script>
    ```

2. **`POST /api/events`** takes that object back unchanged, plus a date. It needs the session cookie:

    ```json
    {"date": "2026-12-01 00:00:00", "config": {"roomId": 7, "token": "abc=="}}
    ```

    It returns 14 days of bookings starting at `date`, as JSON wrapped in a string. Times are in UTC with no offset, names have stray spaces, and cancelled bookings have `Status: -12`:

    ```json
    {"d": "{\"Bookings\": [{\"Name\": \"Public Skate   \", \"StartUtc\": \"2026-12-02T18:00:00\", \"EndUtc\": \"2026-12-02T19:30:00\", \"Room\": \"Main Rink\", \"Status\": 1}]}"}
    ```

This definition reads it:

```yaml
id: two-step-demo
version: 1
name: Two-step demo API
kind: pipeline
params:
  page_url: {type: url, description: The public calendar page}
steps:
  - http: {url: "{{page_url}}", follow_redirects: false}                        # 0
  - extract: {regex: 'app\.config = (\{.*?\});', as: config, parse: json}       # 1
  - paginate: {window: lookahead, step_days: 7, as: date}                       # 2
  - http:                                                                       # 3
      method: POST
      url: "{{origin(page_url)}}/api/events"
      json: {date: "{{date:%Y-%m-%d %H:%M:%S}}", config: "{{config}}"}
  - extract: {jsonpath: "$.d", parse: json}                                     # 4
  - items: {jsonpath: "$.Bookings[*]"}                                          # 5
map:
  title: {jsonpath: "$.Name", strip: true}
  start: {jsonpath: "$.StartUtc", tz: UTC}
  end: {jsonpath: "$.EndUtc", tz: UTC}
  location: {jsonpath: "$.Room"}
  skip_if: {jsonpath: "$.Status", equals: -12}
```

Step by step:

0. Fetches the page **without following the redirect**. Following it would land on the error page, which has no config. The response's session cookie goes into the run's cookie jar.
1. Takes the object literal from the script tag, decodes it with `parse: json`, and saves it as `config`.
2. Runs steps 3–5 for each week of the window: on the start date, 7 days later, and so on.
3. POSTs the date, formatted as the API expects, together with `config`. Because `"{{config}}"` is the whole string, the object is sent as an object. The cookie from step 0 goes with the request.
4. Reads `$.d`, which is a string, and decodes that string as JSON. The decoded value becomes the document.
5. Yields each booking.

Then `map` strips the names, reads the times as UTC, and drops cancelled bookings. Each POST returns 14 days but the pages are 7 days apart, so most bookings arrive twice. The uid dedupe keeps one of each. A 21-day run from 1 December gives:

```text
start (UTC)       end (UTC)         title           location
2026-12-02 18:00  2026-12-02 19:30  Public Skate    Main Rink
2026-12-09 12:00  2026-12-09 13:00  Stick & Puck    Main Rink
2026-12-16 07:00  2026-12-16 08:00  Figure Skating  Studio Rink
3 event(s)
```

calsync's own test suite runs this exact definition against a fake server built this way, in `tests/adapters/pipeline/fake_api.py`.
