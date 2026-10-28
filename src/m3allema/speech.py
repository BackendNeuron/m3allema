"""Speech to text for voice input (dashboard microphone, Telegram voice notes).

Transcripts go back to the owner to review and edit; nothing in M3allema acts
on a transcript until the owner sends it. Engines:

* :class:`LocalWhisper` runs faster-whisper on this machine (``pip install
  "m3allema[voice]"``). The model loads on first use and stays in memory.
* :class:`GroqWhisper` uses Groq's OpenAI-compatible transcription API.
"""

from __future__ import annotations

import asyncio
import io
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from m3allema.config.models import SpeechSettings

MAX_AUDIO_BYTES = 20 * 1024 * 1024
"""About 20 minutes of compressed speech; longer recordings are refused."""

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "whisper-large-v3-turbo"


class SpeechError(Exception):
    """Transcription is unavailable or failed."""


@dataclass(frozen=True, slots=True)
class Transcript:
    """What was said, and the language the engine detected (when it reports one)."""

    text: str
    language: str = ""


class Transcriber(Protocol):
    """Turns recorded audio into text."""

    async def transcribe(self, audio: bytes, filename: str) -> Transcript:
        """Transcribe one recording; ``filename`` hints at the format (e.g. ``voice.ogg``)."""
        ...


class LocalWhisper:
    """faster-whisper on the CPU with int8 weights."""

    def __init__(self, model: str = "small", language: str = "auto") -> None:
        self._model_name = model
        self._language = None if language == "auto" else language
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise SpeechError(
                        'local voice input needs faster-whisper: pip install "m3allema[voice]"'
                    ) from exc
                self._model = WhisperModel(self._model_name, device="cpu", compute_type="int8")
            return self._model

    def _run(self, audio: bytes) -> Transcript:
        segments, info = self._load().transcribe(
            io.BytesIO(audio), language=self._language, vad_filter=True
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return Transcript(text, getattr(info, "language", "") or "")

    async def transcribe(self, audio: bytes, filename: str) -> Transcript:
        """Transcribe in a worker thread so the server stays responsive."""
        _check_size(audio)
        return await asyncio.to_thread(self._run, audio)


class GroqWhisper:
    """Groq's hosted Whisper through the OpenAI SDK."""

    def __init__(self, api_key: str, language: str = "auto") -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
        self._language = None if language == "auto" else language

    async def transcribe(self, audio: bytes, filename: str) -> Transcript:
        """Upload the recording and return Groq's transcript."""
        _check_size(audio)
        extra: dict[str, Any] = {"language": self._language} if self._language else {}
        try:
            result = await self._client.audio.transcriptions.create(
                model=GROQ_MODEL, file=(filename, audio), **extra
            )
        except Exception as exc:
            raise SpeechError(f"Groq transcription failed: {exc}") from exc
        return Transcript(result.text.strip())


def _check_size(audio: bytes) -> None:
    if not audio:
        raise SpeechError("the recording is empty")
    if len(audio) > MAX_AUDIO_BYTES:
        raise SpeechError("the recording is too long")


def build_transcriber(settings: SpeechSettings) -> Transcriber | None:
    """Create the configured engine, or ``None`` when voice input is off.

    Raises:
        SpeechError: ``groq`` is selected without an API key.

    """
    if settings.engine == "off":
        return None
    if settings.engine == "groq":
        if not settings.api_key:
            raise SpeechError("speech.engine is groq but speech.api_key is not set")
        return GroqWhisper(settings.api_key, settings.language)
    return LocalWhisper(settings.model, settings.language)
