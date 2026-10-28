"""The local web dashboard: a FastAPI app with a WebSocket for live runs."""

from m3allema.server.app import create_app

__all__ = ["create_app"]
