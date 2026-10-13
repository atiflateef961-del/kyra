import base64
import builtins
import pytest
from types import SimpleNamespace
from threading import Event
from fastapi.testclient import TestClient

from app.actions.safety import ActionGuard
from app.auth.firebase import VerifiedIdentity
from app.computer.controller import ComputerController
from app.intents.engine import IntentEngine
from app.voice.microphone import MicrophoneService, MicrophoneUnavailable
from app.voice.engine import VoiceEngine, VoiceEngineUnavailable
from app.voice.speech import FasterWhisperProvider, SpeechProviderUnavailable, Transcript, VoiceActivitySegmenter, VoiceCommandParser
from app.core.config import Settings
from app.main import create_app


class FakeStream:
    def __init__(self, start_error: Exception | None = None, *, emit_on_start: bool = True) -> None:
        self.started = False
        self.stopped = False
        self.closed = False
        self.start_error = start_error
        self.emit_on_start = emit_on_start

    @property
    def active(self) -> bool:
        return self.started and not self.stopped

    def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.started = True
        if self.emit_on_start and hasattr(self, "callback"):
            self.callback([0.1] * 256, 256, None, None)

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True

    def emit(self, samples: list[float]) -> None:
        callback = getattr(self, "callback", None)
        if callback is not None:
            callback(samples, len(samples), None, None)


class FakeSoundDevice:
    def __init__(self, *, start_error: Exception | None = None, emit_on_start: bool = False) -> None:
        self.streams: list[FakeStream] = []
        self.start_error = start_error
        self.emit_on_start = emit_on_start

    @property
    def stream(self) -> FakeStream:
        return self.streams[-1]

    def query_devices(self, device: object, *, kind: str) -> dict[str, str]:
        assert kind == "input"
        return {"name": "test microphone"}

    def InputStream(self, **kwargs: object) -> FakeStream:
        assert kwargs["samplerate"] == 16_000
        self.streams.append(FakeStream(self.start_error, emit_on_start=self.emit_on_start))
        self.stream.callback = kwargs["callback"]
        return self.stream


class FakeSpeechProvider:
    available = True

    def __init__(self, transcript: Transcript = Transcript("pause")) -> None:
        self.transcript = transcript
        self.audio: object | None = None

    def transcribe(self, audio: object) -> Transcript:
        self.audio = audio
        return self.transcript


def test_microphone_is_opt_in_and_uses_explicit_test_stream() -> None:
    device = FakeSoundDevice(emit_on_start=True)
    service = MicrophoneService(sounddevice_module=device)

    assert service.status().active is False
    assert service.probe().available is True
    assert service.start().active is True
    assert service.stop().active is False
    assert device.stream.closed is True
    assert len(device.streams) == 2


def test_microphone_probe_opens_and_releases_the_capture_stream() -> None:
    device = FakeSoundDevice(emit_on_start=True)
    service = MicrophoneService(sounddevice_module=device)

    status = service.probe()

    assert status.available is True
    assert status.active is False
    assert device.stream.closed is True


def test_microphone_probe_requires_audio_callback_data_and_closes_stream() -> None:
    device = FakeSoundDevice(emit_on_start=False)
    service = MicrophoneService(sounddevice_module=device)

    status = service.probe()

    assert status.available is False
    assert status.active is False
    assert status.diagnostic_code == "no_data"
    assert "no audio samples" in status.message
    assert device.stream.closed is True


def test_microphone_probe_reports_a_device_that_cannot_open() -> None:
    device = FakeSoundDevice(start_error=RuntimeError("input host unavailable"))
    service = MicrophoneService(sounddevice_module=device)

    status = service.probe()

    assert status.available is False
    assert status.active is False
    assert status.diagnostic_code == "initialization_failed"
    assert status.diagnostic_detail == "RuntimeError"
    assert "RuntimeError" in status.message
    assert device.stream.closed is True


def test_microphone_diagnostic_preserves_portaudio_codes_without_raw_error_text() -> None:
    class PortAudioError(RuntimeError):
        pass

    cause = PortAudioError("Error opening InputStream: Unanticipated host error")
    cause.args = (cause.args[0], -9999, (0, 1, "external detail"))
    device = FakeSoundDevice(start_error=cause)
    status = MicrophoneService(sounddevice_module=device).probe()

    assert status.available is False
    assert status.diagnostic_code == "initialization_failed"
    assert status.diagnostic_detail == "PortAudioError; PortAudio -9999; host error 1"
    assert "external detail" not in status.message
    assert device.stream.closed is True


def test_microphone_status_reports_a_stream_that_stopped_unexpectedly() -> None:
    device = FakeSoundDevice()
    service = MicrophoneService(sounddevice_module=device)
    service.start()

    device.stream.stopped = True
    status = service.status()

    assert status.active is False
    assert status.available is False
    assert status.message == "Microphone capture stopped unexpectedly."
    service.stop()


def test_missing_microphone_and_speech_dependencies_are_reported() -> None:
    microphone = MicrophoneService(sounddevice_module=None)
    provider = FasterWhisperProvider(module=None)

    with pytest.raises(MicrophoneUnavailable, match="sounddevice is not installed"):
        microphone.start()
    with pytest.raises(SpeechProviderUnavailable, match="faster-whisper is not installed"):
        provider.transcribe(object())


def test_exact_voice_commands_are_parsed_without_executing_them() -> None:
    parser = VoiceCommandParser()

    assert parser.parse(Transcript("Open the next video.")).command_name == "NEXT_VIDEO"
    assert parser.parse(Transcript("pause the video")).command_name == "PAUSE"
    assert parser.parse(Transcript("please pause the video")).command_name == "PAUSE"
    assert parser.parse(Transcript("turn volume down")).command_name == "VOLUME_DOWN"
    assert parser.parse(Transcript("volume up")).command_name == "VOLUME_UP"
    assert parser.parse(Transcript("previous video")).command_name == "PREVIOUS_VIDEO"
    assert parser.parse(Transcript("go to the next video")).command_name == "NEXT_VIDEO"
    assert parser.parse(Transcript("write a shell command")).command_name is None


def test_voice_engine_is_opt_in_emits_lifecycle_and_keeps_audio_in_memory() -> None:
    events = []
    intents = []
    engine = VoiceEngine(
        MicrophoneService(sounddevice_module=FakeSoundDevice()),
        FakeSpeechProvider(),
        on_event=events.append,
        on_intent=intents.append,
    )

    assert engine.status().active is False
    assert engine.start().active is True
    assert engine.process_audio("audio-buffer") == Transcript("pause")
    assert engine.stop().active is False
    assert [(event.phase, event.transcript) for event in events] == [
        ("started", None),
        ("transcript", "pause"),
        ("understanding", None),
        ("stopped", None),
    ]
    assert intents[0].name == "PAUSE"


def test_voice_engine_requires_an_available_local_speech_provider() -> None:
    class UnavailableProvider:
        available = False

        def transcribe(self, audio: object) -> Transcript:
            raise AssertionError("unavailable provider must not transcribe")

    engine = VoiceEngine(MicrophoneService(sounddevice_module=FakeSoundDevice()), UnavailableProvider())

    with pytest.raises(VoiceEngineUnavailable, match="speech-to-text"):
        engine.start()


def test_voice_engine_stop_cleans_up_worker_after_unexpected_capture_stop() -> None:
    device = FakeSoundDevice()
    engine = VoiceEngine(MicrophoneService(sounddevice_module=device), FakeSpeechProvider())
    engine.start()
    worker = engine._audio_worker
    device.stream.stopped = True

    status = engine.stop()

    assert status.active is False
    assert worker is not None and not worker.is_alive()
    assert engine._audio_worker is None


def test_voice_parser_supports_urdu_and_roman_urdu_for_allowlisted_intents() -> None:
    parser = VoiceCommandParser()

    assert parser.parse(Transcript("آواز کم کرو")).command_name == "VOLUME_DOWN"
    assert parser.parse(Transcript("agla video")).command_name == "NEXT_VIDEO"
    assert parser.parse(Transcript("کروم کھولو۔")).command_name == "OPEN_CHROME"
    assert parser.parse(Transcript("shutdown the computer")).command_name is None


def test_voice_activity_segmenter_waits_for_speech_then_silence() -> None:
    segmenter = VoiceActivitySegmenter()

    assert segmenter.add_frame([0.001] * 1600) is None
    assert segmenter.add_frame([0.1] * 1600) is None
    completed = None
    for _ in range(7):
        completed = segmenter.add_frame([0.001] * 1600) or completed

    assert completed is not None
    assert len(completed) == 8 * 1600


def test_voice_engine_transcribes_buffered_microphone_utterances() -> None:
    device = FakeSoundDevice()
    transcribed = Event()

    class CapturingProvider:
        available = True
        audio: object | None = None

        def transcribe(self, audio: object) -> Transcript:
            self.audio = audio
            transcribed.set()
            return Transcript("pause")

    provider = CapturingProvider()
    engine = VoiceEngine(MicrophoneService(sounddevice_module=device), provider)
    engine.start()
    device.stream.emit([0.1] * 4800)
    for _ in range(7):
        device.stream.emit([0.001] * 1600)

    try:
        assert transcribed.wait(timeout=2)
        assert isinstance(provider.audio, list)
        assert len(provider.audio) == 10 * 1600
    finally:
        engine.stop()


def test_faster_whisper_uses_multilingual_model_and_returns_language_confidence() -> None:
    model_options: list[dict[str, object]] = []

    class FakeModel:
        def transcribe(self, audio: object, **kwargs: object):
            assert kwargs == {"vad_filter": True}
            return [SimpleNamespace(text=" Urdu speech", avg_logprob=-0.2, no_speech_prob=0.05)], SimpleNamespace(language="ur")

    class FakeWhisperModule:
        @staticmethod
        def WhisperModel(model_size: str) -> FakeModel:
            model_options.append({"model_size": model_size})
            return FakeModel()

    provider = FasterWhisperProvider(module=FakeWhisperModule)
    assert provider.available is True
    assert provider.model_loaded is False
    transcript = provider.transcribe([0.1] * 16000)

    assert model_options == [{"model_size": "base"}]
    assert transcript.text == "Urdu speech"
    assert transcript.language == "ur"
    assert transcript.confidence == pytest.approx(0.8187, rel=1e-3)
    assert transcript.no_speech_probability == 0.05
    assert provider.model_loaded is True


def test_low_confidence_transcript_is_not_resolved_as_an_action() -> None:
    events = []
    intents = []
    engine = VoiceEngine(
        MicrophoneService(sounddevice_module=FakeSoundDevice()),
        FakeSpeechProvider(Transcript("pause", confidence=0.2)),
        on_event=events.append,
        on_intent=intents.append,
    )

    engine.process_audio([0.1] * 16000)

    assert intents == []
    assert events[-1].phase == "unrecognized"
    assert events[-1].message == "I didn't understand that clearly. Please repeat the command."


def test_voice_routes_use_explicit_local_lifecycle() -> None:
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        microphone_service=MicrophoneService(sounddevice_module=FakeSoundDevice(emit_on_start=True)),
        speech_provider=FakeSpeechProvider(),
    )
    client = TestClient(app)

    assert client.post("/api/voice/probe").json()["available"] is True
    started = client.post("/api/voice/start")
    assert started.status_code == 200
    assert started.json()["active"] is True
    stopped = client.post("/api/voice/stop")
    assert stopped.status_code == 200
    assert stopped.json()["active"] is False


def test_browser_voice_audio_is_bounded_and_transcribed_in_memory() -> None:
    provider = FakeSpeechProvider(Transcript("pause the video", language="en"))
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        speech_provider=provider,
    )
    pcm = bytes(8_000)  # 0.25 seconds of mono PCM16 at 16 kHz.

    response = TestClient(app).post(
        "/api/voice/transcribe",
        json={"audio_pcm_base64": base64.b64encode(pcm).decode("ascii"), "sample_rate": 16_000},
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": True}
    assert provider.audio is not None
    assert len(provider.audio) == 4_000  # type: ignore[arg-type]


def test_browser_voice_transcription_failure_returns_an_error_not_accepted() -> None:
    class FailingProvider:
        available = True

        def transcribe(self, audio: object) -> Transcript:
            raise RuntimeError("model failure")

    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        speech_provider=FailingProvider(),
    )
    response = TestClient(app).post(
        "/api/voice/transcribe",
        json={"audio_pcm_base64": base64.b64encode(bytes(8_000)).decode("ascii"), "sample_rate": 16_000},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "TRANSCRIPTION_FAILED"


def test_browser_voice_reports_missing_numpy_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        speech_provider=FakeSpeechProvider(Transcript("pause", language="en")),
    )
    original_import = builtins.__import__

    def import_without_numpy(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("numpy is not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_numpy)
    response = TestClient(app).post(
        "/api/voice/transcribe",
        json={"audio_pcm_base64": base64.b64encode(bytes(8_000)).decode("ascii"), "sample_rate": 16_000},
    )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "VOICE_UNAVAILABLE",
        "message": "NumPy is unavailable; reinstall the backend voice dependencies.",
    }


@pytest.mark.parametrize(
    ("transcript", "intent_name", "executor_call"),
    (
        ("turn volume down", "VOLUME_DOWN", ("volume", -0.05)),
        ("volume up", "VOLUME_UP", ("volume", 0.05)),
        ("next video", "NEXT_YOUTUBE_VIDEO", ("combo", "176")),
        ("previous video", "PREVIOUS_YOUTUBE_VIDEO", ("combo", "177")),
        ("pause", "PAUSE", ("media", "pause")),
        ("play", "PLAY", ("media", "play")),
        ("scroll down", "SCROLL_DOWN", ("scroll", -120)),
        ("turn the volume down a little", "VOLUME_DOWN", ("volume", -0.05)),
    ),
)
def test_authenticated_browser_voice_reaches_intent_and_guarded_executor(
    transcript: str,
    intent_name: str,
    executor_call: tuple[str, int | float],
) -> None:
    class RecordingReasoner:
        available = True
        name = "groq"

        def __init__(self) -> None:
            self.transcripts: list[str] = []

        def complete(self, text: str) -> dict[str, str | None]:
            self.transcripts.append(text)
            return {"intent": "VOLUME_DOWN", "application": None}

    class RecordingExecutor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int | float | str]] = []

        def press_virtual_key(self, key_code: int) -> None:
            self.calls.append(("key", key_code))

        def control_media(self, action: str) -> None:
            self.calls.append(("media", action))

        def press_key_combo(self, key_codes: tuple[int, ...]) -> None:
            self.calls.append(("combo", ",".join(str(key) for key in key_codes)))

        def scroll(self, delta: int) -> None:
            self.calls.append(("scroll", delta))

        def adjust_volume(self, delta: float) -> tuple[float, float]:
            self.calls.append(("volume", delta))
            return 0.5, 0.5 + delta

        def launch(self, executable: str) -> None:
            self.calls.append(("launch", executable))

    executor = RecordingExecutor()
    reasoner = RecordingReasoner()
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=False),
        token_verifier=lambda token: VerifiedIdentity(firebase_uid=token, email=None, name=None),
        speech_provider=FakeSpeechProvider(Transcript(transcript, language="en")),
        intent_engine=IntentEngine(cloud_provider=reasoner, cloud_enabled=True),
        action_guard=ActionGuard(ComputerController(dry_run=False, executor=executor)),
    )
    client = TestClient(app)
    pcm = bytes(8_000)

    with client.websocket_connect("/ws/agent", subprotocols=["bearer", "test-user"]) as connection:
        assert connection.receive_json() == {"type": "auth_ok"}
        for _ in range(3):
            connection.receive_json()
        response = client.post(
            "/api/voice/transcribe",
            headers={"Authorization": "Bearer test-user"},
            json={"audio_pcm_base64": base64.b64encode(pcm).decode("ascii"), "sample_rate": 16_000},
        )
        assert response.status_code == 200
        received = []
        while not any(event["event_type"] == "action_completed" for event in received):
            received.append(connection.receive_json())

    assert any(event["event_type"] == "voice_transcript" and event["payload"]["transcript"] == transcript for event in received)
    assert any(event["event_type"] == "intent_detected" and event["payload"]["name"] == intent_name for event in received)
    assert received[-1]["payload"]["status"] == "succeeded"
    assert executor.calls == [executor_call]
    if transcript == "turn the volume down a little":
        assert reasoner.transcripts == [transcript]
    else:
        assert reasoner.transcripts == []
