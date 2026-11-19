# Google OAuth

calsync signs users in with Google, and it uses the same grant to read the calendar list and write events.

## Create the client

1. Create a project in the Google Cloud console and enable the **Google Calendar API**.
2. Configure the OAuth consent screen and add these scopes:
    - `openid`
    - `email`
    - `https://www.googleapis.com/auth/calendar.calendarlist.readonly`
    - `https://www.googleapis.com/auth/calendar.events`
3. Create an OAuth client ID of type **Web application**. Add `<CALSYNC_BASE_URL>/auth/callback` as an authorized redirect URI, for example `https://calsync.example/auth/callback`. Google accepts plain `http://` only for `localhost`. A public instance needs HTTPS; see [Reverse proxy](reverse-proxy.md).
4. Put the client ID and secret into `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

!!! warning "Publish the consent screen"
    Set the consent screen's publishing status to **In production**. An unverified app is fine for personal use; Google shows a warning screen you can click through. In *Testing* mode, refresh tokens expire after 7 days, and background syncs stop working.
