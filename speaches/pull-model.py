"""Installs the Whisper model Speaches needs, before the server starts.

Speaches 0.8.3 ships with no model and does NOT fetch one on first use: it
answers 404 "Model is not installed locally" and stt_node fails on every
utterance. 0.9 will do this itself through a `preload_models` setting, at
which point this can go away.

Runs in the server's own image, so the HuggingFace cache is written exactly
the way the server reads it back - from the hf-hub-cache volume. Idempotent,
and offline on a warm cache: nothing touches the network once the model is in.
"""

import os

from huggingface_hub import snapshot_download

# What the server's own POST /v1/models pulls, README.md included: GET
# /v1/models reads the model card to decide what is installed, so without it
# the model is there but invisible.
FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json",
         "vocabulary.*", "README.md"]

model = os.environ["STT_MODEL"]
try:
    snapshot_download(model, allow_patterns=FILES, local_files_only=True)
except Exception:  # noqa: BLE001 - absent, or a download cut short last time
    print(f'[speaches] downloading {model}, several minutes on a first run...', flush=True)
    snapshot_download(model, allow_patterns=FILES)
    print('[speaches] done.', flush=True)
else:
    print(f'[speaches] {model} already installed, nothing to do.', flush=True)
