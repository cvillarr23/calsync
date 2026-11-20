# Google Calendar sync

A source can write its matched events straight into one of your Google Calendars. Its `.ics` feed keeps working either way.

## Picking a calendar

On the source form, choose a calendar under **Google Calendar**. The list shows the calendars your Google account can add events to, with your primary calendar first. Choose **None (.ics feed only)** to stop syncing to Google. The same field is `target_calendar_id` in the [JSON API](api.md), and `GET /api/calendars` lists the choices.

A dedicated calendar, for example one called "Skating", is easiest to manage. You can hide it, colour it or share it without touching your other events.

## What calsync writes

Each sync, after the site has been read and the events stored, calsync compares the source's matched events with what it pushed last time:

- **New** matched events are added. Each carries a private tag, `extendedProperties.private = {calsync_source, calsync_uid}`, that marks it as calsync's.
- **Changed** events are updated in place: the title, the times, the location, the description or the link.
- **Future** events that the site no longer lists, or that the source's filters now drop, are deleted.
- Events that haven't changed aren't sent again. A sync where nothing on the site changed makes no calls to Google.

Event times are written in UTC; Google shows them in your own time zone. The description holds the site's description followed by the event's link.

## What calsync never touches

- **Events without its tag**, or with another source's tag. Before changing or deleting an event, calsync reads it back from Google and checks the tag.
- **Past events.** Once an event has started, calsync leaves it alone, so your calendar keeps a record of what happened.
- **Anything after a failed read.** If the adapter fails, hits a [safety limit](adapters/concepts.md#safety-limits), or finds no events at all while future events are stored, the sync stops before Google and nothing is deleted.

If you delete a calsync event in Google, it stays deleted until the event changes on the site; calsync then adds it again. Edits you make in Google to a calsync event are overwritten the next time the event changes on the site.

## Changing or clearing the target

When you point a source at a different calendar, the next sync deletes its future events from the old calendar and adds them to the new one. When you set it to **None**, the next sync deletes its future events from the calendar and stops writing to Google. Past events stay where they are.

## Rate limits and outages

When Google answers that calsync is sending too much (`429`, or `403` with a rate-limit reason) or has a server error (`5xx`), calsync waits and tries again: up to four attempts, honouring Google's `Retry-After`. If Google is still failing, the sync is marked as an error and retried on the source's [backoff schedule](api.md#scheduling). Each change is saved as it is made, so the next sync carries on where this one stopped.

## Reconnecting Google

calsync syncs in the background with the refresh token Google gave it when you signed in; see [Google OAuth](google-oauth.md). If that token stops working, sources that sync to Google fail with "Google access was revoked or has expired" and show a **Reconnect Google** link. This happens when you remove calsync from your Google account's third-party access, change your password, or leave the consent screen in *Testing* mode, or when `CALSYNC_TOKEN_ENC_KEY` changed. Click the link and sign in again; Google asks for consent once more, and the next sync carries on. Feeds are not affected.
