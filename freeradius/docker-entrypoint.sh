#!/bin/bash
set -euo pipefail
python3 /usr/local/bin/render-freeradius-sql.py
exec "$@"
