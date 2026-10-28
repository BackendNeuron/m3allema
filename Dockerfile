# M3allema in a container: the dashboard and the Telegram bot.
#
#   docker compose up            # dashboard on http://127.0.0.1:8765 (link in the logs)
#
# The workspace (config, .env, files, database) lives in the ./workspace volume.

FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project --extra voice
COPY src ./src
RUN uv sync --locked --no-dev --extra voice

FROM python:3.12-slim-bookworm
RUN useradd --create-home --uid 1000 m3allema
COPY --from=build --chown=m3allema:m3allema /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/workspace/.m3allema/models
USER m3allema
WORKDIR /workspace
VOLUME ["/workspace"]
EXPOSE 8765
# Inside the container the server must listen on all interfaces; compose publishes the
# port on the host's 127.0.0.1 only.
CMD ["m3allema", "serve", "--host", "0.0.0.0", "--no-open"]
