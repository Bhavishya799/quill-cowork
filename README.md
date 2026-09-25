# Quill-Cowork

A local-first agentic AI assistant. Runs entirely on consumer hardware.
No cloud. No accounts. Your files stay on your machine.

Uses Ollama for inference, FastAPI for the backend, and a single-file HTML
frontend. Wraps an abliterated 4B model in a layered safety architecture —
eight layers enforced in code, two at the prompt level.

## ⚠️ Safety notice

Quill-Cowork runs an abliterated (uncensored) language model with
filesystem, email, and GitHub access. It is designed for single-user,
trusted-machine use. Do not expose it to a shared network or the public
internet without adding an authentication layer. The model will comply
with requests that aligned models refuse. You are responsible for what
it does.

## Status

Early prototype. Functional end-to-end. Tool-selection accuracy is 87.5%
(N=24), documented in the paper draft.

## Features

- 42 tools across 8 connectors: Filesystem, GitHub, Gmail, Web, Wikipedia,
  Search (Tavily), Folder Grants, Codebase
- Runs a 4B model on an 8 GB GPU, or CPU-only with the cpu-* slots
- Permission card before every destructive action
- Encrypted credential vault (AES-256-GCM, OS keychain-backed)
- Codebase indexing with search, grep, symbol lookup, and patch-based edits
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
    ollama pull qwen2.5:3b
    ollama create quill -f Modelfile
    python main.py

Open http://localhost:8000

## Configuration

Variables in backend/.env:

- MODEL_* — model slots
- WORKSPACE_ROOT — filesystem sandbox root
- DISABLED_CONNECTORS — comma-separated connector ids to hide
- ALLOWED_DOMAINS — extra hosts for fetch_page

Credentials go in the vault:

    python vault.py set GITHUB_PERSONAL_ACCESS_TOKEN ghp_xxx --sensitive

## Connectors

Filesystem (4), GitHub (9), Gmail (9), Web (1), Wikipedia (2),
Search/Tavily (1), Folder Grants (2), Codebase (14).

## Safety architecture

Ten designed layers; eight enforced in code. L1 (input filter) and
L4 (confirmation gate) are prompt/callback-dependent.

## Known Limitations

- Tool-selection accuracy 87.5% at N=24. Codebase category at 33%.
- Regex input filter caps at 80% recall on a 20-prompt set.
- Model hallucinates tool success. Audit log is source of truth.
- Codebase indexing is lexical, not semantic.
- No chat persistence across reload.
- Windows-first. macOS/Linux untested.
- No auth on WebSocket. Do not expose without a layer in front.

## License

MIT — see LICENSE.
