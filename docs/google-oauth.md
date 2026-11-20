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

The redirect URI calsync sends is exactly `CALSYNC_BASE_URL` with `/auth/callback` appended, without a doubled slash, whether or not the base URL ends in `/`. Google compares it character for character with the one you registered, so register it in the same form, including the scheme and any port.

## How sign-in works

- calsync asks for the scopes above with `access_type=offline`, so Google returns a **refresh token** that lets calsync sync while you're signed out. The token is encrypted with `CALSYNC_TOKEN_ENC_KEY` before it's stored.
- Google only sends a refresh token from its consent screen. If a sign-in comes back without one and calsync has none stored for you, it sends you through the consent screen once more.
- After Google's sign-in, calsync checks the account. The email must be verified by Google and, when `CALSYNC_ALLOWED_EMAILS` is set, on that list. Any other account sees an "isn't allowed" page, and no session is created.
- The sign-in `state` and `nonce` are checked on the way back, so a callback link can't be replayed or forged.

!!! warning "Publish the consent screen"
    Set the consent screen's publishing status to **In production**. An unverified app is fine for personal use; Google shows a warning screen you can click through. In *Testing* mode, refresh tokens expire after 7 days, and background syncs stop working.
