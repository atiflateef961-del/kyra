from __future__ import annotations

from dataclasses import dataclass
import importlib
import math
from typing import Any, Protocol


class SpeechProviderUnavailable(RuntimeError):
    """Raised when local speech recognition is requested without its dependency."""


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None = None
    confidence: float | None = None
    no_speech_probability: float | None = None


class SpeechProvider(Protocol):
    @property
    def available(self) -> bool: ...
    def transcribe(self, audio: Any) -> Transcript: ...


def _load_faster_whisper() -> Any | None:
    try:
        return importlib.import_module("faster_whisper")
    except ImportError:
        return None


_AUTO_LOAD = object()


class FasterWhisperProvider:
    """Lazy multilingual local Faster-Whisper provider."""

    def __init__(self, model_size: str = "base", module: Any = _AUTO_LOAD) -> None:
        self._model_size = model_size
        self._module = _load_faster_whisper() if module is _AUTO_LOAD else module
        self._model: Any | None = None

    @property
    def available(self) -> bool:
        return self._module is not None

    @property
    def model_loaded(self) -> bool:
        return self._model is not None

    def transcribe(self, audio: Any) -> Transcript:
        if self._module is None:
            raise SpeechProviderUnavailable("faster-whisper is not installed; local speech-to-text is unavailable.")
        if isinstance(audio, list):
            numpy = importlib.import_module("numpy")
            audio = numpy.asarray(audio, dtype=numpy.float32)
        if self._model is None:
            self._model = self._module.WhisperModel(self._model_size)
        segments, info = self._model.transcribe(audio, vad_filter=True)
        segments = list(segments)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        log_probabilities = [
            float(segment.avg_logprob)
            for segment in segments
            if isinstance(getattr(segment, "avg_logprob", None), (int, float))
        ]
        confidence = (
            sum(math.exp(min(0.0, score)) for score in log_probabilities) / len(log_probabilities)
            if log_probabilities
            else None
        )
        no_speech_probabilities = [
            float(segment.no_speech_prob)
            for segment in segments
            if isinstance(getattr(segment, "no_speech_prob", None), (int, float))
        ]
        no_speech_probability = max(no_speech_probabilities) if no_speech_probabilities else None
        return Transcript(
            text=text,
            language=getattr(info, "language", None),
            confidence=confidence,
            no_speech_probability=no_speech_probability,
        )


@dataclass(frozen=True)
class ParsedVoiceCommand:
    transcript: str
    command_name: str | None


class VoiceCommandParser:
    """Small exact-phrase parser whose candidates are resolved locally to intents."""

    _COMMANDS = {
        "pause": "PAUSE",
        "pause video": "PAUSE",
        "pause the video": "PAUSE",
        "pause this video": "PAUSE",
        "please pause the video": "PAUSE",
        "play": "PLAY",
        "play video": "PLAY",
        "play the video": "PLAY",
        "open the next video": "NEXT_VIDEO",
        "go to the next video": "NEXT_VIDEO",
        "next video": "NEXT_VIDEO",
        "previous video": "PREVIOUS_VIDEO",
        "go to the previous video": "PREVIOUS_VIDEO",
        "turn volume up": "VOLUME_UP",
        "volume up": "VOLUME_UP",
        "turn the volume up": "VOLUME_UP",
        "turn volume down": "VOLUME_DOWN",
        "volume down": "VOLUME_DOWN",
        "turn the volume down": "VOLUME_DOWN",
        "scroll down": "SCROLL_DOWN",
        "scroll up": "SCROLL_UP",
        "open chrome": "OPEN_CHROME",
        "open powerpoint": "OPEN_POWERPOINT",
        "go back": "GO_BACK",
        "ruko": "PAUSE",
        "ruk jao": "PAUSE",
        "chalao": "PLAY",
        "phir se chalao": "PLAY",
        "agla video": "NEXT_VIDEO",
        "agli video": "NEXT_VIDEO",
        "volume barhao": "VOLUME_UP",
        "awaz barhao": "VOLUME_UP",
        "awaaz barhao": "VOLUME_UP",
        "volume kam karo": "VOLUME_DOWN",
        "awaz kam karo": "VOLUME_DOWN",
        "awaaz kam karo": "VOLUME_DOWN",
        "chrome kholo": "OPEN_CHROME",
        "powerpoint kholo": "OPEN_POWERPOINT",
        "agla video chalao": "NEXT_VIDEO",
        "neeche scroll karo": "SCROLL_DOWN",
        "upar scroll karo": "SCROLL_UP",
        "رک جاؤ": "PAUSE",
        "چلاؤ": "PLAY",
        "اگلی ویڈیو": "NEXT_VIDEO",
        "آواز بڑھاؤ": "VOLUME_UP",
        "آواز کم کرو": "VOLUME_DOWN",
        "کروم کھولو": "OPEN_CHROME",
        "پاورپوائنٹ کھولو": "OPEN_POWERPOINT",
        "نیچے سکرول کرو": "SCROLL_DOWN",
        "اوپر سکرول کرو": "SCROLL_UP",
    }

    def parse(self, transcript: Transcript) -> ParsedVoiceCommand:
        normalized = _normalize_voice_text(transcript.text)
        return ParsedVoiceCommand(transcript=transcript.text, command_name=self._COMMANDS.get(normalized))


def _normalize_voice_text(text: str) -> str:
    normalized = " ".join(text.casefold().strip().rstrip(".!?؟۔").split())
    return normalized.translate(str.maketrans({"ي": "ی", "ك": "ک"}))


class VoiceActivitySegmenter:
    """Build bounded utterances from microphone blocks using local RMS and silence."""

    sample_rate = 16_000
    threshold = 0.018
    silence_samples = int(sample_rate * 0.65)
    minimum_samples = int(sample_rate * 0.25)
    maximum_samples = int(sample_rate * 10)

    def __init__(self) -> None:
        self._samples: list[float] = []
        self._silence_count = 0
        self._active = False

    def add_frame(self, audio: Any) -> list[float] | None:
        if hasattr(audio, "reshape"):
            values = audio.reshape(-1).tolist()
        elif isinstance(audio, (list, tuple)):
            values = list(audio)
        else:
            return None
        samples = [float(value) for value in values]
        if not samples:
            return None
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
        if rms >= self.threshold:
            self._active = True
            self._silence_count = 0
        elif self._active:
            self._silence_count += len(samples)
        if self._active:
            self._samples.extend(samples)
        if self._active and (
            self._silence_count >= self.silence_samples or len(self._samples) >= self.maximum_samples
        ):
            return self.finish()
        return None

    def finish(self) -> list[float] | None:
        samples = self._samples
        self._samples = []
        self._silence_count = 0
        self._active = False
        return samples if len(samples) >= self.minimum_samples else None
