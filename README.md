# voice_pipeline

A ROS 2 voice assistant pipeline: microphone → speech-to-text → LLM → spoken reply.

Audio is captured and segmented locally, transcription and generation are offloaded to
self-hosted HTTP services (a Whisper server and [Ollama](https://ollama.com)), and every
stage talks over plain ROS 2 topics so any node can be swapped or inspected on its own.

- ROS 2 **Lyrical** / Python 3.14, `ament_python` package built with `colcon`
- Workspace root with a single package: `src/voice_pipeline`
- Text-to-speech is the next stage and is not implemented yet

## Architecture

```
microphone ──► stt_node ──► /user_text ──► llm_node ──► /llm_reply ──► (tts_node, planned)
                                            echo_node (uppercase stub, for testing)
```

| Topic        | Type                  | Published by          | Consumed by         |
| ------------ | --------------------- | --------------------- | ------------------- |
| `/user_text` | `std_msgs/msg/String` | `stt_node`            | `llm_node`          |
| `/llm_reply` | `std_msgs/msg/String` | `llm_node`            | TTS / any subscriber |

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

- ROS 2 Lyrical with `rclpy` and `std_msgs`
- Python: `requests`, `numpy`, `sounddevice` (which needs PortAudio, e.g.
  `sudo apt install libportaudio2`)
- An [Ollama](https://ollama.com) server with the generation model pulled
  (`ollama pull qwen3:8b`)
- A Whisper server exposing `POST /v1/audio/transcriptions` (e.g. Speaches /
  faster-whisper-server)

Both services are reached over HTTP, so they can run on the same machine
(`http://localhost:...`) or on a remote GPU box — the defaults above point to a host on
a private VPN and will need to be overridden.

## Build

```bash
cd ~/Documents/ROS
colcon build --symlink-install
source install/setup.bash
```

## Run

Each command goes in its own terminal, with `install/setup.bash` sourced.

```bash
ros2 run voice_pipeline stt_node
```

```bash
ros2 run voice_pipeline llm_node
```

Point the nodes at your own servers:

```bash
ros2 run voice_pipeline llm_node --ros-args -p ollama_url:=http://localhost:11434 -p model:=qwen3:8b
```

```bash
ros2 run voice_pipeline stt_node --ros-args -p stt_url:=http://localhost:8001 -p language:=fr
```

Watch the replies:

```bash
ros2 topic echo /llm_reply
```

Inject text without a microphone:

```bash
ros2 topic pub --once /user_text std_msgs/msg/String "data: 'whats the weather in paris today ?'"
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
- [ ] `tts_node`: speak `/llm_reply` out loud
- [ ] Launch file to bring the whole pipeline up at once
- [ ] Wake word / push-to-talk instead of always-on listening

## License

MIT
