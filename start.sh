#!/usr/bin/env bash
# OmniSight-NVR Universal Surveillance Hub Launcher
set -e

PORT=${1:-8080}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "✦ Initializing OmniSight-NVR Hub on port ${PORT}..."
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

exec python3 "${SCRIPT_DIR}/backend/server.py" "${PORT}"
