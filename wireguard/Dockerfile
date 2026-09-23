# SafeNet VPN hub: WireGuard interface for tenants' routers, peers synced from the database
FROM alpine:3.20
RUN apk add --no-cache wireguard-tools iproute2 python3 py3-pymysql
COPY wireguard/wg_sync.py /usr/local/bin/wg_sync.py
CMD ["python3", "-u", "/usr/local/bin/wg_sync.py"]
