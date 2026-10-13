const TARGET_RATE = 16_000;
export type BrowserVoiceState = "disconnected" | "requesting_permission" | "ready" | "listening" | "processing" | "error";
export type BrowserVoiceSession = { stop: () => void };

function encodePcm16(samples: number[]): string {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);
  samples.forEach((sample, index) => {
    const clamped = Math.max(-1, Math.min(1, sample));
    view.setInt16(index * 2, Math.round(clamped * (clamped < 0 ? 32768 : 32767)), true);
  });
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length)));
  }
  return window.btoa(binary);
}

function resample(input: Float32Array, sourceRate: number): number[] {
  if (sourceRate === TARGET_RATE) return Array.from(input);
  const outputLength = Math.floor(input.length * TARGET_RATE / sourceRate);
  const output = new Array<number>(outputLength);
  for (let index = 0; index < outputLength; index += 1) {
    const sourcePosition = index * sourceRate / TARGET_RATE;
    const left = Math.floor(sourcePosition);
    const fraction = sourcePosition - left;
    const first = input[left] ?? 0;
    const second = input[Math.min(left + 1, input.length - 1)] ?? first;
    output[index] = first + (second - first) * fraction;
  }
  return output;
}

export function browserVoiceSupported(): boolean {
  return typeof window !== "undefined"
    && typeof window.AudioContext !== "undefined"
    && typeof window.AudioWorkletNode !== "undefined"
    && Boolean(navigator.mediaDevices?.getUserMedia);
}

export async function startBrowserVoice(
  onUtterance: (audioBase64: string) => void | Promise<void>,
  onError: (message: string) => void,
  onState?: (state: BrowserVoiceState) => void,
): Promise<BrowserVoiceSession> {
  onState?.("requesting_permission");
  if (!browserVoiceSupported()) {
    onState?.("error");
    throw new Error("This browser does not support microphone capture. Try the latest Chrome or Edge.");
  }
  if (!window.isSecureContext) {
    onState?.("error");
    throw new Error("Microphone access requires KYRA's trusted HTTPS address or localhost.");
  }

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: false,
    });
  } catch (cause) {
    if (cause instanceof DOMException && ["NotAllowedError", "SecurityError"].includes(cause.name)) {
      onState?.("error");
      throw new Error("Microphone permission was denied. Allow microphone access for this KYRA site, then try again.");
    }
    if (cause instanceof DOMException && cause.name === "NotFoundError") {
      onState?.("error");
      throw new Error("No microphone was found. Connect a microphone and try again.");
    }
    onState?.("error");
    throw cause instanceof Error ? cause : new Error("Browser microphone access could not start.");
  }
  onState?.("ready");
  let context: AudioContext | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let processor: AudioWorkletNode | null = null;
  let silentGain: GainNode | null = null;
  let stopped = false;
  let utteranceQueue = Promise.resolve();
  const audioTrack = stream.getAudioTracks()[0];

  const cleanup = (state: BrowserVoiceState = "disconnected") => {
    if (stopped) return;
    stopped = true;
    audioTrack?.removeEventListener("mute", onTrackMute);
    audioTrack?.removeEventListener("unmute", onTrackUnmute);
    audioTrack?.removeEventListener("ended", onTrackEnded);
    if (context) context.onstatechange = null;
    processor?.port.close();
    source?.disconnect();
    processor?.disconnect();
    silentGain?.disconnect();
    stream.getTracks().forEach((track) => track.stop());
    if (context) void context.close();
    onState?.(state);
  };

  const onTrackMute = () => onState?.("ready");
  const onTrackUnmute = () => onState?.("listening");
  const onTrackEnded = () => {
    cleanup("error");
    onError("The microphone stream ended. Reconnect the microphone and try again.");
  };

  try {
    if (!audioTrack || audioTrack.readyState === "ended") {
      throw new Error("The browser did not provide an active microphone track.");
    }
    // Use the device's native rate; not every browser/audio device can open a
    // context directly at 16 kHz. Audio is resampled before upload below.
    const audioContext = new AudioContext();
    context = audioContext;
    await audioContext.resume();
    await audioContext.audioWorklet.addModule(`${import.meta.env.BASE_URL}voice-capture-processor.js`);
    source = audioContext.createMediaStreamSource(stream);
    processor = new AudioWorkletNode(audioContext, "kyra-voice-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
    });
    processor.port.onmessage = (event: MessageEvent<Float32Array>) => {
      if (!stopped && event.data instanceof Float32Array) {
        const audio = encodePcm16(resample(event.data, audioContext.sampleRate));
        utteranceQueue = utteranceQueue
          .then(() => onUtterance(audio))
          .catch((cause: unknown) => {
            onError(cause instanceof Error ? cause.message : "Voice utterance processing failed.");
          });
      }
    };
    processor.onprocessorerror = () => {
      if (stopped) return;
      onError("Browser microphone processing stopped unexpectedly. Restart microphone access and try again.");
      cleanup("error");
    };
    silentGain = audioContext.createGain();
    silentGain.gain.value = 0;
    source.connect(processor);
    processor.connect(silentGain);
    silentGain.connect(context.destination);
    audioTrack.addEventListener("mute", onTrackMute);
    audioTrack.addEventListener("unmute", onTrackUnmute);
    audioTrack.addEventListener("ended", onTrackEnded, { once: true });
    context.onstatechange = () => {
      if (stopped) return;
      if (context?.state === "running" && audioTrack.readyState === "live" && !audioTrack.muted) onState?.("listening");
      else if (context?.state === "suspended") onState?.("ready");
      else if (context?.state === "closed") {
        cleanup("error");
        onError("The browser suspended microphone processing. Restart microphone access and try again.");
      }
    };
    onState?.(context.state === "running" && !audioTrack.muted ? "listening" : "ready");
  } catch (cause) {
    cleanup("error");
    if (cause instanceof DOMException && ["NotAllowedError", "SecurityError"].includes(cause.name)) {
      throw new Error("Microphone permission was denied. Allow microphone access for this KYRA site, then try again.");
    }
    const error = cause instanceof Error ? cause : new Error("Browser microphone capture could not start.");
    onError(error.message || "Browser microphone capture could not start. Check that a microphone is connected and available.");
    throw error;
  }

  return { stop: cleanup };
}
