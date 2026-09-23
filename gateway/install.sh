#!/bin/bash
# Install/update the SafeNet gateway on this machine. Run with sudo.
# Keeps an existing /etc/safenet-gateway/gateway.env.
set -euo pipefail
cd "$(dirname "$0")"

install -d -m 755 /opt/safenet-gateway
install -d -m 700 /etc/safenet-gateway
install -m 755 portal.py safenet-gw-firewall safenet-gw-dnsmasq-conf /opt/safenet-gateway/
install -m 644 portal_ui.py portal.css /opt/safenet-gateway/
install -d -m 755 /opt/safenet-gateway/img
for logo in ../static/img/*.png ../static/img/*.jpg; do
    [ -f "$logo" ] && install -m 644 "$logo" /opt/safenet-gateway/img/
done
install -m 644 systemd/safenet-gw-*.service /etc/systemd/system/
if [[ ! -f /etc/safenet-gateway/gateway.env ]]; then
    install -m 600 gateway.env.example /etc/safenet-gateway/gateway.env
    echo "Created /etc/safenet-gateway/gateway.env - set RADIUS_SECRET and interfaces, then:"
    echo "  sudo systemctl enable --now safenet-gw-firewall safenet-gw-dns safenet-gw-portal"
fi
systemctl daemon-reload
for unit in safenet-gw-firewall safenet-gw-dns safenet-gw-portal; do
    systemctl is-active --quiet "$unit" && systemctl restart "$unit" || true
done
echo "Installed."
