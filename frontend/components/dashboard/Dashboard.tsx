import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";

import { useAuth } from "../auth/AuthProvider";
import { AccountPanel } from "./AccountPanel";
import { DevicePanel } from "./DevicePanel";
import { GestureStudio } from "./GestureStudio";
import { NotificationPanel } from "./NotificationPanel";
import { PermissionPanel } from "./PermissionPanel";
import { SettingsPanel, type SettingsDraft } from "./SettingsPanel";
import { VoiceControl, type VoiceHistoryItem } from "./VoiceControl";
import { HandAnalysis } from "./HandAnalysis";
import { Sidebar } from "./Sidebar";
import { PageTransition } from "../motion/PageTransition";
import { StateTransition } from "../motion/StateTransition";
import { AnimatedBorder } from "../ui/AnimatedBorder";
import { ConfirmActionDialog } from "../ui/ConfirmActionDialog";
import { GlassPanel } from "../ui/GlassPanel";
import { LiquidPanel } from "../ui/LiquidPanel";
import { NeumorphicButton } from "../ui/NeumorphicButton";
import { AmbientEnergy } from "../ui/AmbientEnergy";
import { kyraApi, type KyraHealth } from "../../lib/api";
import { KyraAgentSocket, type AgentEvent, type AgentSocketStatus } from "../../lib/websocket";
import { browserVoiceSupported, startBrowserVoice, type BrowserVoiceSession, type BrowserVoiceState } from "../../lib/browser-voice";
import type { Action, AgentStatus, GestureEvent, Intent } from "../../types/contracts";

type ActivityItem = {
  id: string;
  label: string;
  detail: string;
  timestamp: string;
  tone: "neutral" | "success" | "danger";
};

const unknown = "Not reported";
const microphoneStateLabel: Record<BrowserVoiceState, string> = {
  disconnected: "Disconnected",
  requesting_permission: "Requesting permission",
  ready: "Ready",
  listening: "Listening",
  processing: "Processing",
  error: "Error",
};
function timeLabel(timestamp: string) {
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(timestamp));
}

function errorMessage(cause: unknown, fallback: string) {
  return cause instanceof Error && cause.message.trim() ? cause.message : fallback;
}

function socketLabel(status: AgentSocketStatus) {
  return {
    idle: "Offline",
    connecting: "Connecting",
    open: "Live",
    reconnecting: "Reconnecting",
    authentication_error: "Authentication error",
    backend_error: "Backend error",
    network_error: "Network error",
    unauthenticated: "Sign in required",
    closed: "Offline",
  }[status];
}

function microphoneMotionState(state: BrowserVoiceState) {
  if (state === "listening") return "listening" as const;
  if (state === "processing") return "thinking" as const;
  if (state === "error") return "error" as const;
  if (state === "disconnected") return "offline" as const;
  return "active" as const;
}

export function Dashboard() {
  const { user } = useAuth();
  const [health, setHealth] = useState<KyraHealth | null>(null);
  const [browserVoiceActive, setBrowserVoiceActive] = useState(false);
  const [voiceSupported] = useState(browserVoiceSupported);
  const speechAvailable = health?.components.speech_to_text.available === true;
  const voiceAvailable = voiceSupported && speechAvailable;
  const [gestureTarget, setGestureTarget] = useState<"automatic" | "youtube">(() => {
    try {
      return window.localStorage.getItem("kyra.gestureTarget.v2") === "youtube" ? "youtube" : "automatic";
    } catch {
      return "automatic";
    }
  });
  const [context, setContext] = useState<{ label: string; profile: string } | null>(null);
  const [agent, setAgent] = useState<AgentStatus | null>(null);
  const [intent, setIntent] = useState<Intent | null>(null);
  const [voiceTranscript, setVoiceTranscript] = useState<string | null>(null);
  const [voicePhase, setVoicePhase] = useState<string | null>(null);
  const [microphoneUiState, setMicrophoneUiState] = useState<BrowserVoiceState>("disconnected");
  const [voiceLanguage, setVoiceLanguage] = useState<string | null>(null);
  const [voiceMessage, setVoiceMessage] = useState<string | null>(null);
  const [voiceHistory, setVoiceHistory] = useState<VoiceHistoryItem[]>([]);
  const [currentAction, setCurrentAction] = useState<Action | null>(null);
  const [latestGesture, setLatestGesture] = useState<GestureEvent | null>(null);
  const [actionReport, setActionReport] = useState<string | null>(null);
  const [cameraPreview, setCameraPreview] = useState<string | null>(null);
  const [handLandmarks, setHandLandmarks] = useState<Array<Array<{ x: number; y: number }>>>([]);
  const [browserCameraActive, setBrowserCameraActive] = useState(false);
  const browserVoiceRef = useRef<BrowserVoiceSession | null>(null);
  const microphoneStateRef = useRef<BrowserVoiceState>("disconnected");
  const microphoneReturnStateRef = useRef<BrowserVoiceState>("disconnected");
  const processingVoiceRef = useRef(false);
  const gestureTargetRef = useRef(gestureTarget);
  const socketRef = useRef<KyraAgentSocket | null>(null);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [socketStatus, setSocketStatus] = useState<AgentSocketStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [confirmingActionId, setConfirmingActionId] = useState<string | null>(null);
  const [busy, setBusy] = useState<"camera" | "microphone" | null>(null);
  const [settings, setSettings] = useState<SettingsDraft>({
    theme: "dark",
    camera_enabled: true,
    microphone_enabled: true,
    privacy_mode: true,
    ai_provider: "local",
  });
  const [savingSettings, setSavingSettings] = useState(false);

  const updateMicrophoneState = useCallback((state: BrowserVoiceState) => {
    microphoneStateRef.current = state;
    if (state !== "processing") microphoneReturnStateRef.current = state;
    setMicrophoneUiState(state);
  }, []);

  useEffect(() => {
    const preference = settings.theme ?? "dark";
    const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
    const applyTheme = () => {
      document.documentElement.dataset.theme = preference === "system"
        ? systemTheme.matches ? "dark" : "light"
        : preference === "light" ? "light" : "dark";
    };

    applyTheme();
    if (preference !== "system") return;

    systemTheme.addEventListener("change", applyTheme);
    return () => systemTheme.removeEventListener("change", applyTheme);
  }, [settings.theme]);

  useEffect(() => {
    let mounted = true;
    const loadState = async () => {
      const results = await Promise.allSettled([
        kyraApi.health(),
        kyraApi.context(),
        kyraApi.listActivity(),
        kyraApi.getSettings(),
      ]);
      if (!mounted) return;
      const [healthResult, contextResult, activityResult, settingsResult] = results;
      if (healthResult.status === "fulfilled") setHealth(healthResult.value);
      if (contextResult.status === "fulfilled") setContext(contextResult.value);
      if (activityResult.status === "fulfilled") {
        setActivity(activityResult.value.items.map((item) => ({
          id: item.activity_id,
          label: item.intent_name ?? item.action_id ?? item.input_type,
          detail: item.result_status === "dry_run" ? "Dry run · not executed" : item.result_status,
          timestamp: item.timestamp,
          tone: item.result_status === "failed" ? "danger" : item.result_status === "succeeded" ? "success" : "neutral",
        })));
      }
      if (settingsResult.status === "fulfilled") {
        setSettings({
          theme: settingsResult.value.theme ?? "dark",
          camera_enabled: settingsResult.value.camera_enabled ?? true,
          microphone_enabled: settingsResult.value.microphone_enabled ?? true,
          privacy_mode: settingsResult.value.privacy_mode ?? true,
          ai_provider: settingsResult.value.ai_provider ?? "local",
        });
      }
      const failures = results
        .filter((result): result is PromiseRejectedResult => result.status === "rejected")
        .map((result) => errorMessage(result.reason, "A local agent status request failed."));
      if (failures.length) setError([...new Set(failures)].join(" "));
    };
    void loadState();

    const socket = new KyraAgentSocket({
      onStatus: (status) => {
        if (!mounted) return;
        setSocketStatus(status);
        if (status === "open") {
          setError(null);
          void loadState();
        }
      },
      onError: (cause) => mounted && setError(cause.message),
      onEvent: (event) => {
        if (!mounted) return;
        handleAgentEvent(event, {
          setAgent,
          setContext,
          setIntent,
          setLatestGesture,
          setActionReport,
          setVoiceTranscript,
          setVoicePhase,
          setVoiceLanguage,
          setVoiceMessage,
          setVoiceHistory,
          setCurrentAction,
          setActivity,
        });
      },
    });
    socketRef.current = socket;
    socket.connect();

    return () => {
      mounted = false;
      socket.disconnect();
      socketRef.current = null;
      browserVoiceRef.current?.stop();
      browserVoiceRef.current = null;
    };
  }, [user]);

  useEffect(() => {
    gestureTargetRef.current = gestureTarget;
    try {
        window.localStorage.setItem("kyra.gestureTarget.v2", gestureTarget);
    } catch {
      // The selected gesture target remains available for the current session.
    }
  }, [gestureTarget]);

  useEffect(() => {
    if (!browserCameraActive) return;
    let cancelled = false;
    let timeout = 0;
    const updatePreview = async () => {
      try {
        const frame = await kyraApi.processGestureFrame();
        if (cancelled) return;
        setCameraPreview(frame.preview);
        setHandLandmarks(frame.hands);
      } catch (cause) {
        if (cancelled) return;
        setBrowserCameraActive(false);
        setHandLandmarks([]);
        setError(errorMessage(cause, "Background camera analysis stopped."));
      } finally {
        if (!cancelled) timeout = window.setTimeout(() => void updatePreview(), 120);
      }
    };
    void updatePreview();
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [browserCameraActive]);

  useEffect(() => {
    if (!browserCameraActive) return;
    void kyraApi.setCameraTarget(gestureTarget).catch((cause) => {
      setError(errorMessage(cause, "The gesture target could not be updated."));
    });
  }, [browserCameraActive, gestureTarget]);

  useEffect(() => {
    if (settings.microphone_enabled || !browserVoiceRef.current) return;
    browserVoiceRef.current.stop();
    browserVoiceRef.current = null;
    setBrowserVoiceActive(false);
    updateMicrophoneState("disconnected");
    setVoicePhase("idle");
    setVoiceMessage("Microphone access is disabled in KYRA settings.");
  }, [settings.microphone_enabled, updateMicrophoneState]);

  async function toggleCamera() {
    setBusy("camera");
    setError(null);
    try {
      if (browserCameraActive) {
        await kyraApi.stopCamera();
        setBrowserCameraActive(false);
        setCameraPreview(null);
        setHandLandmarks([]);
      } else {
        await kyraApi.startCamera(gestureTargetRef.current);
        setBrowserCameraActive(true);
      }
    } catch (cause) {
      setError(errorMessage(cause, "Camera could not be changed."));
    } finally {
      setBusy(null);
    }
  }

  async function submitVoiceAudio(audioPcmBase64: string) {
    if (processingVoiceRef.current) return;
    processingVoiceRef.current = true;
    updateMicrophoneState("processing");
    setVoicePhase("processing");
    setVoiceMessage("Transcribing locally on the KYRA agent…");
    try {
      await kyraApi.transcribeVoice(audioPcmBase64);
    } catch (cause) {
      setVoicePhase("error");
      setVoiceMessage(errorMessage(cause, "Kyra could not transcribe the microphone audio."));
    } finally {
      processingVoiceRef.current = false;
      updateMicrophoneState(microphoneReturnStateRef.current);
    }
  }

  async function toggleMicrophone() {
    setError(null);
    if (browserVoiceRef.current) {
      browserVoiceRef.current.stop();
      browserVoiceRef.current = null;
      setBrowserVoiceActive(false);
      updateMicrophoneState("disconnected");
      setVoicePhase("idle");
      setVoiceMessage("Browser microphone stopped.");
      return;
    }
    setBusy("microphone");
    try {
      browserVoiceRef.current = await startBrowserVoice(
        (audio) => submitVoiceAudio(audio),
        (message) => {
          browserVoiceRef.current?.stop();
          browserVoiceRef.current = null;
          setBrowserVoiceActive(false);
          updateMicrophoneState("error");
          setVoicePhase("error");
          setVoiceMessage(message);
        },
        updateMicrophoneState,
      );
      setBrowserVoiceActive(true);
      if (microphoneStateRef.current === "ready" || microphoneStateRef.current === "listening") {
        setVoicePhase("listening");
        setVoiceMessage("Microphone is active in this browser. Speech is sent over HTTPS for local transcription on the KYRA agent.");
      }
    } catch (cause) {
      updateMicrophoneState("error");
      setVoicePhase("error");
      setVoiceMessage(errorMessage(cause, "Browser microphone could not start."));
    } finally {
      setBusy(null);
    }
  }

  async function saveSettings() {
    setSavingSettings(true);
    setError(null);
    try {
      const saved = await kyraApi.updateSettings(settings);
      setSettings({
        theme: saved.theme ?? "dark",
        camera_enabled: saved.camera_enabled ?? true,
        microphone_enabled: saved.microphone_enabled ?? true,
        privacy_mode: saved.privacy_mode ?? true,
        ai_provider: saved.ai_provider ?? "local",
      });
    } catch (cause) {
      setError(errorMessage(cause, "Settings could not be saved."));
    } finally {
      setSavingSettings(false);
    }
  }

  async function confirmAction(approved: boolean) {
    if (!currentAction) return;
    const actionId = currentAction.action_id;
    setConfirmingActionId(actionId);
    setError(null);
    try {
      await kyraApi.confirmAction({ action_id: actionId, approved });
      setCurrentAction(null);
    } catch (cause) {
      setError(errorMessage(cause, "The action confirmation could not be completed."));
    } finally {
      setConfirmingActionId(null);
    }
  }

  return (
    <div className="kyra-app-shell">
      <AmbientEnergy connection={socketStatus} agentState={agent?.state ?? null} />
      <Sidebar status={socketStatus} />
      <PageTransition className="kyra-dashboard" aria-labelledby="dashboard-title">
      <header className="kyra-dashboard__header">
        <div>
          <p className="kyra-dashboard__eyebrow">Local intelligence console</p>
          <h1 id="dashboard-title">Kyra</h1>
          <p className="kyra-dashboard__subline">Observe, understand, act.</p>
        </div>
        <div className="kyra-dashboard__status" aria-live="polite">
          <span className={`kyra-dashboard__status-dot kyra-dashboard__status-dot--${socketStatus}`} aria-hidden="true" />
          <span>{socketLabel(socketStatus)}</span>
        </div>
      </header>

      <AnimatePresence initial={false}>
        {error ? <motion.p key={error} className="kyra-dashboard__error" role="status" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.18 }}>{error}</motion.p> : null}
      </AnimatePresence>

      <section className="kyra-dashboard__grid" aria-label="Agent overview">
        <LiquidPanel className={`kyra-dashboard__hero kyra-dashboard__hero--${agent?.state ?? socketStatus}`} accent="blue">
          <div className="kyra-dashboard__hero-copy">
            <p className="kyra-dashboard__eyebrow">AI core</p>
            <h2>{agent?.state ?? "Waiting for agent state"}</h2>
            <p>{agent?.message ?? "The local agent has not reported a current state."}</p>
          </div>
          <div className="kyra-dashboard__core-visual" aria-hidden="true">
            <span className="kyra-dashboard__core-orbit" />
            <span className="kyra-dashboard__core-orbit kyra-dashboard__core-orbit--inner" />
            <span className="kyra-dashboard__core-node" />
          </div>
          <div className="kyra-dashboard__hero-metrics">
            <span>{health?.dry_run === true ? "Dry run" : health?.dry_run === false ? "Live control" : unknown}</span>
            <span>{health?.environment ?? unknown}</span>
          </div>
        </LiquidPanel>

        <AnimatedBorder tone="aqua" className={`kyra-dashboard__sensor kyra-dashboard__sensor--camera${browserCameraActive ? " kyra-dashboard__sensor--active" : ""}`}>
          <div className="kyra-dashboard__sensor-content">
            <div className="kyra-dashboard__panel-heading">
              <div><p className="kyra-dashboard__eyebrow">Vision</p><h2>Camera</h2></div>
              <StateTransition className="kyra-dashboard__state" state={browserCameraActive ? "active" : "idle"}>
                {browserCameraActive ? "ACTIVE · LOCAL AGENT" : "OFF"}
              </StateTransition>
            </div>
            <p className="kyra-dashboard__reading">Local camera analysis continues when this page is in the background.</p>
            <label className="kyra-dashboard__target">
              <span>Gesture target</span>
              <select value={gestureTarget} onChange={(event) => setGestureTarget(event.target.value as "automatic" | "youtube")}>
                <option value="automatic">Active application</option>
                <option value="youtube">YouTube playback</option>
              </select>
            </label>
            <NeumorphicButton disabled={busy !== null} onClick={() => void toggleCamera()} size="sm" tone={browserCameraActive ? "danger" : "primary"}>
              {busy === "camera" ? "Updating..." : browserCameraActive ? "Stop camera" : "Start camera"}
            </NeumorphicButton>
          </div>
        </AnimatedBorder>

        <AnimatedBorder tone="green" className="kyra-dashboard__sensor">
          <div className="kyra-dashboard__sensor-content">
            <div className="kyra-dashboard__panel-heading">
              <div><p className="kyra-dashboard__eyebrow">Voice</p><h2>Microphone</h2></div>
              <StateTransition className="kyra-dashboard__state" state={voiceAvailable ? microphoneMotionState(microphoneUiState) : "error"}>
                {voiceAvailable ? microphoneStateLabel[microphoneUiState] : "Unavailable"}
              </StateTransition>
            </div>
            <p className="kyra-dashboard__reading">{voiceMessage ?? (!voiceSupported ? "Microphone capture requires a current Chrome or Edge browser." : health ? health.components.speech_to_text.message : "Waiting for local speech recognition status.")}</p>
            <NeumorphicButton disabled={busy !== null || !voiceAvailable || !settings.microphone_enabled} onClick={toggleMicrophone} size="sm" tone={browserVoiceActive ? "danger" : "primary"}>
              {busy === "microphone" ? "Starting..." : browserVoiceActive ? "Stop microphone" : "Start microphone"}
            </NeumorphicButton>
          </div>
        </AnimatedBorder>

        <GlassPanel className="kyra-dashboard__context" tone="strong">
          <div className="kyra-dashboard__panel-heading"><div><p className="kyra-dashboard__eyebrow">Context</p><h2>{context?.label ?? unknown}</h2></div><span className="kyra-dashboard__state">{context?.profile ?? "unknown"}</span></div>
          <p className="kyra-dashboard__reading">Current application profile for gesture meaning.</p>
        </GlassPanel>

        <HandAnalysis
          active={browserCameraActive}
          preview={cameraPreview}
          hands={handLandmarks}
          latestGesture={latestGesture}
          actionReport={actionReport}
        />

        <GlassPanel className="kyra-dashboard__intent" tone="muted">
          <p className="kyra-dashboard__eyebrow">Last intent</p>
          <h2>{intent?.name ?? "No intent reported"}</h2>
          <p className="kyra-dashboard__reading">{intent ? `${Math.round(intent.confidence * 100)}% confidence` : "Waiting for a validated intent."}</p>
        </GlassPanel>

        <GlassPanel className="kyra-dashboard__activity" tone="default">
          <div className="kyra-dashboard__panel-heading"><div><p className="kyra-dashboard__eyebrow">Activity</p><h2>Recent events</h2></div><span className="kyra-dashboard__state">{activity.length} reported</span></div>
          {activity.length === 0 ? <p className="kyra-dashboard__empty">No live events received.</p> : <motion.ul className="kyra-dashboard__activity-list" initial={false}>
            <AnimatePresence initial={false}>
              {activity.map((item) => <motion.li
                className={`kyra-dashboard__activity-item kyra-dashboard__activity-item--${item.tone}`}
                key={item.id}
                layout="position"
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, height: 0, marginBottom: 0, paddingTop: 0, paddingBottom: 0 }}
                transition={{ duration: 0.2, ease: "easeOut" }}
              ><span><strong>{item.label}</strong><small>{item.detail}</small></span><time dateTime={item.timestamp}>{timeLabel(item.timestamp)}</time></motion.li>)}
            </AnimatePresence>
          </motion.ul>}
        </GlassPanel>
      </section>
      <GestureStudio />
      <VoiceControl
        microphoneActive={browserVoiceActive}
        microphoneAvailable={voiceAvailable}
        microphoneEnabled={settings.microphone_enabled}
        transcript={voiceTranscript}
        phase={voicePhase}
        language={voiceLanguage}
        message={voiceMessage}
        intent={intent}
        history={voiceHistory}
        busy={busy === "microphone"}
        onToggle={toggleMicrophone}
      />
      <SettingsPanel settings={settings} saving={savingSettings} onChange={(changes) => setSettings((current) => ({ ...current, ...changes }))} onSave={() => void saveSettings()} />
      <AccountPanel />
      <DevicePanel />
      <NotificationPanel />
      <PermissionPanel />
      </PageTransition>
      <ConfirmActionDialog
        action={currentAction?.requires_confirmation ? currentAction : null}
        busy={confirmingActionId !== null}
        onApprove={() => void confirmAction(true)}
        onCancel={() => void confirmAction(false)}
      />
    </div>
  );
}

type EventHandlers = {
  setAgent: (value: AgentStatus) => void;
  setContext: (value: { label: string; profile: string }) => void;
  setIntent: (value: Intent) => void;
  setLatestGesture: (value: GestureEvent) => void;
  setActionReport: (value: string) => void;
  setVoiceTranscript: (value: string | null) => void;
  setVoicePhase: (value: string) => void;
  setVoiceLanguage: (value: string | null) => void;
  setVoiceMessage: (value: string | null) => void;
  setVoiceHistory: (value: (current: VoiceHistoryItem[]) => VoiceHistoryItem[]) => void;
  setCurrentAction: (value: Action | null) => void;
  setActivity: (value: (current: ActivityItem[]) => ActivityItem[]) => void;
};

function handleAgentEvent(event: AgentEvent, handlers: EventHandlers) {
  const timestamp = event.timestamp;
  const addActivity = (item: ActivityItem) => handlers.setActivity((current) => [item, ...current].slice(0, 6));
  switch (event.event_type) {
    case "agent_status":
    case "ai_thinking":
      handlers.setAgent(event.payload);
      return;
    case "microphone_status":
      return;
    case "gesture_detected":
      handlers.setLatestGesture(event.payload);
      handlers.setActionReport(`Hand sign recognized: ${event.payload.gesture.replace(/_/g, " ")}.`);
      handlers.setContext({ label: event.payload.context ?? unknown, profile: "live" });
      addActivity({ id: event.payload.event_id, label: event.payload.gesture, detail: "Gesture detected", timestamp, tone: "neutral" });
      return;
    case "intent_detected":
      handlers.setIntent(event.payload);
      handlers.setActionReport(`Intent understood: ${event.payload.name.replace(/_/g, " ")}.`);
      addActivity({ id: `intent-${timestamp}`, label: event.payload.name, detail: "Intent validated", timestamp, tone: "neutral" });
      return;
    case "action_requested":
    case "action_executing":
    case "confirmation_required":
      handlers.setCurrentAction(event.payload);
      handlers.setActionReport(`Kyra is handling ${event.payload.identifier.replace(/_/g, " ")}.`);
      addActivity({ id: event.payload.action_id, label: event.payload.identifier, detail: event.event_type.replace(/_/g, " "), timestamp, tone: "neutral" });
      return;
    case "action_completed":
      handlers.setCurrentAction(null);
      handlers.setActionReport(event.payload.message ?? `Action ${event.payload.status.replace(/_/g, " ")}.`);
      handlers.setActivity((current) => [{
        id: event.payload.action_id,
        label: current.find((item) => item.id === event.payload.action_id)?.label ?? event.payload.action_id,
        detail: event.payload.status === "dry_run" ? "Dry run · not executed" : event.payload.message ?? event.payload.status,
        timestamp,
        tone: event.payload.status === "succeeded" ? "success" as const : "neutral" as const,
      }, ...current.filter((item) => item.id !== event.payload.action_id)].slice(0, 6));
      return;
    case "action_failed":
      handlers.setCurrentAction(null);
      handlers.setActionReport(event.payload.message ?? "The action could not be completed.");
      handlers.setActivity((current) => [{
        id: event.payload.action_id,
        label: current.find((item) => item.id === event.payload.action_id)?.label ?? event.payload.action_id,
        detail: event.payload.message ?? "Action failed",
        timestamp,
        tone: "danger" as const,
      }, ...current.filter((item) => item.id !== event.payload.action_id)].slice(0, 6));
      return;
    case "voice_started":
      handlers.setVoicePhase(event.payload.phase);
      handlers.setVoiceLanguage(event.payload.language);
      handlers.setVoiceMessage(event.payload.message);
      if (event.payload.transcript) handlers.setVoiceTranscript(event.payload.transcript);
      return;
    case "voice_transcript":
      handlers.setVoicePhase(event.payload.phase);
      handlers.setVoiceLanguage(event.payload.language);
      handlers.setVoiceMessage(event.payload.message);
      if (event.payload.transcript !== null) handlers.setVoiceTranscript(event.payload.transcript);
      if (event.payload.transcript) handlers.setVoiceHistory((current) => [{ id: event.payload.event_id, transcript: event.payload.transcript!, timestamp }, ...current].slice(0, 8));
      addActivity({ id: event.payload.event_id, label: event.payload.transcript ?? event.payload.phase, detail: "Voice event", timestamp, tone: "neutral" });
      return;
  }
}
