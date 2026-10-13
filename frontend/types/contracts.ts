/**
 * Browser representation of backend/app/contracts/models.py.
 * Datetime values are ISO 8601 strings at the transport boundary.
 */

export type AgentState = "online" | "offline" | "idle" | "listening" | "thinking" | "executing" | "error";
export type RiskLevel = "low" | "high";
export type ActionStatus = "planned" | "pending_confirmation" | "executing" | "succeeded" | "failed" | "dry_run";

export interface AgentStatus {
  state: AgentState;
  dry_run: boolean;
  updated_at: string;
  message: string | null;
}

export interface CameraStatus {
  available: boolean | null;
  active: boolean;
  updated_at: string;
  message: string | null;
  diagnostic_code: string;
}

export interface MicrophoneStatus {
  available: boolean | null;
  active: boolean;
  updated_at: string;
  message: string | null;
  diagnostic_code: string;
  diagnostic_detail: string | null;
}

export interface AppContext {
  application: string;
  profile: string;
  available: boolean;
  label: string;
}

export interface GestureEvent {
  event_id: string;
  gesture: string;
  confidence: number;
  timestamp: string;
  context: string | null;
}

export interface VoiceEvent {
  event_id: string;
  phase: string;
  timestamp: string;
  transcript: string | null;
  language: string | null;
  confidence: number | null;
  message: string | null;
}

export interface Intent {
  name: string;
  application: string | null;
  confidence: number;
  risk_level: RiskLevel;
}

export type IntentSource = "voice" | "gesture";

export interface IntentResolveRequest {
  source: IntentSource;
  transcript?: string | null;
  gesture?: string | null;
  confidence?: number;
}

export interface IntentResolveResponse {
  intent: Intent | null;
  provider: string | null;
}

export interface Action {
  action_id: string;
  identifier: string;
  risk_level: RiskLevel;
  requires_confirmation: boolean;
  parameters: Record<string, unknown>;
}

export interface ActionResult {
  action_id: string;
  status: ActionStatus;
  completed_at: string;
  message: string | null;
}

export interface ActivityLog {
  activity_id: string;
  timestamp: string;
  input_type: string;
  intent_name: string | null;
  action_id: string | null;
  result_status: ActionStatus;
  risk_level: RiskLevel;
}

export interface Device {
  device_id: string;
  display_name: string;
  registered_at: string;
  last_seen_at: string;
}

export interface Notification {
  notification_id: string;
  title: string;
  message: string;
  severity: "info" | "warning" | "critical";
  read: boolean;
  created_at: string;
  updated_at: string;
}

export interface DeviceRegistrationRequest {
  device_id: string;
  display_name: string;
}

export interface UserSettings {
  theme: string | null;
  camera_enabled: boolean;
  microphone_enabled: boolean;
  privacy_mode: boolean;
  ai_provider: string | null;
}

export interface UserSettingsUpdate {
  theme?: string | null;
  camera_enabled?: boolean | null;
  microphone_enabled?: boolean | null;
  privacy_mode?: boolean | null;
  ai_provider?: string | null;
}

export interface GestureMapping {
  mapping_id: string;
  gesture: string;
  action: string;
  application: string;
  enabled: boolean;
  updated_at: string;
}

export interface GestureMappingInput {
  gesture: string;
  action: string;
  application: string;
  enabled: boolean;
}

export interface Permission {
  permission_id: string;
  action_identifier: string;
  granted: boolean;
  requires_confirmation: boolean;
  updated_at: string;
}

export interface PermissionUpdate {
  granted?: boolean;
  requires_confirmation?: boolean;
}

export interface CommandRequest {
  intent: Intent | null;
  identifier: string | null;
  parameters: Record<string, unknown>;
}

export interface ConfirmRequest {
  action_id: string;
  approved: boolean;
}

export interface CommandResponse {
  action: Action | null;
  result: ActionResult | null;
}
