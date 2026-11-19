# HTML adapters

An `html` adapter reads events straight out of a web page with CSS selectors. Use it when a site shows its schedule as HTML and offers no JSON API. If the page loads its data from a JSON endpoint, a [pipeline](pipeline.md) adapter that calls that endpoint is usually faster and sturdier.

This page covers the `html` kind's own fields. [Concepts](concepts.md) covers params, templates and the field `map` keys every kind shares.

## A first definition

```yaml
id: rec-center
version: 1
name: Rec center schedule
kind: html
params:
  url: {type: url, description: The schedule page}
fetch:
  url: "{{url}}"
item: li.event                     # one element per event
map:
  title: {selector: h3}
  start: {selector: time.start, attr: datetime}
  end: {selector: time.end, attr: datetime}
  location: {selector: .where}
  url: {selector: a, attr: href}   # relative links are resolved against the page
  skip_if: {selector: .status, equals: cancelled}
```

For this page:

```html
<li class="event">
  <h3>Public Skate</h3>
  <time class="start" datetime="2026-11-21T13:00:00-06:00">Sat 1:00 PM</time>
  <time class="end" datetime="2026-11-21T14:30:00-06:00">2:30 PM</time>
  <span class="where">Main Rink</span>
  <a href="/events/101">Details</a>
</li>
```

calsync produces one event, *Public Skate*, from 19:00 to 20:30 UTC at *Main Rink*.

## Fetching

| Key | Default | Meaning |
|---|---|---|
| `url` | | The page to read, as a [template](concepts.md#templates) over the params. Omit it when `pagination.mode` is `url_template`. |
| `mode` | `static` | `static` downloads the HTML. `headless` renders the page in Chromium first. |
| `wait_for` | | Headless only: a CSS selector to wait for before the HTML is read. |
| `user_agent` | `calsync/<version>` | The User-Agent sent with every request. |

Static mode is the default and almost always enough. Open the page with JavaScript turned off, or look at **View source**. If the events are in the source, use `static`.

## Items and fields

`item` is a CSS selector, and every element it matches becomes one event. Each field in `map` then reads from inside that element:

- `selector` finds the first matching element inside the item. Its value is its text, with whitespace collapsed to single spaces.
- `attr` reads an attribute of that element instead of its text, for example `datetime` on a `<time>` or `href` on a link.
- The `url` field is resolved against the page's address, so `href="/events/101"` becomes a full URL.

calsync checks every selector when you save the definition. A selector that isn't valid CSS is reported against its field, for example `map.title.selector: invalid CSS selector '<<>>'`. A valid selector that matches nothing in an item is reported when the definition runs. The item is left out and the rest of the page is still read.

## Grids: `from_context`

Week and month grids often print the date once, in a header, and each event cell carries only a time. `from_context` reads such a value from **outside** the item: it finds the nearest element matching the selector that is either an ancestor of the item or comes before it in the page.

```html
<table class="week">
  <tr class="day"><th>Saturday, October 31</th></tr>
  <tr class="slot"><td class="time">7:00–8:30 PM</td><td class="name">Halloween Skate</td></tr>
  <tr class="day"><th>Sunday, November 1</th></tr>
  <tr class="slot"><td class="time">7:00–8:30 PM</td><td class="name">Sunday Skate</td></tr>
</table>
```

```yaml
item: tr.slot
map:
  title: {selector: .name}
  date: {from_context: tr.day th}
  start:
    selector: .time
    tz: America/Chicago
    time_range_regex: '(.+?)\s*[–-]\s*(.+)'
```

Each slot gets its date from the last `tr.day th` above it. `time_range_regex` splits the cell into a start and an end, and the trailing `PM` applies to both. `tz` says the times are Chicago local time. The result is two events: Saturday's starts at 00:00 UTC on 1 November (CDT, UTC−5), and Sunday's at 01:00 UTC on 2 November, because daylight saving time ended that morning (CST, UTC−6). A range that ends after midnight, such as `11:00 PM–12:30 AM`, ends on the next day.

`from_context` takes `attr`, `regex` and the other refining keys, just like `selector`.

## Dates and times

calsync reads `start`, `end` and `date` with the [field keys](concepts.md#the-field-map) shared by every kind:

- An ISO 8601 attribute such as `datetime="2026-11-21T13:00:00-06:00"` is the most reliable source. Its offset is kept.
- Text such as `Sat Nov 21, 1:00 PM` is read by dateparser, or by `format` (a strftime pattern) when you give one. A year-less date gets the year that puts it nearest after the start of the sync window.
- A time without a date takes its day from the `date` field.
- `tz` applies to times that carry no offset. Without it, they are read as UTC.

## Pagination

Set `pagination.mode` to one of these:

| Mode | Keys | What it does |
|---|---|---|
| `none` | | Reads `fetch.url` once. This is the default. |
| `url_template` | `url_template`, `step_days` | Builds one URL per step across the sync window. `url_template` is a template that also knows `{{date}}`, the first day of each step. `fetch.url` is omitted, because the template gives every page's URL. |
| `click_next` | `selector`, `max_pages` | Headless only. Reads the first page, then clicks the `selector` button and reads again, up to `max_pages` pages in all. It stops early when the button is gone or disabled. |

```yaml
fetch:
  mode: static
pagination:
  mode: url_template
  url_template: "{{url}}?week={{date:%Y-%m-%d}}"
  step_days: 7
```

With a 60-day window this fetches nine weekly pages. The same event can appear on two pages; calsync keeps one copy per uid.

## Headless trade-offs

`mode: headless` loads the page in headless Chromium, lets its scripts run, waits for `wait_for` (or for the network to go quiet when there is no `wait_for`), and parses the resulting HTML with the same selectors as static mode. It is the tool for pages that build their schedule in JavaScript, but it costs more:

- **Speed and memory.** Each run starts a fresh Chromium, which takes a second or more and a few hundred MB of memory, and closes it afterwards. Static runs take milliseconds.
- **Chromium must be installed** where calsync runs, for example with `playwright install --with-deps chromium`. Without it, headless runs fail with an error saying so; static runs are unaffected.
- **Every request counts.** Chromium doesn't reach the network itself. calsync answers each of its requests through the same guarded fetcher static mode uses, so the [SSRF guard](concepts.md#safety-limits), the time limit and the byte limit apply to everything the page loads. Each script, XHR and fetch counts against `CALSYNC_FETCH_MAX_PAGES`, so a script-heavy site may need a higher limit. Images, stylesheets, fonts and media are not downloaded at all, and WebSockets and service workers are refused.
- **Blocked requests.** A script or XHR aimed at a private address is refused and the page carries on without it. If the page itself is refused, or any request breaks the run's limits, the run fails.
- **Redirects** are followed by the guarded fetcher, so the page sees the final response under the URL it asked for.
- **`wait_for` beats guessing.** Set it to the item selector, or to something that appears once the schedule has loaded. Without it, calsync waits until the network has been quiet for half a second, which is slower and less reliable.

Use the [preview cache](concepts.md#safety-limits) while tuning selectors: re-running a preview within five minutes reuses the fetched responses, even in headless mode.
