# Security

## Scope

Quill-Cowork is designed as a local tool. It runs on your machine, talks
to your Ollama instance, and stores credentials in a local encrypted vault.
It is not designed to be exposed to the public internet.

## Exposing to the internet

If you run this behind a tunnel or reverse proxy:

1. Add authentication. There is no built-in auth.
2. Disable destructive connectors in .env:
       DISABLED_CONNECTORS=gmail,github,codebase
3. Use Cloudflare Access (or equivalent) so the tunnel requires login.
4. Do not leave it running unattended.

## Credentials

All credentials live in vault.enc, encrypted with AES-256-GCM. The master
key is stored in your OS keyring. An optional passphrase adds a second layer.

Never commit vault.enc, .env, or audit.log.jsonl.

## Reporting

Open an issue on GitHub. For sensitive reports, email the maintainer.
