#!/bin/bash
# Railway entry point — SERVICE_TYPE env var determines which service to run
if [ "$SERVICE_TYPE" = "wa-bridge" ]; then
  echo "[start.sh] Starting WA Bridge..."
  node wa-bridge/index.js
else
  echo "[start.sh] Starting Truman..."
  python -m truman.main_cloud
fi
