# Contributing to M3allema

Thanks for helping. This guide covers setup and the standards every change meets.

## Setup

```bash
git clone https://github.com/BackendNeuron/m3allema
cd m3allema
uv sync
```

## Before you open a pull request

```bash
uv run ruff format .
uv run ruff check .
uv run mypy
uv run pytest
```

CI runs the same commands on every push and pull request.

## Standards

- **Layering.** `domain/` imports nothing from the rest of the package. The agent loop depends
  on the protocols in `agent/interfaces.py`, never on concrete adapters. New wiring goes in
  `runtime.py`. See [docs/architecture.md](docs/architecture.md).
- **Types.** `mypy --strict` must pass. Prefer frozen dataclasses for data.
- **Docstrings.** Every public module, class and function has one (Google style). Explain *why*
  where it isn't obvious; don't restate the code.
- **Tests.** New behaviour comes with tests. Use the fakes in `tests/fakes.py` instead of real
  network calls.
- **Safety.** Tools declare an honest risk level. Paths and URLs from the model are untrusted
  and must be validated. Never log or print secrets.
- **Commits.** Small and focused, with a message that says why.
