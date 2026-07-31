#!/bin/bash
set -euo pipefail

python3 /usr/local/bin/render-freeradius-sql.py

# Stock Ubuntu FreeRADIUS 3.0 ships a broken filter_username policy where
# /\.\./ matches ANY two characters (backslashes stripped before the regex
# engine). That rejects every username — including PEAP inner identities
# handled by sites-enabled/inner-tunnel (outer "default" already disables it).
for site in \
  /etc/freeradius/3.0/sites-enabled/inner-tunnel \
  /etc/freeradius/3.0/sites-available/inner-tunnel
do
  if [[ -f "$site" ]]; then
    sed -i -E 's/^([[:space:]]*)filter_username([[:space:]]*)$/\1# filter_username\2/' "$site"
  fi
done

# Prefer PEAP for 802.1X (WPA-Enterprise) instead of starting with EAP-MD5.
if [[ -f /etc/freeradius/3.0/mods-enabled/eap ]]; then
  sed -i 's/^[[:space:]]*default_eap_type = md5/	default_eap_type = peap/' \
    /etc/freeradius/3.0/mods-enabled/eap
fi

exec "$@"
