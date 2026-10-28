# Security

M3allema acts on real email, files and calendars, so security reports are welcome and
taken seriously.

## Reporting a vulnerability

Please do **not** open a public issue. Use GitHub's private
[security advisory form](https://github.com/BackendNeuron/m3allema/security/advisories/new).
You will get a reply within a few days. Once a fix is released, you are credited in the
advisory unless you prefer not to be.

Especially interesting:

- Ways for content (an email, a web page, a file, an MCP tool description) to make
  M3allema act without the approval `policy.yaml` requires.
- Escaping the files folder or the shell sandbox.
- Reaching the dashboard, its WebSocket or the Telegram bot without the token or allowlist.
- Leaking API keys, OAuth tokens or `.env` contents.

## How M3allema protects you

- Permissions are enforced in code by `policy.yaml`, not by instructions to the model.
- Sending, inviting, deleting and every external MCP tool ask first by default. New memory
  and skills always ask, so injected text cannot plant lasting instructions.
- File tools are confined to `files/`; web fetches refuse private networks; the shell runs in
  a container with no network.
- The dashboard listens on `127.0.0.1`, needs a per-start token and refuses other origins.
- Secrets live in `.env`; Google tokens are encrypted at rest.

## Supported versions

Until 1.0, only the latest release receives security fixes.
