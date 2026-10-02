# Quill-Cowork

A local-first agentic AI assistant. Runs entirely on consumer hardware.
No cloud. No accounts. Your files stay on your machine.

Uses Ollama for inference, FastAPI for the backend, and a single-file HTML
frontend. Wraps an abliterated 4B model in a layered safety architecture —
eleven layers enforced in code.

## ?? Safety notice

Quill-Cowork runs an abliterated (uncensored) language model with
filesystem, email, and GitHub access. It is designed for single-user,
trusted-machine use. Do not expose it to a shared network or the public
internet without enabling the built-in auth (see SECURITY.md). The model
will comply with requests that aligned models refuse. You are responsible
for what it does.

## Status

Early prototype. Functional end-to-end. Tool-selection accuracy is
tracked in `benchmarks.md`. The 100-case suite scores 82.2% (N=90, three
runs each) on the pre-rewrite router; the rewritten router is in place
and re-measurement is pending.

## Features

- 43 tools across 8 connectors: Filesystem, GitHub, Gmail, Web,
  Wikipedia, Search (Tavily), Folder Grants, Codebase
- Runs a 4B model on an 8 GB GPU, or CPU-only with the cpu-* slots
- Permission card before every destructive action
- Encrypted credential vault (AES-256-GCM, OS keychain-backed)
- Codebase indexing with search, grep, symbol lookup, read-all, and
  patch-based edits
- Secret detection: pasted API keys are stored in the vault, not the model
- Append-only audit log of every tool call, approval, and refusal

## Requirements

- Windows 10/11 (tested), macOS/Linux (untested)
- Python 3.11+
- Ollama running locally
- ~8 GB free disk
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

Variables in backend/.env:

- MODEL_* — model slots
- WORKSPACE_ROOT — filesystem sandbox root
- DISABLED_CONNECTORS — comma-separated connector ids to hide
- ALLOWED_DOMAINS — extra hosts for fetch_page
- MAX_TOOL_ITERATIONS — cap on tool-call rounds per turn (default 20)

Model slots in `backend/.env`. Each slot must point at an Ollama tag
whose manifest declares `tools` in its Capabilities. Verify with
`ollama show <tag>` before trusting a slot.

- MODEL_FAST — `huihui_ai/qwen2.5-abliterate:3b`
- MODEL_BALANCED — `quill` (built from `Modelfile`, agents-a1-4b base)
- MODEL_POWERFUL — `richardyoung/granite-4.2-8b-heretic` (capped at 8K ctx)
- MODEL_CPU_FAST — `quill-cpu-fast` (0.6B)
- MODEL_CPU_SMART — `quill-cpu-smart` (4B)

Swap any slot by editing the tag, then run
`ollama create <alias> -f <Modelfile>` for the `quill*` aliases.

Credentials go in the vault:

    python vault.py set GITHUB_PERSONAL_ACCESS_TOKEN ghp_xxx --sensitive

## Connectors

Filesystem (4), GitHub (9), Gmail (9), Web (1), Wikipedia (2),
Search/Tavily (1), Folder Grants (2), Codebase (15).

## Safety architecture

Eleven layers, all enforced in code. Layer L11 (auth) is only active
once a web password is set in the vault; see SECURITY.md.

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
- No chat persistence across reload.
- Windows-first. macOS/Linux untested.
- WebSocket connections are origin-gated when auth is disabled. Do not
  expose without a layer in front.

## License

MIT — see LICENSE.# test
# watcher test
