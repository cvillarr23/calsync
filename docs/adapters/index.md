# Adapters

An adapter definition tells calsync how to read one kind of site. Definitions are written in YAML or JSON and edited in the UI. Adding a new site doesn't require any code.

There are three kinds:

- [**pipeline**](pipeline.md): an ordered list of HTTP, extraction and pagination steps. It suits sites backed by a JSON API.
- [**html**](html.md): CSS selectors over a rendered page, fetched statically or in a headless browser.
- **python**: built-in adapters only, for sites that need custom code. User-created definitions cannot use this kind.

Start with [Concepts](concepts.md), which covers the parts every kind shares: params, the field `map`, templates, validation and safety limits. calsync serves the full schema as JSON Schema at `/schema/adapter.json`.
