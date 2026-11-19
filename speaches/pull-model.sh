#!/bin/sh
# Installs the Whisper model Speaches needs, once, at `docker compose up`.
#
# Speaches 0.8.3 ships with no model and does NOT fetch one on first use: it
# answers 404 "Model is not installed locally" and stt_node fails on every
# utterance. Its own `preload_models` setting would do this at startup, but it
# only exists from 0.9.0 onwards, still a release candidate today - when that
# ships, this container can go away and the setting takes over.
#
# Idempotent: if the model is already in the hf-hub-cache volume, this exits
# without downloading anything.

set -eu

# Service name on the compose network; override to run this from outside.
API=${SPEACHES_URL:-http://speaches:8000}
: "${STT_MODEL:?STT_MODEL is not set}"

if curl -fsS --max-time 30 "$API/v1/models" | grep -q "\"$STT_MODEL\""; then
  echo "[speaches] $STT_MODEL already installed, nothing to do."
  exit 0
fi

echo "[speaches] downloading $STT_MODEL - several minutes on a first run..."
# No timeout short enough to matter here: ~1.5 GB for distil-large-v3.
curl -fsS --max-time 3600 -X POST "$API/v1/models/$STT_MODEL"
echo
echo "[speaches] done."
