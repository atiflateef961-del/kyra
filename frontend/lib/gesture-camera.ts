import { FilesetResolver, HandLandmarker } from "@mediapipe/tasks-vision";

import wasmLoader from "../../node_modules/@mediapipe/tasks-vision/wasm/vision_wasm_internal.js?url";
import wasmBinary from "../../node_modules/@mediapipe/tasks-vision/wasm/vision_wasm_internal.wasm?url";
import wasmNoSimdLoader from "../../node_modules/@mediapipe/tasks-vision/wasm/vision_wasm_nosimd_internal.js?url";
import wasmNoSimdBinary from "../../node_modules/@mediapipe/tasks-vision/wasm/vision_wasm_nosimd_internal.wasm?url";

export type HandPoint = { x: number; y: number };
export type GestureName = "SWIPE_RIGHT" | "SWIPE_LEFT" | "OPEN_PALM" | "THUMBS_UP" | "THUMBS_DOWN" | "INDEX_UP" | "INDEX_DOWN" | "TWO_FINGERS" | "VOLUME_UP" | "VOLUME_DOWN" | "SCROLL";
export type GestureDetection = { gesture: GestureName; confidence: number; direction?: "up" | "down" };

type FrameHandler = (hands: HandPoint[][], detection: GestureDetection | null) => void;

type TimedHand = { at: number; wrist: HandPoint; index: HandPoint };

class TemporalGestureRecognizer {
  private history: TimedHand[] = [];
  private candidate: GestureName | null = null;
  private candidateFrames = 0;
  private neutralFrames = 0;
  private locked = false;
  private lastEmission = 0;

  process(points: HandPoint[], now: number): GestureDetection | null {
    if (points.length !== 21) {
      this.history = [];
      return this.observe(null, 0, undefined);
    }

    this.history.push({ at: now, wrist: points[0], index: points[8] });
    this.history = this.history.filter((point) => now - point.at <= 700);

    let gesture: GestureName | null = null;
    let direction: "up" | "down" | undefined;
    let strength = 0;
    const first = this.history[0];
    const last = this.history[this.history.length - 1];
    const fingers = [8, 12, 16, 20].map((tip) => points[tip].y < points[tip - 2].y);
    const indexOnly = fingers[0] && !fingers[1] && !fingers[2] && !fingers[3];
    const twoFingers = fingers[0] && fingers[1] && !fingers[2] && !fingers[3];

    if (first && last && this.history.length >= 3) {
      const dx = last.wrist.x - first.wrist.x;
      const dy = last.index.y - first.index.y;
      if (Math.abs(dx) >= 0.18 && Math.abs(dx) >= Math.abs(dy) * 1.25) {
        gesture = dx > 0 ? "SWIPE_RIGHT" : "SWIPE_LEFT";
        strength = Math.abs(dx);
      } else if (Math.abs(dy) >= 0.16 && indexOnly) {
        gesture = dy < 0 ? "VOLUME_UP" : "VOLUME_DOWN";
        strength = Math.abs(dy);
      } else if (Math.abs(dy) >= 0.12 && twoFingers) {
        gesture = "SCROLL";
        direction = dy < 0 ? "up" : "down";
        strength = Math.abs(dy);
      }
    }

    if (!gesture) {
      const thumbRaised = points[4].y < points[3].y;
      const thumbLowered = points[4].y > points[3].y;
      const closedFist = !fingers.some(Boolean);
      if (thumbRaised && closedFist) gesture = "THUMBS_UP";
      else if (thumbLowered && closedFist) gesture = "THUMBS_DOWN";
      else if (indexOnly) gesture = "INDEX_UP";
      else if (!fingers[1] && !fingers[2] && !fingers[3] && points[8].y > points[6].y) gesture = "INDEX_DOWN";
      else if (twoFingers) gesture = "TWO_FINGERS";
      else if (thumbRaised && fingers.every(Boolean)) gesture = "OPEN_PALM";
    }

    const confidence = strength
      ? Math.min(0.99, 0.7 + Math.min(1, strength / 0.18) * 0.25)
      : 0.85;
    const detection = this.observe(gesture, confidence, direction);
    if (detection && (detection.gesture === "SWIPE_RIGHT" || detection.gesture === "SWIPE_LEFT")) {
      this.history = [{ at: now, wrist: points[0], index: points[8] }];
    }
    return detection;
  }

  reset() {
    this.history = [];
    this.candidate = null;
    this.candidateFrames = 0;
    this.neutralFrames = 0;
    this.locked = false;
    this.lastEmission = 0;
  }

  private observe(gesture: GestureName | null, confidence: number, direction?: "up" | "down"): GestureDetection | null {
    if (!gesture) {
      this.candidate = null;
      this.candidateFrames = 0;
      this.neutralFrames += 1;
      if (this.neutralFrames >= 4) this.locked = false;
      return null;
    }
    this.neutralFrames = 0;
    if (gesture === this.candidate) this.candidateFrames += 1;
    else {
      this.candidate = gesture;
      this.candidateFrames = 1;
    }
    if (this.locked || this.candidateFrames < 4 || performance.now() - this.lastEmission < 750) return null;
    this.lastEmission = performance.now();
    this.locked = true;
    return { gesture, confidence, ...(direction ? { direction } : {}) };
  }
}

export type GestureCameraSession = { stop: () => void };

function cameraError(cause: unknown): Error {
  if (!(cause instanceof DOMException)) return cause instanceof Error ? cause : new Error("The camera could not start.");
  if (cause.name === "NotAllowedError" || cause.name === "SecurityError") {
    return new Error("Camera permission was denied. Allow camera access for this KYRA site and try again.");
  }
  if (cause.name === "NotFoundError" || cause.name === "OverconstrainedError") {
    return new Error("No compatible camera was found. Connect a webcam or choose another camera.");
  }
  if (cause.name === "NotReadableError") return new Error("The camera is busy or unavailable. Close other apps using it and try again.");
  return new Error(`Camera could not start: ${cause.message}`);
}

async function createLandmarker(): Promise<HandLandmarker> {
  const simd = await FilesetResolver.isSimdSupported();
  const files = {
    wasmLoaderPath: simd ? wasmLoader : wasmNoSimdLoader,
    wasmBinaryPath: simd ? wasmBinary : wasmNoSimdBinary,
  } as Parameters<typeof HandLandmarker.createFromOptions>[0];
  return HandLandmarker.createFromOptions(files, {
    baseOptions: { modelAssetPath: `${import.meta.env.BASE_URL}models/hand_landmarker.task` },
    runningMode: "VIDEO",
    numHands: 2,
    minHandDetectionConfidence: 0.6,
    minHandPresenceConfidence: 0.55,
    minTrackingConfidence: 0.55,
  });
}

export async function startGestureCamera(video: HTMLVideoElement, onFrame: FrameHandler): Promise<GestureCameraSession> {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    throw new Error("Browser camera access requires a secure HTTPS site (localhost is allowed). Open KYRA using a trusted HTTPS address on the LAN.");
  }

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: "user",
        width: { ideal: 640 },
        height: { ideal: 480 },
        frameRate: { ideal: 24, max: 30 },
      },
    });
  } catch (cause) {
    throw cameraError(cause);
  }

  let landmarker: HandLandmarker | null = null;
  try {
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;
    await video.play();
    landmarker = await createLandmarker();
  } catch (cause) {
    stream.getTracks().forEach((track) => track.stop());
    video.srcObject = null;
    throw cause instanceof Error ? cause : new Error("The hand-landmark model could not start.");
  }

  let stopped = false;
  let animationFrame = 0;
  let lastVideoTime = -1;
  let lastInference = 0;
  const recognizer = new TemporalGestureRecognizer();
  const model = landmarker;

  const reportVisibility = () => {
    if (stopped) return;
    recognizer.reset();
    const hidden = document.visibilityState === "hidden";
    if (hidden) {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = 0;
    } else if (animationFrame === 0) {
      animationFrame = window.requestAnimationFrame(process);
    }
    window.dispatchEvent(new CustomEvent("kyra-camera-visibility", { detail: hidden }));
  };

  const failSession = (message: string) => {
    if (stopped) return;
    stopped = true;
    window.cancelAnimationFrame(animationFrame);
    document.removeEventListener("visibilitychange", reportVisibility);
    stream.getVideoTracks()[0]?.removeEventListener("ended", onTrackEnded);
    recognizer.reset();
    stream.getTracks().forEach((track) => track.stop());
    model.close();
    video.srcObject = null;
    window.dispatchEvent(new CustomEvent("kyra-camera-error", { detail: message }));
  };

  const onTrackEnded = () => failSession("The camera stream ended. Reconnect the camera and try again.");

  const process = (now: number) => {
    if (stopped) return;
    if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && video.currentTime !== lastVideoTime && now - lastInference >= 66) {
      lastVideoTime = video.currentTime;
      lastInference = now;
      try {
        const result = model.detectForVideo(video, now);
        const hands = result.landmarks.map((hand) => hand.map((point) => ({ x: 1 - point.x, y: point.y })));
        const detection = hands.length ? recognizer.process(hands[0], now) : recognizer.process([], now);
        onFrame(hands, detection);
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error("Hand tracking stopped unexpectedly.");
        failSession(error.message);
        return;
      }
    }
    animationFrame = window.requestAnimationFrame(process);
  };
  document.addEventListener("visibilitychange", reportVisibility);
  stream.getVideoTracks()[0]?.addEventListener("ended", onTrackEnded, { once: true });
  reportVisibility();

  return {
    stop: () => {
      if (stopped) return;
      stopped = true;
      window.cancelAnimationFrame(animationFrame);
      document.removeEventListener("visibilitychange", reportVisibility);
      stream.getVideoTracks()[0]?.removeEventListener("ended", onTrackEnded);
      recognizer.reset();
      model.close();
      stream.getTracks().forEach((track) => track.stop());
      video.srcObject = null;
    },
  };
}
