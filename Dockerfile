# syntax=docker/dockerfile:1
FROM node:22-alpine AS web-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
ENV VITE_API_URL=/
RUN npm run build

FROM python:3.11-slim AS python-dependencies
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN python -m venv "$VIRTUAL_ENV"
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r /tmp/requirements.txt

FROM caddy:2-alpine AS caddy-binary

FROM python:3.11-slim AS runtime
ARG VCS_REF=unknown
ARG VERSION=dev
LABEL org.opencontainers.image.title="Autonomous Trading Bot" \
      org.opencontainers.image.description="Single-image autonomous trading API, dashboard and HTTPS proxy" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.source="https://github.com/Zaernsn/TradingBot"

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DATABASE_URL=sqlite:////var/lib/trading-bot/tradingbot.db
ENV MODEL_DIR=/var/lib/trading-bot/models
ENV XDG_DATA_HOME=/var/lib/trading-bot/caddy-data
ENV XDG_CONFIG_HOME=/var/lib/trading-bot/caddy-config
ENV APP_HOST=:80
ENV APP_PUBLIC_URL=http://localhost

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /srv /var/lib/trading-bot/models /var/lib/trading-bot/caddy-data /var/lib/trading-bot/caddy-config \
    && chown -R app:app /app /srv /var/lib/trading-bot

WORKDIR /app
COPY --from=python-dependencies /opt/venv /opt/venv
COPY --from=caddy-binary /usr/bin/caddy /usr/bin/caddy
COPY --chown=app:app backend/ /app/
COPY --from=web-build --chown=app:app /build/frontend/dist /srv
COPY frontend/Caddyfile /etc/caddy/Caddyfile
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/trading-bot-entrypoint

EXPOSE 80 443 443/udp
VOLUME ["/var/lib/trading-bot"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

ENTRYPOINT ["/usr/local/bin/trading-bot-entrypoint"]
