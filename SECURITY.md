# Security

## Scope

Quill-Cowork is designed as a local tool. It runs on your machine, talks
to your Ollama instance, and stores credentials in a local encrypted vault.
It is not designed to be exposed to the public internet.

## Exposing to the internet

If you run this behind a tunnel or reverse proxy:

1. Enable the built-in web auth. Generate a salted scrypt hash and store
   it in the vault:

       python -c "import sys; sys.path.insert(0,'backend'); from auth import hash_password; print(hash_password('YOUR-PW'))"
       python vault.py set QUILL_WEB_PASSWORD "<paste-output>" --sensitive

   With this key present, every HTTP route and the WebSocket require a
   valid session cookie. Without it, auth is disabled and requests are
   allowed from localhost only.

2. Disable destructive connectors in .env:

       DISABLED_CONNECTORS=gmail,github,codebase

3. Use Cloudflare Access (or equivalent) so the tunnel requires login.
4. Do not leave it running unattended.

## Credentials

All credentials live in vault.enc, encrypted with AES-256-GCM. The master
key is stored in your OS keyring. An optional vault passphrase adds a
second layer on top.

Never commit vault.enc, .env, or audit.log.jsonl.

## Reporting

Open an issue on GitHub. For sensitive reports, email the maintainer.

## Audio

Streaming speech recognition and text-to-speech run entirely on the
local machine.

- Recognition uses `faster-whisper`. The model is downloaded once
  from Hugging Face on first use and cached under
  `%USERPROFILE%\.cache\huggingface\hub`. After that, no network
  calls are made.
- Text-to-speech uses `pyttsx3`, which drives the OS voice engine
  (SAPI on Windows). No network.
- Audio bytes are streamed over the existing local WebSocket at
  `/ws/audio`. They are not logged or written to disk beyond the
  temporary file `faster-whisper` uses internally during decode.

The `/ws/audio` endpoint is origin-gated and shares the same auth
rules as the main `/ws` chat socket.

## Chat history

Every chat is persisted to `backend/workspace/.quill/chat.db`, a
SQLite database. It contains the raw text of every user prompt and
assistant reply in the session.

- The file lives under `workspace/`, which is gitignored.
- It is not encrypted at rest.
- Deleting a chat removes its rows immediately.
- If you handle sensitive prompts, delete the database manually:
  `del backend\workspace\.quill\chat.db`

Do not commit `chat.db`. It is not in the repo and should never be
added.
