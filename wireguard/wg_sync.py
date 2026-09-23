#!/usr/bin/env python3
"""SafeNet VPN hub.

Creates the WireGuard interface (key kept in /data), publishes the hub's public
key to the vpn_server table, then every SYNC_SECONDS makes the peers match the
active rows of the routers table and records each router's last handshake and
traffic. Routers are only ever added or removed here, never in the web app.
"""
import logging
import os
import subprocess
import time
from datetime import datetime, timezone

import pymysql

IFACE = os.environ.get('WG_INTERFACE', 'wg-safenet')
PORT = int(os.environ.get('WG_PORT', '51820'))
ADDRESS = os.environ.get('WG_SERVER_ADDRESS', '10.200.0.1/16')
KEY_FILE = os.environ.get('WG_KEY_FILE', '/data/server.key')
SYNC_SECONDS = int(os.environ.get('SYNC_SECONDS', '15'))

log = logging.getLogger('wg-sync')


def sh(*args, stdin=None):
    return subprocess.run(args, input=stdin, text=True, capture_output=True, check=True).stdout


def server_key():
    if not os.path.exists(KEY_FILE):
        os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
        key = sh('wg', 'genkey').strip()
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(key + '\n')
        log.info('generated hub key')
    with open(KEY_FILE) as f:
        private = f.read().strip()
    return sh('wg', 'pubkey', stdin=private).strip()


def ensure_interface():
    if subprocess.run(['ip', 'link', 'show', IFACE], capture_output=True).returncode != 0:
        sh('ip', 'link', 'add', IFACE, 'type', 'wireguard')
        log.info('created %s', IFACE)
    if ADDRESS.split('/')[0] not in sh('ip', '-o', 'addr', 'show', 'dev', IFACE):
        sh('ip', 'addr', 'add', ADDRESS, 'dev', IFACE)
    sh('wg', 'set', IFACE, 'private-key', KEY_FILE, 'listen-port', str(PORT))
    sh('ip', 'link', 'set', IFACE, 'up')


def connect():
    return pymysql.connect(host=os.environ.get('DB_HOST', '127.0.0.1'), port=int(os.environ.get('DB_PORT', '3306')),
                           user=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'],
                           database=os.environ.get('DB_NAME', 'radius'), autocommit=True, connect_timeout=10)


def publish(conn, public_key):
    with conn.cursor() as cur:
        cur.execute('INSERT INTO vpn_server (id, public_key, listen_port, updated_at) VALUES (1, %s, %s, UTC_TIMESTAMP()) '
                    'ON DUPLICATE KEY UPDATE public_key = VALUES(public_key), listen_port = VALUES(listen_port), '
                    'updated_at = VALUES(updated_at)', (public_key, PORT))


def current_peers():
    """{public_key: (allowed_ips, latest_handshake, rx, tx)} from `wg show dump`."""
    peers = {}
    for line in sh('wg', 'show', IFACE, 'dump').splitlines()[1:]:
        f = line.split('\t')
        if len(f) >= 7:
            peers[f[0]] = (f[3], int(f[4] or 0), int(f[5] or 0), int(f[6] or 0))
    return peers


def sync(conn):
    with conn.cursor() as cur:
        cur.execute('SELECT public_key, tunnel_ip FROM routers WHERE is_active = 1')
        wanted = {pub: f'{ip}/32' for pub, ip in cur.fetchall()}
    peers = current_peers()
    for pub in peers.keys() - wanted.keys():
        sh('wg', 'set', IFACE, 'peer', pub, 'remove')
        log.info('removed peer %s', pub[:10])
    for pub, allowed in wanted.items():
        if pub not in peers or peers[pub][0] != allowed:
            sh('wg', 'set', IFACE, 'peer', pub, 'allowed-ips', allowed, 'persistent-keepalive', '25')
            log.info('added peer %s -> %s', pub[:10], allowed)
    with conn.cursor() as cur:
        for pub, (_, handshake, rx, tx) in current_peers().items():
            if handshake:
                seen = datetime.fromtimestamp(handshake, timezone.utc).replace(tzinfo=None)
                cur.execute('UPDATE routers SET last_handshake_at = %s, rx_bytes = %s, tx_bytes = %s WHERE public_key = %s',
                            (seen, rx, tx, pub))


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    public_key = server_key()
    log.info('hub public key %s, port %d, address %s', public_key, PORT, ADDRESS)
    conn = None
    while True:
        try:
            ensure_interface()
            if conn is None:
                conn = connect()
                publish(conn, public_key)
            sync(conn)
        except pymysql.err.ProgrammingError as e:      # tables not created yet by the web app
            log.warning('waiting for database tables: %s', e)
            conn = None
        except (pymysql.MySQLError, OSError) as e:
            log.warning('database: %s', e)
            conn = None
        except subprocess.CalledProcessError as e:
            log.error('%s failed: %s', ' '.join(e.cmd), (e.stderr or '').strip())
        time.sleep(SYNC_SECONDS)


if __name__ == '__main__':
    main()
