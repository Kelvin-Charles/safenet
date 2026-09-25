#!/bin/bash
# Give the Omada Controller the same Let's Encrypt certificate as radius.safezonetz.com
# (kept by Nginx Proxy Manager). Restarts the controller only when the certificate changed.
# Cron: weekly. Usage: ./update_cert.sh [--force]
set -euo pipefail
cd "$(dirname "$0")"
PROXY=proxy-manager-app-1
LIVE=/etc/letsencrypt/live/npm-230            # radius.safezonetz.com in the proxy
umask 077
mkdir -p cert
docker exec "$PROXY" cat "$LIVE/fullchain.pem" > cert/tls.crt.new
docker exec "$PROXY" cat "$LIVE/privkey.pem" > cert/tls.key.new
if ! openssl x509 -in cert/tls.crt.new -noout -checkend 86400 >/dev/null; then
    echo "$(date -Is) certificate from the proxy is missing or expiring; not using it" >&2
    rm -f cert/*.new; exit 1
fi
if [[ "${1:-}" != --force ]] && cmp -s cert/tls.crt.new cert/tls.crt && cmp -s cert/tls.key.new cert/tls.key; then
    rm -f cert/*.new; exit 0
fi
mv cert/tls.crt.new cert/tls.crt
mv cert/tls.key.new cert/tls.key
echo "$(date -Is) new certificate $(openssl x509 -in cert/tls.crt -noout -enddate); restarting the controller"
docker compose up -d --force-recreate
