# Adapter concepts

This page covers the ideas every adapter kind shares. The [pipeline](pipeline.md) and [HTML](html.md) pages document each kind's own fields.

## Definitions and sources

An **adapter definition** describes how to read one *kind* of site, for example "an EMS Cloud browse page". It knows nothing about any particular calendar.

A **source** is one calendar you sync. It names a definition and supplies values for the definition's **params**, such as the page URL. Many sources can share one definition.

```yaml
id: ems-browse          # lowercase letters, digits and dashes
version: 1              # bump when you change the definition
name: EMS Cloud browse page
kind: pipeline          # pipeline, html or python
params:
  page_url: {type: url, description: The public browse page}
match_hosts: [ems.example.edu]   # suggests this adapter when a matching URL is pasted
uid: [title, start, location]    # optional: map fields hashed into each event's id
# ...kind-specific fields, then `map`
```

### Params

Each param has a `type` (`url`, `string` or `int`; the default is `string`), an optional `default` of that type, and an optional `description` shown in the source form. Param names are identifiers: letters, digits and underscores, not starting with a digit.

### The field map

`map` turns each extracted item into an event. `title` and `start` are required. `end`, `date`, `location`, `description`, `url` and `skip_if` are optional. Every field reads its value from exactly one source:

| Key | Reads |
|---|---|
| `jsonpath` | a JSONPath into a JSON item |
| `selector` | a CSS selector inside an HTML item, plus optional `attr` to read an attribute instead of the text |
| `from_context` | a CSS selector matched against the nearest ancestor or preceding element, for grids whose date sits in a header row |

These keys then refine the value:

- `regex` keeps the first capture group, or the whole match if there is none.
- `strip` trims whitespace.
- `tz` is an IANA time zone, such as `UTC` or `America/Los_Angeles`.
- `format` is a strftime pattern. Without one, calsync parses the date with dateparser.
- `time_range_regex` splits text such as `7:00–8:30 PM` into a start and an end.
- `default_duration_min` gives the length of an event that has no end.
- `skip_if` takes `equals` and drops items whose value matches it. For example, `skip_if: {jsonpath: "$.StatusTypeId", equals: -12}` drops cancelled bookings.

## Templates

Strings such as URLs, headers and request bodies can contain `{{...}}` templates. Templates are **not** Jinja: there are no loops, conditions, attribute access or code. Only these forms exist:

| Form | Result |
|---|---|
| `{{page_url}}` | the variable's value |
| `{{date:%Y-%m-%d %H:%M:%S}}` | a date variable formatted with a strftime pattern |
| `{{origin(page_url)}}` | the scheme, host and port of a URL, such as `https://ems.example.edu` |

Variables are the definition's params plus anything earlier pipeline steps saved with `as`. Any other expression, an unknown helper or a variable that isn't defined yet is a validation error, reported with the field's path (for example `steps.3.http.url`).

Inside text, objects and lists are written as compact JSON and dates as ISO 8601. In a JSON request body, a string that is *only* a template, such as `data: "{{browse_data}}"`, embeds the value itself. An extracted object is sent as an object, not as a string of JSON.

## Validation and the JSON Schema

calsync validates definitions on the server when you save them, and reports each problem with the path of the field at fault. Unknown keys are errors, so typos don't pass silently.

The schema is published as JSON Schema at `/schema/adapter.json` on your instance. Point your editor at it for completion and inline errors. For example, with the YAML language server:

```yaml
# yaml-language-server: $schema=https://calsync.example/schema/adapter.json
```

The template and cross-field checks described above run only on the server.

## Built-in and user definitions

- **User definitions** are created in the UI and stored in the database. They can use the `pipeline` and `html` kinds.
- **Built-in definitions** ship with calsync as YAML files in the `adapters/` directory and are read-only. None ship yet.
- The **`python`** kind names a function registered in calsync's code, as `entrypoint: module:function`. It is the escape hatch for sites the declarative kinds can't handle, so it is limited to built-in definitions. A user definition with `kind: python` is rejected.

## Safety limits

Adapters fetch URLs that users supply, so every fetch is constrained:

- **SSRF guard.** Before connecting, calsync resolves the host and checks **every** address it resolves to. It refuses private (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.0/8`, `::1`), link-local (`169.254.0.0/16`, which includes cloud metadata endpoints), CGNAT (`100.64.0.0/10`), unspecified, multicast and reserved addresses, including IPv4-mapped IPv6 forms. The connection goes to the address that was checked, so DNS rebinding can't swap it. Each redirect hop is checked the same way. Environment proxy settings are ignored. Set `CALSYNC_FETCH_ALLOW_PRIVATE=true` only if you need to read calendars on your own network.
- **Per-run budget.** One adapter run shares a time limit (`CALSYNC_FETCH_TIMEOUT_S`), a request limit (`CALSYNC_FETCH_MAX_PAGES`, which counts redirect hops) and a download limit (`CALSYNC_FETCH_MAX_BYTES`, which counts decompressed bytes). A run that exceeds any of them fails with an error saying which. See [Configuration](../configuration.md).
- **Preview cache.** While you edit a definition, the pages that previews fetch are cached for about five minutes. Tweaking a selector doesn't hit the site again.
- **Requests.** Each run keeps its own cookie jar and sends `calsync/<version>` as its User-Agent unless the definition sets one.
