import { getFirebaseAuth } from "./firebase";
import { agentUrl, kyraApi } from "./api";
import { z } from "zod";

export function agentWebSocketUrl(agentBaseUrl = agentUrl): string {
  const url = new URL("/ws/agent", agentBaseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

const timestamp = z.string();
const agentState = z.enum(["online", "offline", "idle", "listening", "thinking", "executing", "error"]);
const riskLevel = z.enum(["low", "high"]);
const actionStatus = z.enum(["planned", "pending_confirmation", "executing", "succeeded", "failed", "dry_run"]);

const agentStatus = z.object({ state: agentState, dry_run: z.boolean(), updated_at: timestamp, message: z.string().nullable() });
const cameraStatus = z.object({ available: z.boolean().nullable(), active: z.boolean(), updated_at: timestamp, message: z.string().nullable() });
const microphoneStatus = z.object({ available: z.boolean().nullable(), active: z.boolean(), updated_at: timestamp, message: z.string().nullable() });
const gestureEvent = z.object({ event_id: z.string(), gesture: z.string(), confidence: z.number().min(0).max(1), timestamp, context: z.string().nullable() });
const voiceEvent = z.object({
  event_id: z.string(),
  phase: z.string(),
  timestamp,
  transcript: z.string().nullable(),
  language: z.string().nullable(),
  confidence: z.number().min(0).max(1).nullable(),
  message: z.string().nullable(),
});
const intent = z.object({ name: z.string(), application: z.string().nullable(), confidence: z.number().min(0).max(1), risk_level: riskLevel });
const action = z.object({ action_id: z.string(), identifier: z.string(), risk_level: riskLevel, requires_confirmation: z.boolean(), parameters: z.record(z.string(), z.unknown()) });
const actionResult = z.object({ action_id: z.string(), status: actionStatus, completed_at: timestamp, message: z.string().nullable() });

const agentEventSchema = z.discriminatedUnion("event_type", [
  z.object({ event_type: z.literal("agent_status"), timestamp, payload: agentStatus }),
  z.object({ event_type: z.literal("camera_status"), timestamp, payload: cameraStatus }),
  z.object({ event_type: z.literal("microphone_status"), timestamp, payload: microphoneStatus }),
  z.object({ event_type: z.literal("gesture_detected"), timestamp, payload: gestureEvent }),
  z.object({ event_type: z.literal("voice_started"), timestamp, payload: voiceEvent }),
  z.object({ event_type: z.literal("voice_transcript"), timestamp, payload: voiceEvent }),
  z.object({ event_type: z.literal("intent_detected"), timestamp, payload: intent }),
  z.object({ event_type: z.literal("ai_thinking"), timestamp, payload: agentStatus }),
  z.object({ event_type: z.literal("action_requested"), timestamp, payload: action }),
  z.object({ event_type: z.literal("confirmation_required"), timestamp, payload: action }),
  z.object({ event_type: z.literal("action_executing"), timestamp, payload: action }),
  z.object({ event_type: z.literal("action_completed"), timestamp, payload: actionResult }),
  z.object({ event_type: z.literal("action_failed"), timestamp, payload: actionResult }),
]);

export type AgentEvent = z.infer<typeof agentEventSchema>;
export type AgentSocketStatus =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "authentication_error"
  | "backend_error"
  | "network_error"
  | "unauthenticated"
  | "closed";

type AgentSocketOptions = {
  onEvent: (event: AgentEvent) => void;
  onError?: (error: Error) => void;
  onStatus?: (status: AgentSocketStatus) => void;
  reconnectDelayMs?: number;
  heartbeatMs?: number;
};

export class KyraAgentSocket {
  private socket: WebSocket | null = null;
  private heartbeatTimer: number | undefined;
  private reconnectTimer: number | undefined;
  private stopped = true;
  private hasConnected = false;
  private authenticated = false;
  private reconnectAttempt = 0;
  private readonly reconnectDelayMs: number;
  private readonly heartbeatMs: number;

  constructor(private readonly options: AgentSocketOptions) {
    this.reconnectDelayMs = options.reconnectDelayMs ?? 1_000;
    this.heartbeatMs = options.heartbeatMs ?? 20_000;
  }

  connect() {
    this.stopped = false;
    this.hasConnected = false;
    void this.open();
  }

  disconnect() {
    this.stopped = true;
    this.authenticated = false;
    this.clearTimers();
    this.socket?.close(1000, "Client disconnected");
    this.socket = null;
    this.setStatus("closed");
  }

  private async open() {
    if (this.stopped || this.socket) return;
    this.setStatus(this.hasConnected ? "reconnecting" : "connecting");
    const websocketUrl = agentWebSocketUrl();
    const healthUrl = new URL("/api/health", agentUrl).toString();
    let authenticationAvailable = false;

    try {
      const user = getFirebaseAuth().currentUser;
      if (!user) {
        if (import.meta.env.DEV) {
          console.warn("[KYRA] WebSocket connection needs Firebase sign-in.", {
            frontendOrigin: window.location.origin,
            websocketUrl,
            healthUrl,
            authenticationAvailable: false,
          });
        }
        this.setStatus("unauthenticated");
        return;
      }
      authenticationAvailable = true;
      const token = await user.getIdToken();
      if (this.stopped) return;
      if (import.meta.env.DEV) {
        console.info("[KYRA] Connecting authenticated WebSocket.", {
          frontendOrigin: window.location.origin,
          websocketUrl,
          healthUrl,
          authenticationAvailable,
        });
      }
      const socket = new WebSocket(websocketUrl, ["bearer", token]);
      this.socket = socket;
      socket.onmessage = (message) => this.handleMessage(message.data);
      socket.onerror = () => {
        if (import.meta.env.DEV) {
          console.error("[KYRA] WebSocket transport error; browser details are in Network/Console diagnostics.", {
            frontendOrigin: window.location.origin,
            websocketUrl,
            healthUrl,
            authenticationAvailable,
          });
        }
        this.options.onError?.(new Error("The Kyra real-time connection failed. Check the browser Network panel for the WebSocket handshake result."));
      };
      socket.onclose = (event) => {
        this.clearHeartbeat();
        this.socket = null;
        if (import.meta.env.DEV) {
          console.warn("[KYRA] WebSocket closed.", {
            frontendOrigin: window.location.origin,
            websocketUrl,
            healthUrl,
            closeCode: event.code,
            closeReason: event.reason || null,
            wasClean: event.wasClean,
            authenticationAvailable,
          });
        }
        if (event.code === 1008) {
          this.setStatus("authentication_error");
          this.options.onError?.(new Error(event.reason || "The backend rejected the WebSocket token or frontend origin. Check the backend authentication logs."));
          return;
        }
        if (event.code === 1011) {
          this.setStatus("backend_error");
          this.options.onError?.(new Error(event.reason || "The backend could not initialize the authenticated WebSocket connection. Check backend logs and Firebase Admin configuration."));
          this.scheduleReconnect();
          return;
        }
        if (!this.stopped) {
          const normalClose = event.code === 1000;
          this.setStatus(normalClose ? "reconnecting" : "network_error");
          this.options.onError?.(new Error(normalClose
            ? "The WebSocket closed normally; KYRA will reconnect."
            : `The WebSocket connection closed (code ${event.code}${event.reason ? `: ${event.reason}` : ""}).`));
          if (event.code === 1006) {
            void kyraApi.health().then((health) => {
              if (import.meta.env.DEV) {
                console.info("[KYRA] Backend health check succeeded after WebSocket close.", {
                  frontendOrigin: window.location.origin,
                  healthUrl,
                  backendReachable: true,
                  dryRun: health.dry_run,
                });
              }
              if (!this.stopped && !health.configured.firebase_admin) {
                this.setStatus("backend_error");
                this.options.onError?.(new Error("The backend is reachable, but Firebase Admin authentication is not configured. Set FIREBASE_PROJECT_ID, FIREBASE_CLIENT_EMAIL, and FIREBASE_PRIVATE_KEY in the backend environment."));
              } else if (!this.stopped) {
                this.options.onError?.(new Error(`The backend health endpoint is reachable at ${agentUrl}, but the WebSocket handshake closed without a browser-visible reason. Check the FastAPI WebSocket logs for Firebase token verification or frontend-origin rejection.`));
              }
            }).catch((cause: unknown) => {
              if (import.meta.env.DEV) {
                console.error("[KYRA] Backend health check failed after WebSocket close.", {
                  frontendOrigin: window.location.origin,
                  healthUrl,
                  protocol: new URL(healthUrl).protocol,
                  authenticationAvailable,
                  error: cause,
                });
              }
              if (!this.stopped) {
                const detail = cause instanceof Error ? cause.message : "unknown health check error";
                this.options.onError?.(new Error(`The browser could not read the health endpoint at ${agentUrl} after the WebSocket closed (${detail}). This can be caused by network reachability, CORS, or browser local-network access policy; the fetch failure alone does not prove that FastAPI is offline.`));
              }
            });
          }
          this.setStatus("reconnecting");
          this.scheduleReconnect();
        }
      };
    } catch (cause) {
      this.socket = null;
      const error = cause instanceof Error ? cause : new Error("The Kyra real-time connection could not start.");
      this.options.onError?.(error);
      this.setStatus("authentication_error");
    }
  }

  private handleMessage(raw: unknown) {
    if (typeof raw !== "string") return;
    let payload: unknown;
    try {
      payload = JSON.parse(raw);
    } catch {
      this.options.onError?.(new Error("The Kyra real-time connection sent invalid JSON."));
      return;
    }
    if (payload && typeof payload === "object" && "type" in payload) {
      if (payload.type === "auth_ok") {
        this.authenticated = true;
        this.hasConnected = true;
        this.reconnectAttempt = 0;
        this.setStatus("open");
        this.heartbeatTimer = window.setInterval(() => this.socket?.send(JSON.stringify({ type: "ping" })), this.heartbeatMs);
        return;
      }
      if (payload.type === "pong") return;
      if (payload.type === "gesture_rejected" || payload.type === "gesture_ignored") {
        const message = "message" in payload && typeof payload.message === "string" ? payload.message : "Gesture was not processed.";
        this.options.onError?.(new Error(message));
        return;
      }
    }
    const parsed = agentEventSchema.safeParse(payload);
    if (!parsed.success) {
      this.options.onError?.(new Error("The Kyra real-time connection sent an invalid event."));
      return;
    }
    this.options.onEvent(parsed.data);
  }

  private clearTimers() {
    this.clearHeartbeat();
    if (this.reconnectTimer !== undefined) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = undefined;
  }

  sendGesture(
    gesture: string,
    confidence: number,
    timestamp = Date.now(),
    targetProfile?: "youtube" | null,
    direction?: "up" | "down",
  ): boolean {
    if (!this.authenticated || this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify({
      type: "gesture",
      gesture,
      confidence,
      timestamp,
      ...(targetProfile ? { target_profile: targetProfile } : {}),
      ...(direction ? { direction } : {}),
    }));
    return true;
  }

  private scheduleReconnect() {
    if (this.stopped) return;
    const delay = Math.min(this.reconnectDelayMs * 2 ** this.reconnectAttempt, 30_000);
    this.reconnectAttempt += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = undefined;
      void this.open();
    }, delay);
  }

  private clearHeartbeat() {
    if (this.heartbeatTimer !== undefined) window.clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = undefined;
  }

  private setStatus(status: AgentSocketStatus) {
    this.options.onStatus?.(status);
  }
}
