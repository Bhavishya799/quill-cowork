# Quill-Cowork AI Instructions

## Architecture Overview
- This is a hybrid Python/Rust application.
- Python (FastAPI) handles orchestration, UI, WebSockets, and LLM interaction.
- Rust (`quill_core`) handles heavy I/O, codebase indexing, filesystem sandboxing, and high-speed tool routing.
- DO NOT move routing logic to Python. If a tool needs to be routed, it MUST be added to `rust_core/src/main.rs` in the `cmd_route` function AND the Python fallback in `agent.py`.

## Safety & Constraints
- The app uses an abliterated (uncensored) 4B model. 
- Always enforce the 11-layer safety architecture.
- Any new tool MUST be registered in `tools/registry.py` with the `@tool` decorator.
- Destructive tools must have `destructive=True` in the decorator.
- Never bypass `network.check_egress` for any external HTTP requests.
- If modifying `vault.py` or `memory.py`, ensure AES-256-GCM encryption remains intact.

## Rust FFI Rules
- The Rust binary is built from `rust_core/src/main.rs` via `quill_rust.py`.
- When adding a new Rust command, you MUST:
  1. Add the subcommand to the `Cmd` enum in `main.rs`.
  2. Implement the logic in a `cmd_*` function.
  3. Map it in the `match cli.command` block.
  4. Add a corresponding `_wrap_*` function in `quill_rust.py` that calls the binary.
  5. Patch the relevant Python module to use the `_wrap_*` function.

## Coding Style
- Be concise. No emoji. No filler.
- Rust: Use `serde` for JSON serialization and `walkdir` for filesystem traversal.
- Python: Use `asyncio.to_thread` for blocking I/O to prevent freezing the event loop.