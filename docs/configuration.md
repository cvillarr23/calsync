# Configuration

calsync reads its configuration from environment variables only. If a required variable is missing or a value is invalid, the app refuses to start, and the error names each offending variable.

## Required

| Variable | Description |
|---|---|
| `CALSYNC_BASE_URL` | The public base URL where calsync is reachable, for example `https://calsync.example`. It is used to build the OAuth redirect (`<base>/auth/callback`) and the feed URLs. |
| `GOOGLE_CLIENT_ID` | The OAuth web client ID. See [Google OAuth](google-oauth.md). |
| `GOOGLE_CLIENT_SECRET` | The OAuth web client secret. |
| `CALSYNC_SESSION_SECRET` | A random string that signs session cookies. Use at least 32 random bytes. |
| `CALSYNC_TOKEN_ENC_KEY` | A Fernet key that encrypts stored Google refresh tokens. |

You can generate the two secrets with:

```sh
python -c "import secrets; print(secrets.token_urlsafe(32))"                             # session secret
python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())" # token key (Fernet)
```

## Optional

| Variable | Default | Description |
|---|---|---|
| `CALSYNC_DATA_DIR` | `/data` | The directory for the SQLite database. Mount a persistent volume here. |
| `CALSYNC_ALLOWED_EMAILS` | *(empty)* | A comma-separated list of Google accounts allowed to sign in. Matching is case-insensitive. |
| `CALSYNC_MIN_INTERVAL_MIN` | `30` | The shortest sync interval, in minutes, that a source may use. |
| `CALSYNC_FETCH_TIMEOUT_S` | `15` | The time limit, in seconds, for each adapter run. |
| `CALSYNC_FETCH_MAX_PAGES` | `20` | The most pages or requests one adapter run may make. In [headless mode](adapters/html.md#headless-trade-offs), every script and XHR the page loads counts too. |
| `CALSYNC_FETCH_MAX_BYTES` | `2097152` | The most bytes (2 MiB) one adapter run may download. |
| `CALSYNC_FETCH_ALLOW_PRIVATE` | `false` | Allows fetching private, loopback, link-local and CGNAT addresses. Leave this off unless you need it. While it is off, the SSRF guard is active. |
| `CALSYNC_TRUST_PROXY_HEADERS` | `false` | Uses `X-Forwarded-For` and `X-Forwarded-Proto` for the client address and scheme, accepting them from any peer. Turn this on only when calsync is reachable solely through a reverse proxy you control. See [Reverse proxy](reverse-proxy.md). |

!!! warning "Restrict who can sign in"
    If `CALSYNC_ALLOWED_EMAILS` is empty, **any Google account** can sign in to your instance. Set it whenever calsync is reachable from the internet.

## Container

The image `ghcr.io/cvillarr23/calsync` is built for `linux/amd64` and `linux/arm64`.

| Tag | Points at |
|---|---|
| `latest` | The newest build of the `main` branch. |
| `sha-<short sha>` | One specific commit. |
| `1.2.3`, `1.2` | Release `v1.2.3`, and the newest patch release of `1.2`. |

- The app listens on port **8000** inside the container.
- `CALSYNC_DATA_DIR` is `/data`, which is declared as a volume. Mount a named volume or a host directory there.
- The app runs as the non-root user `pwuser`, with uid and gid `1001`. A named volume needs no setup. If you bind-mount a host directory, make it writable by uid 1001: `chown 1001:1001 /path/to/data`.
- The image's `HEALTHCHECK` polls `GET /healthz`.
- Pin a version tag or `sha-` tag in production, and upgrade deliberately.
