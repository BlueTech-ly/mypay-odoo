#!/usr/bin/env bash
# Expose local Odoo (port 8069) with a public HTTPS URL so MyPay can deliver webhooks.
set -euo pipefail

ODOO_URL="${ODOO_URL:-http://127.0.0.1:8069}"
LOG_FILE="${TMPDIR:-/tmp}/mypay-odoo-cloudflared.log"

echo "==> MyPay Odoo webhook tunnel"
echo "    Forwarding public HTTPS → ${ODOO_URL}"
echo

if [[ -n "${TUNNEL_TOKEN:-}" ]]; then
  echo "Using named Cloudflare Tunnel (TUNNEL_TOKEN is set)."
  echo "Ensure the tunnel public hostname proxies to ${ODOO_URL} (or http://odoo:8069 in Compose)."
  echo "Then set Odoo web.base.url to https://YOUR_HOSTNAME and paste the Webhook URL into MyPay."
  exec docker run --rm --network host \
    -e TUNNEL_TOKEN \
    cloudflare/cloudflared:latest \
    tunnel --no-autoupdate run --token "${TUNNEL_TOKEN}"
fi

if command -v cloudflared >/dev/null 2>&1; then
  run_tunnel() {
    cloudflared tunnel --no-autoupdate --url "${ODOO_URL}"
  }
elif command -v docker >/dev/null 2>&1; then
  run_tunnel() {
    docker run --rm --network host cloudflare/cloudflared:latest \
      tunnel --no-autoupdate --url "${ODOO_URL}"
  }
else
  echo "Install cloudflared (https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) or Docker." >&2
  exit 1
fi

: > "${LOG_FILE}"
echo "Starting quick tunnel (trycloudflare.com). Leave this process running."
echo "Log file: ${LOG_FILE}"
echo

run_tunnel 2>&1 | tee "${LOG_FILE}" &
TUNNEL_PID=$!

cleanup() {
  kill "${TUNNEL_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

PUBLIC_URL=""
for _ in $(seq 1 60); do
  PUBLIC_URL="$(grep -Eo 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' "${LOG_FILE}" 2>/dev/null | head -n1 || true)"
  if [[ -n "${PUBLIC_URL}" ]]; then
    break
  fi
  if ! kill -0 "${TUNNEL_PID}" 2>/dev/null; then
    echo "Tunnel process exited early. Check ${LOG_FILE}" >&2
    exit 1
  fi
  sleep 1
done

if [[ -z "${PUBLIC_URL}" ]]; then
  echo "Could not detect trycloudflare.com URL. Check ${LOG_FILE}" >&2
  exit 1
fi

WEBHOOK_URL="${PUBLIC_URL%/}/payment/mypay/webhook"

cat <<EOF

Tunnel is up: ${PUBLIC_URL}

Next steps:
  1. In Odoo: Settings → Technical → System Parameters
       - web.base.url = ${PUBLIC_URL}
       - web.base.url.freeze = True   (optional, keeps the URL stable for this session)
  2. Enable proxy_mode if your deployment sits behind a proxy/tunnel.
  3. Open Payment Providers → MyPay → copy Webhook URL (should be):
       ${WEBHOOK_URL}
  4. Paste that URL into MyPay → Developer API → Webhook URL.
  5. Keep this terminal open while testing payments.

Press Ctrl+C to stop the tunnel.
EOF

wait "${TUNNEL_PID}"
