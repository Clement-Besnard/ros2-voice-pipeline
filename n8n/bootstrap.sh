#!/bin/sh
# Seeds a fresh n8n instance with the credentials and workflows kept in this
# repository, so `docker compose up -d` gives you a working editor instead of an
# empty one. Runs once per `up`, in the n8n image itself, against the same
# n8n-data volume as the server.
#
# The repository is the source of truth: every run re-imports and OVERWRITES the
# workflows below, because they are matched on their fixed `id`. Edit a workflow
# in the browser and the next `up` will undo it, unless you export it back here
# or set N8N_BOOTSTRAP=false in .env.
#
# Order matters. `import:*` needs an instance owner to exist already, and only
# `n8n start` creates one, so this script runs after the server is healthy - see
# the n8n-init service in docker-compose.yml.

set -eu

if [ "${N8N_BOOTSTRAP:-true}" != "true" ]; then
  echo "[bootstrap] N8N_BOOTSTRAP is not true, leaving the instance alone."
  exit 0
fi

SRC=/bootstrap
WORK=/tmp/n8n-bootstrap

# Ollama lives outside the stack, so both its address and the model to use come
# from .env. They are substituted into the JSON files below.
: "${N8N_OLLAMA_URL:=http://host.docker.internal:11434}"
: "${N8N_OLLAMA_MODEL:=llama3.2}"

on_error() {
  echo
  echo "[bootstrap] FAILED."
  echo "[bootstrap] 'Failed to find owner' above means n8n has no account yet."
  echo "[bootstrap]   -> set N8N_OWNER_MANAGED=true in .env, or create the account"
  echo "[bootstrap]      in the browser once, then run: docker compose up -d n8n-init"
}
trap on_error EXIT

# `${N8N_OLLAMA_URL}` and `${N8N_OLLAMA_MODEL}` are placeholders in the JSON, not
# shell or n8n syntax. Rendering to /tmp keeps the mounted repo read-only.
render() {
  sed -e "s|\${N8N_OLLAMA_URL}|${N8N_OLLAMA_URL}|g" \
      -e "s|\${N8N_OLLAMA_MODEL}|${N8N_OLLAMA_MODEL}|g" \
      "$1" >"$2"
}

rm -rf "$WORK"
mkdir -p "$WORK/credentials" "$WORK/workflows"

for f in "$SRC"/credentials/*.json; do
  [ -e "$f" ] || continue
  render "$f" "$WORK/credentials/$(basename "$f")"
done
for f in "$SRC"/workflows/*.json; do
  [ -e "$f" ] || continue
  render "$f" "$WORK/workflows/$(basename "$f")"
done

# Credential `data` goes in as plain JSON; n8n encrypts it on import with the
# instance's own key, which it reads from the shared n8n-data volume.
if [ -n "$(ls -A "$WORK/credentials" 2>/dev/null)" ]; then
  echo "[bootstrap] importing credentials (Ollama at ${N8N_OLLAMA_URL})"
  n8n import:credentials --separate --input="$WORK/credentials"
fi

if [ -n "$(ls -A "$WORK/workflows" 2>/dev/null)" ]; then
  echo "[bootstrap] importing workflows"
  n8n import:workflow --separate --input="$WORK/workflows"

  # import:workflow always lands workflows deactivated: its --activeState=fromJson
  # flag is rejected outside queue mode. publish:workflow has no such limit, and
  # the running server picks the change up within ~15 s.
  for f in "$WORK"/workflows/*.json; do
    [ -e "$f" ] || continue
    id=$(node -e 'const w=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")); if (w.active && w.id) console.log(w.id)' "$f")
    [ -n "$id" ] || continue
    echo "[bootstrap] publishing workflow $id"
    n8n publish:workflow --id="$id"
  done
fi

trap - EXIT
echo "[bootstrap] done."
