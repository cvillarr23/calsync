# calsync

Many community calendars have no `.ics` export: room-booking systems, rec-center schedules, club sites. calsync is a self-hosted web app that turns calendars like these into something you can subscribe to.

- **Sources.** Register a calendar page and pick the adapter that knows how to read it.
- **Adapters.** Declarative YAML or JSON definitions describe how to fetch a site and extract its events. New sites are added in the UI, without writing code.
- **Filters.** Include and exclude keywords keep only the events you care about.
- **Outputs.** calsync syncs matching events to a Google Calendar you choose, publishes them as an `.ics` feed, or both.
- **Schedule.** Each source re-syncs on its own interval, backs off while its site is failing, and can be synced on demand with Sync now.

!!! note "Early development"
    calsync is under active development. Some pages describe features that haven't landed yet.

## Where to next

- [Quickstart](quickstart.md): get an instance running.
- [Using the web UI](usage.md): sign in, add sources and write adapters.
- [Configuration](configuration.md): every environment variable.
- [Google OAuth](google-oauth.md): create the OAuth client calsync signs in with.
- [Adapters](adapters/index.md): describe a new site.
- [Calendar feeds](feeds.md): subscribe to a source in Google, Apple or Outlook.
- [JSON API](api.md): manage sources and adapters from scripts.
