# calsync

calsync is a self-hosted web app. It reads community calendars that have no `.ics` export, such as room-booking systems, rec-center pages and club sites. Sites are described by declarative adapter definitions. calsync filters the events by keyword and syncs the matches to a Google Calendar, serves them as an `.ics` feed, or both.

**Documentation:** <https://cvillarr23.github.io/calsync/>

## Run with Docker

The image is `ghcr.io/cvillarr23/calsync` (amd64 and arm64). See the [quickstart](https://cvillarr23.github.io/calsync/quickstart/) for the `docker run` command and the required variables.

## Development

```sh
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
uv run mkdocs serve   # docs at http://127.0.0.1:8000
```

To run the app locally, set the required variables (see the [configuration docs](https://cvillarr23.github.io/calsync/configuration/)), then:

```sh
uv run uvicorn app.main:create_app --factory --reload
```

## License

MIT. See [LICENSE](LICENSE).
