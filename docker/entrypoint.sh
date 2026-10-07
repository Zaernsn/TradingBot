#!/bin/sh
set -eu

backend_pid=''
caddy_pid=''

stop_processes() {
    [ -z "$backend_pid" ] || kill -TERM "$backend_pid" 2>/dev/null || true
    [ -z "$caddy_pid" ] || kill -TERM "$caddy_pid" 2>/dev/null || true
}

trap stop_processes INT TERM

mkdir -p /var/lib/trading-bot/models /var/lib/trading-bot/caddy-data /var/lib/trading-bot/caddy-config
chown -R app:app /var/lib/trading-bot

gosu app python -m app.cli.migrate
gosu app uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers &
backend_pid=$!
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &
caddy_pid=$!

status=0
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$caddy_pid" 2>/dev/null; do
    sleep 1
done

if ! kill -0 "$backend_pid" 2>/dev/null; then
    wait "$backend_pid" || status=$?
elif ! kill -0 "$caddy_pid" 2>/dev/null; then
    wait "$caddy_pid" || status=$?
fi

stop_processes
wait "$backend_pid" 2>/dev/null || true
wait "$caddy_pid" 2>/dev/null || true
exit "$status"
