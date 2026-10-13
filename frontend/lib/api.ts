import { getFirebaseAuth } from "./firebase";
import type { ActionResult, CommandRequest, CommandResponse, ConfirmRequest, DeviceRegistrationRequest, GestureMappingInput, IntentResolveRequest, UserSettingsUpdate } from "../types/contracts";
import { z } from "zod";

const identitySchema = z.object({
  firebase_uid: z.string(),
  email: z.string().nullable(),
  name: z.string().nullable(),
});

const contextSchema = z.object({
  application: z.string(),
  profile: z.string(),
  available: z.boolean(),
  label: z.string(),
});

const intentSchema = z.object({
  name: z.string(),
  application: z.string().nullable(),
  confidence: z.number().min(0).max(1),
  risk_level: z.enum(["low", "high"]),
});

const intentResolveResponseSchema = z.object({
  intent: intentSchema.nullable(),
  provider: z.string().nullable(),
});

const cameraStatusSchema = z.object({
  available: z.boolean().nullable(),
  active: z.boolean(),
  updated_at: z.string(),
  message: z.string().nullable(),
});

const microphoneStatusSchema = z.object({
  available: z.boolean().nullable(),
  active: z.boolean(),
  updated_at: z.string(),
  message: z.string().nullable(),
});

const gestureEventSchema = z.object({
  event_id: z.string(),
  gesture: z.string(),
  confidence: z.number().min(0).max(1),
  timestamp: z.string(),
  context: z.string().nullable(),
});

const agentHealthSchema = z.object({
  api: z.literal("online"),
  environment: z.string(),
  dry_run: z.boolean(),
  configured: z.object({
    firebase_admin: z.boolean(),
    mongodb: z.string(),
    groq: z.boolean(),
  }),
  ai: z.object({
    deterministic: z.boolean(),
    cloud_enabled: z.boolean(),
    local_enabled: z.boolean(),
  }),
  components: z.object({
    camera: cameraStatusSchema,
    vision: z.object({ available: z.boolean(), message: z.string() }),
    microphone: microphoneStatusSchema,
    speech_to_text: z.object({ available: z.boolean(), message: z.string() }),
  }),
});

const gestureFrameSchema = z.object({
  detections: z.array(gestureEventSchema),
  preview: z.string().nullable(),
  hands: z.array(z.array(z.object({ x: z.number(), y: z.number() }))),
});

const settingsSchema = z.object({
  firebase_uid: z.string().optional(),
  theme: z.string().nullable().optional(),
  camera_enabled: z.boolean().optional(),
  microphone_enabled: z.boolean().optional(),
  privacy_mode: z.boolean().optional(),
  ai_provider: z.string().nullable().optional(),
  created_at: z.string().optional(),
  updated_at: z.string().optional(),
});

const gestureMappingSchema = z.object({
  mapping_id: z.string(),
  gesture: z.string(),
  action: z.string(),
  application: z.string(),
  enabled: z.boolean(),
  updated_at: z.string(),
});

const deviceSchema = z.object({
  device_id: z.string(),
  display_name: z.string(),
  registered_at: z.string(),
  last_seen_at: z.string(),
});

const notificationSchema = z.object({
  notification_id: z.string(),
  title: z.string(),
  message: z.string(),
  severity: z.enum(["info", "warning", "critical"]),
  read: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
});

const activityLogSchema = z.object({
  activity_id: z.string(),
  timestamp: z.string(),
  input_type: z.string(),
  intent_name: z.string().nullable(),
  action_id: z.string().nullable(),
  result_status: z.enum(["planned", "pending_confirmation", "executing", "succeeded", "failed", "dry_run"]),
  risk_level: z.enum(["low", "high"]),
});

const actionSchema = z.object({
  action_id: z.string(),
  identifier: z.string(),
  risk_level: z.enum(["low", "high"]),
  requires_confirmation: z.boolean(),
  parameters: z.record(z.string(), z.unknown()),
});

const actionResultSchema = z.object({
  action_id: z.string(),
  status: z.enum(["planned", "pending_confirmation", "executing", "succeeded", "failed", "dry_run"]),
  completed_at: z.string(),
  message: z.string().nullable(),
});

const permissionSchema = z.object({
  permission_id: z.string(),
  action_identifier: z.string(),
  granted: z.boolean(),
  requires_confirmation: z.boolean(),
  updated_at: z.string(),
});

const commandResponseSchema = z.object({
  action: actionSchema.nullable(),
  result: actionResultSchema.nullable(),
});

function resolveAgentUrl(configuredUrl?: string): string {
  const page = typeof window === "undefined" ? null : window.location;
  const fallback = page?.protocol === "https:"
    ? `${page.protocol}//${page.hostname}:8000`
    : "http://localhost:8000";
  const url = new URL(configuredUrl || fallback);
  const isLoopback = (hostname: string) => hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";

  // On a LAN browser, localhost means that browser's device, not the KYRA host.
  if (page && !isLoopback(page.hostname) && isLoopback(url.hostname)) {
    url.hostname = page.hostname;
  }

  // An HTTPS page must never issue mixed-content HTTP requests.
  if (page?.protocol === "https:") {
    url.protocol = "https:";
  }

  return url.toString().replace(/\/$/, "");
}

export const agentUrl = import.meta.env.DEV
  ? (typeof window === "undefined" ? "http://localhost:5173" : window.location.origin)
  : resolveAgentUrl(import.meta.env.VITE_AGENT_URL);

export class KyraApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
    this.name = "KyraApiError";
  }
}

async function request<T>(path: string, schema: z.ZodType<T>, init: RequestInit = {}, authenticated = true): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  if (authenticated) {
    const user = getFirebaseAuth().currentUser;
    if (!user) throw new KyraApiError("Authentication is required.", 401, "AUTHENTICATION_REQUIRED");
    headers.set("Authorization", `Bearer ${await user.getIdToken()}`);
  }

  const response = await fetch(`${agentUrl}${path}`, { ...init, headers });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = z.object({ error: z.object({ code: z.string(), message: z.string() }) }).safeParse(payload);
    throw new KyraApiError(
      error.success ? error.data.error.message : "The local agent request failed.",
      response.status,
      error.success ? error.data.error.code : "REQUEST_FAILED",
    );
  }
  return schema.parse(payload);
}

export const kyraApi = {
  health: () => request("/api/health", agentHealthSchema, {}, false),
  me: () => request("/api/me", identitySchema),
  context: () => request("/api/context", contextSchema),
  resolveIntent: (body: IntentResolveRequest) =>
    request("/api/intents/resolve", intentResolveResponseSchema, { method: "POST", body: JSON.stringify(body) }),
  cameraStatus: () => request("/api/camera/status", cameraStatusSchema),
  probeCamera: () => request("/api/camera/probe", cameraStatusSchema, { method: "POST" }),
  startCamera: (targetProfile: "automatic" | "youtube" = "automatic") =>
    request("/api/camera/start", cameraStatusSchema, {
      method: "POST",
      body: JSON.stringify({ target_profile: targetProfile }),
    }),
  stopCamera: () => request("/api/camera/stop", cameraStatusSchema, { method: "POST" }),
  setCameraTarget: (targetProfile: "automatic" | "youtube") =>
    request("/api/camera/target", z.object({ target_profile: z.enum(["automatic", "youtube"]) }), {
      method: "PUT",
      body: JSON.stringify({ target_profile: targetProfile }),
    }),
  processGestureFrame: () => request("/api/gestures/process-frame", gestureFrameSchema, { method: "POST" }),
  voiceStatus: () => request("/api/voice/status", microphoneStatusSchema),
  probeVoice: () => request("/api/voice/probe", microphoneStatusSchema, { method: "POST" }),
  startVoice: () => request("/api/voice/start", microphoneStatusSchema, { method: "POST" }),
  stopVoice: () => request("/api/voice/stop", microphoneStatusSchema, { method: "POST" }),
  transcribeVoice: (audioPcmBase64: string) =>
    request("/api/voice/transcribe", z.object({ accepted: z.literal(true) }), {
      method: "POST",
      body: JSON.stringify({ audio_pcm_base64: audioPcmBase64, sample_rate: 16_000 }),
    }),
  getSettings: () => request("/api/settings", settingsSchema),
  updateSettings: (changes: UserSettingsUpdate) =>
    request("/api/settings", settingsSchema, { method: "PUT", body: JSON.stringify(changes) }),
  listGestureMappings: () => request("/api/gestures", z.array(gestureMappingSchema)),
  createGestureMapping: (mapping: GestureMappingInput) =>
    request("/api/gestures", gestureMappingSchema, { method: "POST", body: JSON.stringify(mapping) }),
  updateGestureMapping: (mappingId: string, mapping: GestureMappingInput) =>
    request(`/api/gestures/${encodeURIComponent(mappingId)}`, gestureMappingSchema, { method: "PUT", body: JSON.stringify(mapping) }),
  deleteGestureMapping: (mappingId: string) =>
    request(`/api/gestures/${encodeURIComponent(mappingId)}`, z.object({ deleted: z.literal(true) }), { method: "DELETE" }),
  listDevices: () => request("/api/devices", z.array(deviceSchema)),
  registerDevice: (device: DeviceRegistrationRequest) =>
    request("/api/devices", deviceSchema, { method: "POST", body: JSON.stringify(device) }),
  deleteDevice: (deviceId: string) =>
    request(`/api/devices/${encodeURIComponent(deviceId)}`, z.object({ deleted: z.literal(true) }), { method: "DELETE" }),
  listPermissions: () => request("/api/permissions", z.array(permissionSchema)),
  updatePermission: (actionIdentifier: string, changes: { granted?: boolean; requires_confirmation?: boolean }) =>
    request(`/api/permissions/${encodeURIComponent(actionIdentifier)}`, permissionSchema, { method: "PUT", body: JSON.stringify(changes) }),
  listNotifications: () => request("/api/notifications", z.array(notificationSchema)),
  dismissNotification: (notificationId: string) =>
    request(`/api/notifications/${encodeURIComponent(notificationId)}/dismiss`, z.object({ dismissed: z.literal(true) }), { method: "POST" }),
  markNotificationRead: (notificationId: string) =>
    request(`/api/notifications/${encodeURIComponent(notificationId)}/read`, z.object({ read: z.literal(true) }), { method: "POST" }),
  listActivity: () => request("/api/activity", z.object({ items: z.array(activityLogSchema), total: z.number(), offset: z.number(), limit: z.number() })),
  submitCommand: (command: CommandRequest) =>
    request<CommandResponse>("/api/commands", commandResponseSchema, { method: "POST", body: JSON.stringify(command) }),
  confirmAction: (confirmation: ConfirmRequest) =>
    request<ActionResult>("/api/actions/confirm", actionResultSchema, { method: "POST", body: JSON.stringify(confirmation) }),
};

export type KyraHealth = z.infer<typeof agentHealthSchema>;
export type KyraIdentity = z.infer<typeof identitySchema>;
export type KyraSettingsRecord = z.infer<typeof settingsSchema>;
export type KyraActionResult = ActionResult;
