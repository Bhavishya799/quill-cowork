# Quill-Cowork

A local-first agentic AI assistant. Runs entirely on consumer hardware.
No cloud. No accounts. Your files stay on your machine.

Uses Ollama for inference, FastAPI for the backend, and a single-file HTML
frontend. Wraps an abliterated 4B model in a layered safety architecture --
eleven layers enforced in code.

## Safety notice

Quill-Cowork runs an abliterated (uncensored) language model with
filesystem, email, and GitHub access. It is designed for single-user,
trusted-machine use. Do not expose it to a shared network or the public
internet without enabling the built-in auth (see SECURITY.md). The model
will comply with requests that aligned models refuse. You are responsible
for what it does.

## Status

Early prototype. Functional end-to-end. Tool-selection accuracy is
tracked in `benchmarks.md`. The 90-case suite scores 82.2% (N=90, three
runs each) on the pre-rewrite router; the rewritten router is in place
and re-measurement is pending.

## Features

- 52 tools across 9 connectors: Filesystem, GitHub, Gmail, Web,
  Wikipedia, Search (Tavily + optional SearxNG), Folder Grants, Codebase, Obsidian
- Runs a 4B model on an 8 GB GPU, or CPU-only with the cpu-* slots
- Parallel tool execution: independent non-destructive calls run
  concurrently (bounded by `MAX_PARALLEL_TOOLS`, default 4)
- Permission card before every destructive action
- Encrypted credential vault (AES-256-GCM, OS keychain-backed)
- Codebase indexing with search, grep, symbol lookup, read-all, and
  patch-based edits
- Local web search via SearxNG (optional; Tavily fallback)
- Secret detection: pasted API keys are stored in the vault, not the model
- Append-only audit log of every tool call, approval, and refusal
- Streaming speech recognition (Whisper via `faster-whisper`), with
  live partial transcripts and auto-stop on silence
- Local text-to-speech (pyttsx3 / OS voices) for assistant replies
- Persistent chat history in SQLite, restored across browser reloads

## Requirements

- Windows 10/11 (tested), macOS/Linux (untested)
- Python 3.11+
- Ollama running locally
- ~8 GB free disk (plus ~140 MB for the default Whisper `base` model)
- GPU with 8 GB VRAM recommended

## Quickstart

    git clone https://github.com/Bhavishya799/quill-cowork
    cd quill-cowork/backend
    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
    cp .env.example .env

    # Pull the models your slots reference:
    ollama pull huihui_ai/qwen2.5-abliterate:3b        # MODEL_FAST
    ollama pull richardyoung/granite-4.2-8b-heretic    # MODEL_POWERFUL

    # Build the slot aliases from the Modelfiles.
    # Each pulls its own base model on first run.
    ollama create quill           -f Modelfile
    ollama create quill-cpu-fast  -f Modelfile.cpu-fast
    ollama create quill-cpu-smart -f Modelfile.cpu-smart

    python main.py

Open http://localhost:8000

## Configuration

Variables in `backend/.env`:

- `MODEL_*` -- model slots
- `WORKSPACE_ROOT` -- filesystem sandbox root
- `DISABLED_CONNECTORS` -- comma-separated connector ids to hide
- `ALLOWED_DOMAINS` -- extra hosts for fetch_page
- `MAX_TOOL_ITERATIONS` -- cap on tool-call rounds per turn (default 20)
- `MAX_PARALLEL_TOOLS` -- cap on concurrent non-destructive tool calls
  per turn (default 4)
- `WHISPER_MODEL` -- `tiny` | `base` | `small` | `medium` | `large-v3`
  (default `base`)
- `WHISPER_DEVICE` -- `auto` | `cpu` | `cuda` (default `auto`)
- `WHISPER_COMPUTE` -- `int8` | `float16` | `float32` (default: `int8`
  on CPU, `float16` on CUDA)
- `TTS_RATE` -- speech rate for pyttsx3 (default 180)

Model slots:

- `MODEL_FAST` -- `qwen2.5:3b`
- `MODEL_BALANCED` -- `quill` (built from `Modelfile`, agents-a1-4b base)
- `MODEL_POWERFUL` -- `richardyoung/granite-4.2-8b-heretic` (capped at 8K ctx)
- `MODEL_CPU_FAST` -- `quill-cpu-fast` (0.6B)
- `MODEL_CPU_SMART` -- `quill-cpu-smart` (4B)

Swap any slot by editing the tag, then run
`ollama create <alias> -f <Modelfile>` for the `quill*` aliases.

Credentials go in the vault:

    python vault.py set GITHUB_PERSONAL_ACCESS_TOKEN ghp_xxx --sensitive

## Connectors

Filesystem (5), GitHub (9), Gmail (9), Web (1), Wikipedia (2),
Search/Tavily (1), Folder Grants (2), Codebase (15), Obsidian (8).

Total: 52 tools.

## Audio

Streaming speech recognition is available in the composer:

- Click the mic button to start recording. A level meter appears under
  the input and partial transcripts show in italics as you speak.
- Stop talking for ~1.6 seconds and the recording auto-finalizes.
  Click the mic again to stop early.
- The final transcript is inserted at the cursor position in the
  composer input.

Audio never leaves your machine. Recognition uses `faster-whisper`
with the model cached locally on first use. Text-to-speech uses the
OS voices via `pyttsx3`; on Windows that is Windows SAPI.

Endpoint summary:

- `GET /audio/status` -- reports whether STT and TTS are available
- `WS /ws/audio` -- streaming PCM in, partial and final transcripts out
- `POST /audio/speak` -- JSON `{ "text": "..." }` returns `audio/wav`

If `faster-whisper` or `pyttsx3` is not installed, only audio breaks.
The rest of the app runs normally.

## Chat history

Every chat is persisted to `backend/workspace/.quill/chat.db` (SQLite,
WAL mode). The sidebar lists prior chats, clicking one restores it, and
deleting a chat removes it from disk.

Conversation turns (`user` and `assistant`) are replayed into the
agent's in-memory session on load, so the model keeps context after a
browser reload. Tool-call history is not replayed.

`chat.db` is under `workspace/`, which is gitignored.

## Safety architecture

Eleven layers, all enforced in code. Layer L11 (auth) is only active
once a web password is set in the vault; see SECURITY.md.

- L1  Input filter
- L2  Tool allowlist
- L3  Filesystem sandbox
- L4  Confirmation gate
- L5  Output filter
- L6  Rate limiter
- L7  Audit log
- L8  Network egress allowlist
- L9  Prompt injection detector
- L10 Secret redaction
- L11 Auth (optional)

## Benchmarks

See `benchmarks.md` for methodology, per-category accuracy, latency
figures, and the safety filter's precision/recall.

## Known Limitations

- Tool-selection accuracy: see `benchmarks.md`. The codebase category
  was the weakest before the router rewrite.
- Safety filter is regex-based. It scores 100% recall on the ten-case
  v3 set; a determined attacker can still evade pattern matching.
- Model hallucinates tool success. The audit log is the source of truth.
- Codebase indexing is lexical, not semantic.
- Speech recognition re-transcribes the whole growing buffer for each
  partial. Beyond ~30 seconds of continuous speech, each partial gets
  slower; use the auto-stop to chunk long dictation.
- Windows-first. macOS/Linux untested.
- WebSocket connections are origin-gated when auth is disabled. Do not
  expose without a layer in front.

## License

MIT -- see LICENSE.
