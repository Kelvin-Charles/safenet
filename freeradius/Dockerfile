# FreeRADIUS Dockerfile with Multi-Vendor Support
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install FreeRADIUS and dependencies
RUN apt-get update && apt-get install -y \
    freeradius \
    freeradius-mysql \
    freeradius-utils \
    mariadb-client \
    && rm -rf /var/lib/apt/lists/*

# Copy custom configuration files
COPY freeradius/radiusd.conf /etc/freeradius/3.0/radiusd.conf
COPY freeradius/clients.conf /etc/freeradius/3.0/clients.conf
COPY freeradius/mods-available/sql /etc/freeradius/3.0/mods-available/sql

# Enable SQL module
RUN ln -sf /etc/freeradius/3.0/mods-available/sql /etc/freeradius/3.0/mods-enabled/sql

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

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD radtest test test localhost 0 testing123 || exit 1

# Run FreeRADIUS in foreground
CMD ["freeradius", "-X"]


