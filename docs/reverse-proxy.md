# Reverse proxy

A public calsync instance should sit behind a reverse proxy that terminates TLS. Google requires HTTPS for OAuth redirect URIs on any host other than `localhost`.

## Checklist

- Set `CALSYNC_BASE_URL` to the public URL the proxy serves, for example `https://calsync.example`. The OAuth redirect (`<base>/auth/callback`) and the feed URLs are built from it, so it must match what browsers and calendar clients see.
- **Keep `/feeds/*` reachable without authentication.** Calendar clients such as Google Calendar fetch subscribed `.ics` feeds from their own servers and cannot get past a login page, SSO gateway or basic-auth prompt. Each feed URL contains an unguessable token, which acts as its credential. You may put extra authentication in front of the rest of the app, but exempt `/feeds/`.
- Keep `/auth/callback` reachable too; Google redirects the browser there after sign-in.
- Forward the `Host` header and set `X-Forwarded-For` and `X-Forwarded-Proto`.

## Trusting proxy headers

By default calsync ignores `X-Forwarded-*` headers. Set `CALSYNC_TRUST_PROXY_HEADERS=true` so that calsync uses them for the client address and scheme.

!!! warning "Only behind your own proxy"
    When this is on, calsync trusts these headers from **any** peer, because the proxy's address inside a container network is not known in advance. Make sure nothing but the proxy can reach calsync's port. For example, publish the port only on `127.0.0.1`, or don't publish it at all and share a Docker network with the proxy.

## Examples

These examples assume calsync listens on `127.0.0.1:8000` (`-p 127.0.0.1:8000:8000`).

=== "Caddy"

    ```caddy
    calsync.example {
        reverse_proxy 127.0.0.1:8000
    }
    ```

    Caddy obtains a certificate and sets the forwarding headers itself.

=== "nginx"

    ```nginx
    server {
        listen 443 ssl;
        server_name calsync.example;
        # ssl_certificate / ssl_certificate_key ...

        location / {
            proxy_pass http://127.0.0.1:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
    ```
