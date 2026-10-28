"""Voice input: engine selection, limits, and the dashboard's transcribe endpoint."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from m3allema.config.models import SpeechSettings
from m3allema.server import app as server_app
from m3allema.speech import (
    MAX_AUDIO_BYTES,
    GroqWhisper,
    LocalWhisper,
    SpeechError,
    Transcript,
    build_transcriber,
)
from m3allema.workspace.workspace import Workspace

TOKEN = "speech-token"  # noqa: S105 - test value, not a secret


class FakeTranscriber:
    def __init__(self) -> None:
        self.received: list[tuple[int, str]] = []

    async def transcribe(self, audio: bytes, filename: str) -> Transcript:
        self.received.append((len(audio), filename))
        return Transcript("ابعت الفاتورة لأحمد", "ar")


def test_engine_selection() -> None:
    assert build_transcriber(SpeechSettings(engine="off")) is None
    assert isinstance(build_transcriber(SpeechSettings()), LocalWhisper)
    assert isinstance(build_transcriber(SpeechSettings(engine="groq", api_key="k")), GroqWhisper)
    with pytest.raises(SpeechError):
        build_transcriber(SpeechSettings(engine="groq"))


async def test_empty_and_oversized_audio_are_refused() -> None:
    engine = LocalWhisper()
    with pytest.raises(SpeechError):
        await engine.transcribe(b"", "voice.webm")
    with pytest.raises(SpeechError):
        await engine.transcribe(b"0" * (MAX_AUDIO_BYTES + 1), "voice.webm")


@pytest.mark.skipif(
    importlib.util.find_spec("faster_whisper") is not None, reason="voice extra installed"
)
async def test_missing_voice_extra_explains_how_to_install() -> None:
    with pytest.raises(SpeechError, match=r"m3allema\[voice\]"):
        await LocalWhisper().transcribe(b"audio", "voice.webm")


def test_transcribe_endpoint_returns_text_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Workspace.create(tmp_path)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=test\n", encoding="utf-8")
    fake = FakeTranscriber()
    monkeypatch.setattr(server_app, "build_transcriber", lambda _settings: fake)
    client = TestClient(server_app.create_app(tmp_path, TOKEN))

    assert client.post("/api/transcribe", content=b"x").status_code == 401
    response = client.post(
        "/api/transcribe",
        params={"token": TOKEN},
        content=b"fake-ogg",
        headers={"content-type": "audio/ogg; codecs=opus"},
    )
    assert response.status_code == 200
    assert response.json() == {"text": "ابعت الفاتورة لأحمد", "language": "ar"}
    assert fake.received == [(8, "voice.ogg")]


def test_transcribe_endpoint_when_voice_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Workspace.create(tmp_path)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=test\n", encoding="utf-8")
    monkeypatch.setattr(server_app, "build_transcriber", lambda _settings: None)
    client = TestClient(server_app.create_app(tmp_path, TOKEN))
    response = client.post("/api/transcribe", params={"token": TOKEN}, content=b"x")
    assert response.status_code == 503
