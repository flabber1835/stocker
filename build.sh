#!/bin/sh
# Build the shared base image first, then all service images.
# Use this instead of plain `docker compose build` since service
# Dockerfiles depend on stocker-base:latest being present locally.
#
# Usage:
#   ./build.sh            — build everything
#   ./build.sh --no-cache — force full rebuild from scratch
set -e
echo "[build] Building stocker-base:latest..."
docker build --network host -t stocker-base:latest -f Dockerfile.base .
echo "[build] Building service images..."
docker compose build "$@"
echo "[build] Done."
