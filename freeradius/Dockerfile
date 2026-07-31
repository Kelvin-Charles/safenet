# FreeRADIUS Dockerfile with Multi-Vendor Support
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install FreeRADIUS and dependencies
RUN apt-get update && apt-get install -y \
    freeradius \
    freeradius-mysql \
    freeradius-utils \
    mariadb-client \
    python3-minimal \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Copy custom configuration files
COPY freeradius/radiusd.conf /etc/freeradius/3.0/radiusd.conf
COPY freeradius/clients.conf /etc/freeradius/3.0/clients.conf
# Path avoids freeradius/sites-available/default (old bind mounts created a directory there).
COPY freeradius/default-server /etc/freeradius/3.0/sites-available/default
COPY freeradius/mods-available/sql.template /etc/freeradius/3.0/mods-available/sql.template
COPY freeradius/render-freeradius-sql.py /usr/local/bin/render-freeradius-sql.py
COPY freeradius/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh /usr/local/bin/render-freeradius-sql.py \
    && touch /etc/freeradius/3.0/mods-available/sql \
    && ln -sf /etc/freeradius/3.0/mods-available/sql /etc/freeradius/3.0/mods-enabled/sql

# Copy vendor dictionaries (already included in FreeRADIUS, but we can add custom ones)
# The standard installation includes dictionaries for:
# - Cisco (dictionary.cisco)
# - MikroTik (dictionary.mikrotik)
# - Ubiquiti (dictionary.ubnt)
# - And many others in /usr/share/freeradius/

# Create directory for custom dictionaries if needed
RUN mkdir -p /etc/freeradius/3.0/dictionary.d

# Expose RADIUS ports
EXPOSE 1812/udp 1813/udp

# Health check: just verify the auth socket is listening. Avoids spamming
# the logs with bogus Access-Requests for a hard-coded "test" user.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ss -uln 'sport = :1812' | grep -q ':1812' || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
# -f = foreground (required for Docker), normal log level.
# Do NOT use -X in production: it dumps every auth packet to stdout
# and floods `docker logs` / attached terminals.
CMD ["freeradius", "-f"]


