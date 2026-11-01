

https://github.com/user-attachments/assets/24f19adf-991f-48fa-bd47-f047dffd6274

# Quill-Cowork

A local-first, hybrid Python/Rust agentic AI assistant. Runs entirely on consumer hardware. 
No cloud. No accounts. Your files stay on your machine.

Uses Ollama for inference, FastAPI for the backend, a single-file HTML frontend, and a compiled 
Rust binary (`quill_core`) for high-performance file I/O, codebase indexing, and tool routing. 
Wraps an abliterated 4B model in a layered safety architecture -- eleven layers enforced in code.

## Safety notice

Quill-Cowork runs an abliterated (uncensored) language model with filesystem, email, and GitHub access. 
It is designed for single-user, trusted-machine use. Do not expose it to a shared network or the public 
internet without enabling the built-in auth (see SECURITY.md). The model will comply with requests that 
aligned models refuse. You are responsible for what it does.

## Status

Early prototype. Functional end-to-end. Tool-selection accuracy is tracked in `benchmarks.md`. 
The 90-case suite scores ~82.2% (N=90, three runs each). The rewritten router (now executing in Rust) 
is in place, and re-measurement is pending.

## Features

- **Hybrid Python/Rust Architecture:** Heavy I/O (codebase indexing, file search, grep, symbol extraction, 
  and the 50+ regex tool router) is offloaded to a compiled Rust binary (`quill_core`). This makes 
  message processing and file operations near-instant.
- **52 tools across 9 connectors:** Filesystem, GitHub, Gmail, Web, Wikipedia, Search (DuckDuckGo + Tavily), 
  Folder Grants, Codebase, Obsidian.
- **Hardware Optimized:** Runs a 4B model on an 8 GB GPU (e.g., AMD RX 7600, NVIDIA RTX 3060). 
  Supports 16K context windows on 8 GB cards via `OLLAMA_FLASH_ATTENTION` and `q8_0` KV cache quantization.
- **Batched Deep Search:** Reads top-ranked web pages and extracts grounded, verbatim quotes using batched 
  LLM calls per page. A strict substring check prevents hallucinations without sacrificing latency.
- **Parallel tool execution:** Independent non-destructive calls run concurrently (bounded by `MAX_PARALLEL_TOOLS`).
- **Permission card** before every destructive action.
- **Encrypted credential vault** (AES-256-GCM, OS keychain-backed).
- **Append-only audit log** of every tool call, approval, and refusal.
- **Streaming speech recognition** (Whisper via `faster-whisper`) and local TTS (`pyttsx3`).

## Requirements

- Windows 10/11 (tested), macOS/Linux (untested)
- Python 3.11+
- **Rust Toolchain** (cargo) and a C++ linker (MSVC or MinGW on Windows)
- Ollama running locally
- ~8 GB free disk (plus ~140 MB for the default Whisper `base` model)
- GPU with 8 GB VRAM recommended

## Quickstart

### 1. Install Prerequisites
Ensure you have Python 3.11+, Git, and the Rust toolchain installed. 
*Windows users:* Install Rust via [rustup.rs](https://rustup.rs) and ensure the **Visual Studio C++ Build Tools** are installed.

### 2. Setup Python Backend
```bash
git clone https://github.com/Bhavishya799/quill-cowork
cd quill-cowork/backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
