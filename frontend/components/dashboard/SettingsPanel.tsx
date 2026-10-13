import { NeumorphicButton } from "../ui/NeumorphicButton";
import { NeumorphicToggle } from "../ui/NeumorphicToggle";
import type { UserSettings } from "../../types/contracts";

export type SettingsDraft = Pick<UserSettings, "theme" | "camera_enabled" | "microphone_enabled" | "privacy_mode" | "ai_provider">;

type SettingsPanelProps = {
  settings: SettingsDraft;
  saving: boolean;
  onChange: (changes: Partial<SettingsDraft>) => void;
  onSave: () => void;
};

export function SettingsPanel({ settings, saving, onChange, onSave }: SettingsPanelProps) {
  return (
    <section className="kyra-settings-panel" aria-labelledby="settings-panel-title">
      <div className="kyra-dashboard__panel-heading">
        <div>
          <p className="kyra-dashboard__eyebrow">Preferences</p>
          <h2 id="settings-panel-title">Settings</h2>
        </div>
        <span className="kyra-dashboard__state">Saved</span>
      </div>

      <div className="kyra-settings-panel__grid">
        <label className="kyra-settings-panel__field" htmlFor="kyra-theme">
          <span>Theme</span>
          <select id="kyra-theme" value={settings.theme ?? "system"} onChange={(event) => onChange({ theme: event.target.value || null })}>
            <option value="system">System</option>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </select>
        </label>

        <label className="kyra-settings-panel__field" htmlFor="kyra-ai-provider">
          <span>AI provider</span>
          <select id="kyra-ai-provider" value={settings.ai_provider ?? "local"} onChange={(event) => onChange({ ai_provider: event.target.value || null })}>
            <option value="local">Local</option>
            <option value="groq">Groq</option>
            <option value="none">None</option>
          </select>
        </label>
      </div>

      <div className="kyra-settings-panel__toggles">
        <div className="kyra-settings-panel__toggle-row">
          <div>
            <strong>Camera enabled</strong>
            <small>Allow camera-based gesture capture.</small>
          </div>
          <NeumorphicToggle checked={settings.camera_enabled} label="Camera enabled" onCheckedChange={(checked) => onChange({ camera_enabled: checked })} />
        </div>
        <div className="kyra-settings-panel__toggle-row">
          <div>
            <strong>Microphone enabled</strong>
            <small>Enable spoken command capture.</small>
          </div>
          <NeumorphicToggle checked={settings.microphone_enabled} label="Microphone enabled" onCheckedChange={(checked) => onChange({ microphone_enabled: checked })} />
        </div>
        <div className="kyra-settings-panel__toggle-row">
          <div>
            <strong>Privacy mode</strong>
            <small>Minimize data retention and local exposure.</small>
          </div>
          <NeumorphicToggle checked={settings.privacy_mode} label="Privacy mode" onCheckedChange={(checked) => onChange({ privacy_mode: checked })} />
        </div>
      </div>

      <NeumorphicButton disabled={saving} onClick={onSave} size="sm" tone="primary">{saving ? "Saving..." : "Save settings"}</NeumorphicButton>
    </section>
  );
}
