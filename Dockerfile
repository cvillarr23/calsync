# Must match the playwright version pinned in pyproject.toml: browser builds are per version.
ARG PLAYWRIGHT_VERSION=1.65.2

FROM mcr.microsoft.com/playwright/python:v${PLAYWRIGHT_VERSION}-noble

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first, so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY README.md LICENSE ./
COPY app ./app
COPY adapters ./adapters
RUN uv sync --locked --no-dev

RUN mkdir -p /data && chown pwuser:pwuser /data

ENV PATH=/app/.venv/bin:$PATH \
    CALSYNC_DATA_DIR=/data

USER pwuser
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]

CMD ["python", "-m", "app.serve"]
