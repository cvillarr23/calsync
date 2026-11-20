# Quickstart

calsync ships as a container image, `ghcr.io/cvillarr23/calsync`, for `linux/amd64` and `linux/arm64`. The image includes headless Chromium for adapters that need a browser.

## 1. Create a Google OAuth client

Follow [Google OAuth](google-oauth.md). Use `<your base URL>/auth/callback` as the redirect URI.

## 2. Generate the secrets

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(32))"                            # CALSYNC_SESSION_SECRET
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())" # CALSYNC_TOKEN_ENC_KEY (a Fernet key)
```

## 3. Run the container

Replace each placeholder with your own value:

```sh
docker run -d --name calsync \
  -p 8000:8000 \
  -v calsync-data:/data \
  -e CALSYNC_BASE_URL=https://calsync.example \
  -e GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com \
  -e GOOGLE_CLIENT_SECRET=your-client-secret \
  -e CALSYNC_SESSION_SECRET=your-session-secret \
  -e CALSYNC_TOKEN_ENC_KEY=your-fernet-key \
  -e CALSYNC_ALLOWED_EMAILS=you@example.com \
  ghcr.io/cvillarr23/calsync:latest
```

The named volume `calsync-data` keeps the SQLite database across upgrades. See [Configuration](configuration.md) for every variable.

## 4. Check it is up

```sh
curl http://localhost:8000/healthz
# {"status":"ok"}
```

The image has a `HEALTHCHECK` on the same endpoint, so `docker ps` shows the container as `healthy` once it is serving.

If the container exits right away, run `docker logs calsync`. A missing or invalid variable is reported by name.

## 5. Put it behind HTTPS

Google only accepts HTTPS redirect URIs for hosts other than `localhost`, so a public instance needs a TLS-terminating reverse proxy. See [Reverse proxy](reverse-proxy.md).

## 6. Sign in and add a source

Open your base URL, sign in with Google, and add a source. Then copy the source's feed URL into your calendar app. [Using the web UI](usage.md) walks through each page.
