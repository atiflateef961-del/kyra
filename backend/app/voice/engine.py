from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from queue import Empty, Full, Queue
import logging
from threading import RLock
from threading import Thread
from typing import Any
from uuid import uuid4

from app.contracts.models import Intent, MicrophoneStatus, VoiceEvent
from app.intents.engine import IntentEngine
from app.intents.voice import VoiceIntentResolver
from app.voice.microphone import MicrophoneService
from app.voice.speech import SpeechProvider, Transcript, VoiceActivitySegmenter, VoiceCommandParser


class VoiceEngineUnavailable(RuntimeError):
    """Raised when local voice recognition cannot be explicitly started."""


VoiceEventHandler = Callable[[VoiceEvent], None]
IntentHandler = Callable[[Intent], None]
logger = logging.getLogger("kyra.voice")


class VoiceEngine:
    """Coordinates opt-in local capture and transcription without executing commands.

    Audio is handed directly from the microphone callback to the local speech
    provider. The engine retains neither audio nor transcript history. Parsed
    commands remain candidates for the intent layer; they are never actions.
    """

    def __init__(
        self,
        microphone: MicrophoneService,
        speech_provider: SpeechProvider,
        *,
        parser: VoiceCommandParser | None = None,
        intent_resolver: VoiceIntentResolver | None = None,
        intent_engine: IntentEngine | None = None,
        on_event: VoiceEventHandler | None = None,
        on_intent: IntentHandler | None = None,
    ) -> None:
        self._microphone = microphone
        self._speech_provider = speech_provider
        self._parser = parser or VoiceCommandParser()
        self._intent_engine = intent_engine or IntentEngine(
            parser=self._parser,
            voice_resolver=intent_resolver or VoiceIntentResolver(),
        )
        self._on_event = on_event
        self._on_intent = on_intent
        self._lock = RLock()
        self._audio_queue: Queue[Any] | None = None
        self._audio_worker: Thread | None = None

    def status(self) -> MicrophoneStatus:
        return self._microphone.status()

    @property
    def speech_available(self) -> bool:
        return self._speech_provider.available

    @property
    def speech_model_loaded(self) -> bool:
        return bool(getattr(self._speech_provider, "model_loaded", False))

    def probe(self) -> MicrophoneStatus:
        return self._microphone.probe()

    def start(self) -> MicrophoneStatus:
        """Start only after an explicit request and only with local STT available."""
        with self._lock:
            if self._microphone.status().active:
                return self._microphone.status()
            if not self._speech_provider.available:
                raise VoiceEngineUnavailable("Local speech-to-text is unavailable.")
            self._audio_queue = Queue(maxsize=64)
            self._audio_worker = Thread(
                target=self._run_audio_worker,
                args=(self._audio_queue,),
                name="kyra-voice-transcription",
                daemon=True,
            )
            self._audio_worker.start()
            try:
                status = self._microphone.start(self._enqueue_audio)
            except Exception as cause:
                self._queue_audio_stop()
                self._audio_worker.join(timeout=1)
                self._audio_worker = None
                self._audio_queue = None
                raise VoiceEngineUnavailable(str(cause)) from cause
            self._emit("started", message="Microphone capture is active.")
            return status

    def stop(self) -> MicrophoneStatus:
        with self._lock:
            was_active = self._microphone.status().active
            status = self._microphone.stop()
            worker = self._audio_worker
            if worker is not None:
                self._queue_audio_stop()
                worker.join(timeout=15)
                self._audio_worker = None
                self._audio_queue = None
            if was_active:
                self._emit("stopped", message="Microphone capture stopped.")
            return status

    def process_audio(self, audio: Any) -> Transcript | None:
        """Transcribe one in-memory buffer and publish a non-empty result.

        It is public so the audio boundary can be tested without a microphone.
        Provider errors are emitted locally, never raised from an audio callback.
        """
        try:
            transcript = self._speech_provider.transcribe(audio)
        except Exception:
            logger.exception("voice_transcription_failed")
            self._emit("error", message="Local speech recognition failed.")
            return None

        if not transcript.text.strip():
            self._emit("unrecognized", language=transcript.language, message="I didn't understand that. Please repeat the command.")
            return transcript
        if (
            transcript.confidence is not None and transcript.confidence < 0.35
        ) or (
            transcript.no_speech_probability is not None and transcript.no_speech_probability > 0.6
        ):
            self._emit(
                "unrecognized",
                transcript=transcript.text,
                language=transcript.language,
                confidence=transcript.confidence,
                message="I didn't understand that clearly. Please repeat the command.",
            )
            return transcript

        self._emit(
            "transcript",
            transcript=transcript.text,
            language=transcript.language,
            confidence=transcript.confidence,
        )
        try:
            # Resolving emits a validated candidate only; it performs no action.
            resolved = self._intent_engine.resolve_voice(transcript.text)
        except Exception:
            logger.exception("voice_intent_resolution_failed")
            self._emit("error", message="Command understanding failed.")
            return transcript
        if resolved.intent is None:
            self._emit(
                "unrecognized",
                transcript=transcript.text,
                language=transcript.language,
                confidence=transcript.confidence,
                message="I didn't understand that command. Please repeat it or try a supported command.",
            )
        elif self._on_intent is not None:
            self._emit("understanding", language=transcript.language, confidence=transcript.confidence)
            self._on_intent(resolved.intent)
        return transcript

    def _enqueue_audio(self, audio: Any) -> None:
        audio_queue = self._audio_queue
        if audio_queue is None:
            return
        try:
            audio_queue.put_nowait(audio)
        except Full:
            try:
                audio_queue.get_nowait()
            except Empty:
                pass
            try:
                audio_queue.put_nowait(audio)
            except Full:
                logger.warning("voice_audio_frame_dropped")
            else:
                logger.warning("voice_audio_frame_dropped")

    def _run_audio_worker(self, audio_queue: Queue[Any]) -> None:
        segmenter = VoiceActivitySegmenter()
        while True:
            frame = audio_queue.get()
            if frame is None:
                break
            segment = segmenter.add_frame(frame)
            if segment is not None:
                self._emit("processing", message="Speech detected. Transcribing locally.")
                self.process_audio(segment)
        final_segment = segmenter.finish()
        if final_segment is not None:
            self._emit("processing", message="Finishing local transcription.")
            self.process_audio(final_segment)

    def _queue_audio_stop(self) -> None:
        audio_queue = self._audio_queue
        if audio_queue is None:
            return
        try:
            audio_queue.put_nowait(None)
        except Full:
            try:
                audio_queue.get_nowait()
            except Empty:
                pass
            audio_queue.put_nowait(None)

    def _emit(
        self,
        phase: str,
        *,
        transcript: str | None = None,
        language: str | None = None,
        confidence: float | None = None,
        message: str | None = None,
    ) -> None:
        if self._on_event is None:
            return
        self._on_event(
            VoiceEvent(
                event_id=str(uuid4()),
                phase=phase,
                timestamp=datetime.now(UTC),
                transcript=transcript,
                language=language,
                confidence=confidence,
                message=message,
            )
        )
