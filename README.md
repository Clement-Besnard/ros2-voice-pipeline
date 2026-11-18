# voice_pipeline

A ROS 2 voice assistant pipeline: microphone → speech-to-text → LLM → spoken reply.

Audio is captured and segmented locally, transcription, generation and synthesis are
offloaded to self-hosted HTTP services (a Whisper server, [Ollama](https://ollama.com)
and a [Kokoro](https://github.com/remsky/Kokoro-FastAPI) server), and every stage talks
over plain ROS 2 topics so any node can be swapped or inspected on its own.

- ROS 2 **Lyrical** / Python 3.14, `ament_python` package built with `colcon`
- Workspace root with a single package: `src/voice_pipeline`
- The loop is closed end to end: it listens, answers and speaks

## Architecture

```
microphone ──► stt_node ──► /user_text ──► llm_node ──► /llm_reply ──► tts_node ──► speaker
                                            echo_node (uppercase stub, for testing)
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

**`llm_node`** — subscribes to `/user_text`, calls Ollama's `/api/generate`
(non-streaming, thinking disabled, model kept warm for 30 min) and publishes the answer
on `/llm_reply`. The system prompt constrains the model to two or three spoken sentences
with no markdown, lists or emoji — which cut a typical reply from ~1300 to ~50 tokens.

| Parameter       | Default                  | Description             |
| --------------- | ------------------------ | ----------------------- |
| `ollama_url`    | `http://10.8.0.1:11434`  | Ollama base URL         |
| `model`         | `qwen3:8b`               | Generation model        |
| `system_prompt` | see `llm_node.py`        | Voice-oriented prompt   |

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
  and the ROS overhead.

## Requirements

- ROS 2 Lyrical with `rclpy`, `std_msgs`, `launch` and `launch_ros`
- Python: `requests`, `numpy`, `sounddevice` (which needs PortAudio, e.g.
  `sudo apt install libportaudio2`)
- An [Ollama](https://ollama.com) server with the generation model pulled
  (`ollama pull qwen3:8b`)
- The speech services, which `docker-compose.yml` provides (see below): a Whisper
  server on `POST /v1/audio/transcriptions` and a
  [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) server on
  `POST /v1/audio/speech` with PCM streaming

All three services are reached over plain HTTP, so they can sit on the same machine as
the nodes or on a remote GPU box. The node defaults point at a private VPN address and
will need to be overridden for any other setup — see the `--ros-args` examples below.

## Supporting services

`docker-compose.yml` brings up three containers:

| Service    | Host port | What it serves                                     |
| ---------- | --------- | -------------------------------------------------- |
| `speaches` | `8001`    | Whisper, the `stt_url` the `stt_node` calls         |
| `kokoro`   | `8880`    | Kokoro, the `tts_url` the `tts_node` calls          |
| `n8n`      | `5678`    | automation editor and webhooks                      |

Speaches and Kokoro both run on the GPU. Image tags are pinned, and the Whisper model is
kept resident (`STT_MODEL_TTL=-1`) so an idle pause does not cost a model reload on the
next utterance.

It needs Docker Compose v2+ and the NVIDIA Container Toolkit on the host.

```bash
cp .env.example .env     # then set BIND_ADDR
docker compose up -d
```

`BIND_ADDR` is the address the two services listen on: `127.0.0.1` when the nodes run on
the same machine, the server's VPN address when they do not, `0.0.0.0` to serve every
interface. Neither service authenticates, so `0.0.0.0` belongs on a trusted network
only. The default is `127.0.0.1`, so a missing `.env` fails closed.

Check both are up, and that models persist in the `hf-hub-cache` volume between restarts:

```bash
docker compose ps
```

### n8n

n8n is where the assistant will eventually trigger things — a spoken request reaching a
webhook instead of just an answer. **No node calls it yet**: the container is here so the
workflows can be built before the ROS side exists. Open it on port `5678` and create the
owner account on first run.

Two things worth knowing:

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
ros2 run voice_pipeline llm_node --ros-args -p ollama_url:=http://localhost:11434 -p model:=qwen3:8b
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
- [x] LLM node on Ollama, tuned for spoken-length answers
- [x] Streaming microphone capture with VAD-style segmentation and Whisper transcription
- [x] `tts_node`: speak `/llm_reply` out loud, streamed from Kokoro
- [x] Launch file to bring the whole pipeline up at once
- [ ] Have `stt_node` mute itself on `/tts_speaking`, so the assistant stops hearing itself
- [ ] Wake word / push-to-talk instead of always-on listening
- [ ] Barge-in: cut playback when the user starts talking
- [ ] A node that fires n8n webhooks, so the assistant can act and not only answer

## License

MIT
