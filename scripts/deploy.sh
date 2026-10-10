#!/bin/bash
# Deploy the latest SafeNet: pull, build the images, restart. Safe to run again.
# Use this from the GitHub webhook too: newer Docker Compose builds with "bake", which stops at a
# question for our host-network builds ("pass --allow=network.host") and never finishes on its own.
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only

# 1. Docker Compose with the classic builder
if COMPOSE_BAKE=false docker compose build 2>&1 | tee /tmp/safenet-build.log && ! grep -q 'allow=network.host' /tmp/safenet-build.log; then
    echo "Built with docker compose."
else
    # 2. Plain docker build (allows the host network without asking)
    echo "docker compose wants extra permission to build; building each image with docker build instead."
    docker build --network host -t safenet-web -f Dockerfile .
    docker build --network host -t safenet-freeradius -f freeradius/Dockerfile .
    docker build --network host -t safenet-wireguard -f wireguard/Dockerfile .
fi

docker compose up -d --no-build
docker image prune -f >/dev/null || true      # old images fill the disk over time
echo "Deployed $(git log --oneline -1)"
