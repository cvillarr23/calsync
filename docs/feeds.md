# Calendar feeds

Every source has its own `.ics` feed. The feed holds the source's events that haven't ended yet and pass its include and exclude filters. Any calendar app that can subscribe to a URL can show it, whether or not you also sync the source to Google Calendar.

## The feed URL

The feed URL looks like this:

```
https://calsync.example/feeds/<feed-token>.ics
```

The host is your `CALSYNC_BASE_URL`, and the token is a long random string calsync creates with the source. The `feed_url` field of each source in the [JSON API](api.md) gives the full URL.

!!! warning "The URL is the password"
    Feeds have no login, because calendar apps can't sign in. Anyone who has the URL can read the feed, so share it only with people who should see these events.

## What's in a feed

- Each event's `UID` stays the same across syncs, so calendar apps update the event in place instead of adding duplicates.
- An event that leaves the source site, or stops passing the filters, disappears from the feed. Past events are dropped from the feed once they end.
- The calendar is named after the source (`X-WR-CALNAME`).
- If the adapter gives no end time, the event is shown as one hour long.
- Changing a source's filters changes the feed straight away, without waiting for the next sync.

## Subscribing

Each app checks the feed on its own schedule, which calsync can't control. New events can take from minutes to a day to show up.

### Google Calendar

1. On a computer, open [Google Calendar](https://calendar.google.com).
2. Next to **Other calendars**, click **+** and then **From URL**.
3. Paste the feed URL and click **Add calendar**.

Google refreshes subscribed calendars every few hours, and sometimes less often. If you need changes to show up quickly, give the source a target calendar (`target_calendar_id` in the [JSON API](api.md)) instead, so calsync writes events to Google directly.

### Apple Calendar

On a Mac:

1. Choose **File** > **New Calendar Subscription**.
2. Paste the feed URL and click **Subscribe**.
3. Choose how often to refresh with **Auto-refresh**. To sync the subscription to your other devices, set **Location** to **iCloud**.

On an iPhone or iPad, go to **Settings** > **Calendar** > **Accounts** > **Add Account** > **Other** > **Add Subscribed Calendar**, then paste the URL.

### Outlook

In Outlook on the web or in new Outlook:

1. Open **Calendar** and choose **Add calendar**.
2. Choose **Subscribe from web**.
3. Paste the feed URL, give the calendar a name, and choose **Import**.

Outlook usually refreshes subscribed calendars a few times a day.
