# Reverse proxy

!!! note "Coming soon"
    Guidance for running calsync behind a reverse proxy will land here.

In short:

- Set `CALSYNC_BASE_URL` to the public URL the proxy serves.
- Set `CALSYNC_TRUST_PROXY_HEADERS=true` only when the proxy sets the `X-Forwarded-*` headers and nothing else can reach calsync directly.
