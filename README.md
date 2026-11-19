# voice_pipeline

A ROS 2 voice assistant pipeline: microphone → speech-to-text → LLM → spoken reply.

Audio is captured and segmented locally; transcription, generation and synthesis are
offloaded to self-hosted HTTP services (a Whisper server, an [n8n](https://n8n.io) agent
backed by [Ollama](https://ollama.com), and a
[Kokoro](https://github.com/remsky/Kokoro-FastAPI) server), and every stage talks over
plain ROS 2 topics so any node can be swapped or inspected on its own.

- ROS 2 **Lyrical** / Python 3.14, `ament_python` package built with `colcon`
- Workspace root with a single package: `src/voice_pipeline`
- The loop is closed end to end: it listens, answers and speaks

## Architecture

```
microphone ──► stt_node ──► /user_text ──► llm_node ──► /llm_reply ──► tts_node ──► speaker
                                              │           echo_node (uppercase stub)
                                              ▼
                                      n8n AI Agent ──► Ollama
                                      (memory, tools)
```

| Topic            | Type                  | Published by | Consumed by          |
| ---------------- | --------------------- | ------------ | -------------------- |
| `/user_text`     | `std_msgs/msg/String` | `stt_node`   | `llm_node`           |
| `/llm_reply`     | `std_msgs/msg/String` | `llm_node`   | `tts_node`           |
| `/tts_speaking`  | `std_msgs/msg/Bool`   | `tts_node`   | nothing yet, see Roadmap |

### Nodes

**`stt_node`** — captures 16 kHz mono audio with `sounddevice`, calibrates the ambient
noise floor for one second at startup, then uses an RMS threshold with a pre-roll buffer
to cut out utterances. Each segment is sent as a WAV file to an OpenAI-compatible
`/v1/audio/transcriptions` endpoint (faster-whisper) and published on `/user_text`.
Empty or punctuation-only transcripts are dropped as Whisper hallucinations.

| Parameter          | Default                                      | Description                             |
| ------------------ | -------------------------------------------- | --------------------------------------- |
| `stt_url`          | `http://10.8.0.1:8001`                       | Whisper server base URL                 |
| `model`            | `Systran/faster-distil-whisper-large-v3`      | Transcription model                     |
| `language`         | `en`                                         | Transcription language                  |
| `threshold_factor` | `3.0`                                        | Speech threshold = noise floor × factor |
| `min_threshold`    | `300.0`                                      | Threshold floor (int16 RMS)             |
| `silence_ms`       | `600`                                        | Silence that ends an utterance          |
| `min_speech_ms`    | `300`                                        | Shorter bursts are ignored              |
| `max_speech_ms`    | `15000`                                      | Hard cap on one utterance               |
| `preroll_ms`       | `300`                                        | Audio kept before speech onset          |
| `device`           | `-1`                                         | Input device index, `-1` = default      |

**`llm_node`** — subscribes to `/user_text`, POSTs the question to the n8n webhook and
publishes the agent's answer on `/llm_reply`. It does not talk to Ollama directly: the
model, its address and the system prompt all live in the n8n workflow, which also gives
the conversation a memory the node does not have to keep.

The webhook answers in NDJSON, one object per token, so the node reassembles the
`"type": "item"` events into a single reply before publishing. The trap worth knowing
about: n8n returns **HTTP 200 even when the agent fails**, with the reason in a
`"type": "error"` event, so `raise_for_status` never sees it. The node raises on that
event instead, and publishes nothing rather than an empty string.

A conversation ends with silence. The node keeps one key while the exchanges follow one
another, and mints a new one after `session_timeout` seconds of nothing — so the agent
remembers what you said a minute ago, but does not greet you this evening still holding
this morning's thread. The key sent to n8n is `<session_id>-<random hex>`; a node restart
also starts a fresh one. Setting the timeout very high gives you back a single endless
conversation, and setting it to `0` makes every question stateless.

| Parameter         | Default                             | Description                        |
| ----------------- | ----------------------------------- | ---------------------------------- |
| `n8n_url`         | `http://10.8.0.1:5678/webhook/llm`  | Webhook of the agent workflow      |
| `session_id`      | `ros-voice`                         | Prefix of the conversation key     |
| `session_timeout` | `300.0`                             | Silence, in seconds, that ends one |

`session_timeout` is a float, so override it as `600.0` rather than `600` — ROS refuses
the type mismatch.

The system prompt still constrains the model to two or three spoken sentences with no
markdown, lists or emoji — which cut a typical reply from ~1300 to ~50 tokens — but it is
now the `systemMessage` of the AI Agent node, in
`n8n/workflows/basic-workflow.json`.

**`tts_node`** — subscribes to `/llm_reply` and streams it to a Kokoro
`POST /v1/audio/speech` endpoint as raw 24 kHz mono PCM, playing the chunks as they
arrive on a `sounddevice` output stream. Playback waits for a 200 ms pre-buffer before
starting, so a network hiccup does not cut the voice mid-word, and the time to first
audio is logged. Replies are queued, so a second answer never talks over the first.
While speaking, the node publishes `true` on `/tts_speaking`, and `false` once the queue
has been empty for 300 ms.

| Parameter  | Default                 | Description              |
| ---------- | ----------------------- | ------------------------ |
| `tts_url`  | `http://10.8.0.1:8880`  | Kokoro server base URL   |
| `voice`    | `af_heart`              | Kokoro voice             |

**`echo_node`** — a stand-in for `llm_node`: republishes `/user_text` in uppercase on
`/llm_reply`. Useful to check the plumbing without a GPU or network round trip.

### Helper scripts

Both are plain scripts (not entry points), run them with `python3`:

- `ask.py` — type questions on stdin, publishes them to `/user_text` and prints replies
  from `/llm_reply` with the round-trip latency.
- `bench.py` — runs a fixed set of prompts twice, once straight against Ollama and once
  through the ROS graph, and reports prompt/generation token counts, tokens per second,
  and the overhead. Since `llm_node` goes through n8n, that second figure now measures
  ROS *and* the agent, which is the honest number for the pipeline as it stands.

## Requirements

- ROS 2 Lyrical with `rclpy`, `std_msgs`, `launch` and `launch_ros`
- Python: `requests`, `numpy`, `sounddevice` (which needs PortAudio, e.g.
  `sudo apt install libportaudio2`)
- An [Ollama](https://ollama.com) server with the generation model pulled
  (`ollama pull qwen3:8b`). n8n is what calls it, not the ROS nodes.
- The speech services, which `docker-compose.yml` provides (see below): a Whisper
  server on `POST /v1/audio/transcriptions` and a
  [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) server on
  `POST /v1/audio/speech` with PCM streaming

Every service is reached over plain HTTP, so they can sit on the same machine as the
nodes or on a remote GPU box. The node defaults point at a private VPN address and will
need to be overridden for any other setup — see the `--ros-args` examples below.

## Supporting services

`docker-compose.yml` brings up three long-running containers, plus a one-shot `n8n-init`
that seeds n8n and exits:

| Service    | Host port | What it serves                                     |
| ---------- | --------- | -------------------------------------------------- |
| `speaches` | `8001`    | Whisper, the `stt_url` the `stt_node` calls         |
| `kokoro`   | `8880`    | Kokoro, the `tts_url` the `tts_node` calls          |
| `n8n`      | `5678`    | automation editor and webhooks                      |

Speaches and Kokoro both run on the GPU, and image tags are pinned.

Speaches ships with no model and **does not fetch one on first use** — it answers `404
Model is not installed locally` and `stt_node` fails on every utterance. `PRELOAD_MODELS`
in `docker-compose.yml` therefore downloads it at startup when the `hf-hub-cache` volume
does not already have it, and the container refuses to start if that fails. It reads
`STT_MODEL` from `.env`, which **must match the `model` parameter of `stt_node`**; they
are two different programs and nothing checks that they agree.

So the first `docker compose up` is slow: ~1.5 GB for `distil-large-v3`, during which
the container is legitimately unhealthy. That is why its `start_period` is ten minutes.
Later starts find the model in the volume and come up immediately.

`STT_MODEL_TTL` is how long a model stays in VRAM after its last use, 300 seconds by
default. Set it to `-1` in `.env` to keep it resident — an idle pause then costs no
reload, at the price of holding the VRAM.

It needs Docker Compose v2+ and the NVIDIA Container Toolkit on the host.

```bash
cp .env.example .env     # then set BIND_ADDR
docker compose up -d
```

`BIND_ADDR` is the address the two services listen on: `127.0.0.1` when the nodes run on
the same machine, the server's VPN address when they do not, `0.0.0.0` to serve every
interface. Neither service authenticates, so `0.0.0.0` belongs on a trusted network
only. The default is `127.0.0.1`, so a missing `.env` fails closed.

Check they are up — on a first run, watch the model land in the volume before `speaches`
turns healthy:

```bash
docker compose ps
```

```bash
docker compose logs -f speaches
```

If `stt_node` still gets a 404 after that, ask the server what it actually has; an empty
`data` list means the preload did not happen:

```bash
curl -s http://10.8.0.1:8001/v1/models
```

```bash
curl -X POST http://10.8.0.1:8001/v1/models/Systran/faster-distil-whisper-large-v3
```

### n8n

n8n is where the assistant will eventually trigger things — a spoken request reaching a
webhook instead of just an answer. **No ROS node calls it yet**: the container is here so
the workflows can be built before the ROS side exists.

Three things worth knowing:

- `N8N_SECURE_COOKIE=false` is set because n8n otherwise refuses the session cookie over
  plain HTTP from anything but localhost, which means no login over the VPN. Set it back
  to `true` the day n8n sits behind HTTPS.
- The `n8n-data` volume holds the SQLite database *and* the encryption key n8n generates
  on first start to encrypt stored credentials. Losing that volume makes the credentials
  in every workflow unreadable, so it is the one to back up.
- n8n has required a login since 1.0 and offers no supported way to disable it. The
  owner account is local to the container — no n8n.io account, and with no SMTP
  configured it sends no mail, so the address is just an identifier. That also means
  **there is no password reset**: keep it in a password manager.

The account can be declared up front rather than created through the signup form, which
is what the `N8N_OWNER_*` entries in `.env.example` are for. It is opt-in
(`N8N_OWNER_MANAGED=false` by default), it still produces a login, and it only applies
to an instance that has no owner yet. The password goes in as a bcrypt hash, with its
dollar signs doubled so Compose does not read them as variables.

#### Seeded workflows and credentials

A fresh n8n otherwise comes up empty. The `n8n/` directory in this repository holds what
it should start with, and the one-shot `n8n-init` container loads it on every
`docker compose up`:

```
n8n/
├── bootstrap.sh                   # runs inside the n8n image
├── credentials/ollama.json        # the Ollama connection the nodes use
└── workflows/basic-workflow.json  # POST /webhook/llm -> AI Agent -> Ollama
```

`N8N_OLLAMA_URL` and `N8N_OLLAMA_MODEL` from `.env` are substituted into those files
before import, so the same JSON works on any host. The URL defaults to
`http://host.docker.internal:11434`, which the `extra_hosts` entry on the n8n service
makes resolvable; point it at the VPN address instead when Ollama does not listen on the
Docker bridge. Credential data is written in clear in the repository and encrypted by n8n
on import, so put nothing secret there — the Ollama connection has no key.

A workflow whose JSON says `"active": true` is also published, which is a two-step dance
worth knowing about: `import:workflow` always lands workflows deactivated (its
`--activeState=fromJson` flag is refused outside queue mode), so `bootstrap.sh` calls
`publish:workflow` afterwards. The running server applies that within about 15 seconds,
so the webhook answers shortly after `up` returns, not instantly. Re-running also
deactivates and republishes, so the endpoint blinks for a moment on every `up`.

Two consequences:

- **The repository wins.** Workflows are matched on their fixed `id` and overwritten, so
  anything you change in the browser is undone by the next `up`. Export the workflow back
  into `n8n/workflows/` to keep it, or set `N8N_BOOTSTRAP=false` once the browser becomes
  the source of truth.
- **It needs an owner account to already exist**, because the import commands assign what
  they import to the instance owner and only `n8n start` ever creates one. That is why
  `n8n-init` waits for the server to be healthy rather than running before it. With
  `N8N_OWNER_MANAGED=false` and no account created by hand, the bootstrap fails with
  `Failed to find owner` and says what to do.

Once it is up, the seeded workflow answers on:

```bash
curl -N -X POST http://10.8.0.1:5678/webhook/llm -H 'Content-Type: application/json' -d '{"question": "whats the weather in paris today ?", "session_id": "ros-voice"}'
```

It streams back newline-delimited JSON. `session_id` is what the Simple Memory node keys
the conversation on; omit it and everything shares the `ros-voice` session. That memory
lives in the n8n process, not in the `n8n-data` volume, so it does not survive a restart.

Ollama is deliberately not in the stack — it is usually already installed on the machine
holding the GPU, and the pipeline only needs its HTTP endpoint.

## Build

```bash
cd ~/Documents/ROS
colcon build --symlink-install
source install/setup.bash
```

## Run

The whole pipeline at once, with `install/setup.bash` sourced:

```bash
ros2 launch voice_pipeline voice.launch.py
```

Or one node per terminal, which is easier to debug:

```bash
ros2 run voice_pipeline stt_node
```

```bash
ros2 run voice_pipeline llm_node
```

```bash
ros2 run voice_pipeline tts_node
```

Point the nodes at your own servers:

```bash
ros2 run voice_pipeline llm_node --ros-args -p n8n_url:=http://localhost:5678/webhook/llm -p session_id:=desk
```

```bash
ros2 run voice_pipeline stt_node --ros-args -p stt_url:=http://localhost:8001 -p language:=fr
```

```bash
ros2 run voice_pipeline tts_node --ros-args -p tts_url:=http://localhost:8880 -p voice:=af_heart
```

Watch the replies:

```bash
ros2 topic echo /llm_reply
```

Inject text without a microphone:

```bash
ros2 topic pub --once /user_text std_msgs/msg/String "data: 'whats the weather in paris today ?'"
```

Make it speak without the microphone or the LLM:

```bash
ros2 topic pub --once /llm_reply std_msgs/msg/String "data: 'Hello, the pipeline is working.'"
```

Interactive prompt and benchmark:

```bash
python3 src/voice_pipeline/ask.py
```

```bash
python3 src/voice_pipeline/bench.py
```

## Tests

Standard `ament` linters (flake8, pep257, mypy, xmllint, copyright):

```bash
colcon test --packages-select voice_pipeline && colcon test-result --verbose
```

## Roadmap

- [x] Text round trip through ROS (`echo_node`)
- [x] LLM node tuned for spoken-length answers
- [x] Streaming microphone capture with VAD-style segmentation and Whisper transcription
- [x] `tts_node`: speak `/llm_reply` out loud, streamed from Kokoro
- [x] Launch file to bring the whole pipeline up at once
- [ ] Have `stt_node` mute itself on `/tts_speaking`, so the assistant stops hearing itself
- [ ] Wake word / push-to-talk instead of always-on listening, which then becomes the
      conversation boundary in place of the silence timeout
- [ ] Barge-in: cut playback when the user starts talking
- [x] Route `llm_node` through an n8n AI Agent, which brings conversation memory
- [ ] Give that agent tools, so the assistant can act and not only answer
- [ ] Publish `/llm_reply` sentence by sentence as the agent streams, to start speaking
      sooner

## License

MIT
