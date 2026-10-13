import { useEffect, useState } from "react";

import { kyraApi } from "../../lib/api";
import type { GestureMapping, GestureMappingInput } from "../../types/contracts";
import { GlassPanel } from "../ui/GlassPanel";
import { NeumorphicButton } from "../ui/NeumorphicButton";
import { NeumorphicToggle } from "../ui/NeumorphicToggle";

const gestures = ["SWIPE_RIGHT", "SWIPE_LEFT", "OPEN_PALM", "FIST", "THUMBS_UP", "THUMBS_DOWN", "INDEX_UP", "INDEX_DOWN", "TWO_FINGERS", "VOLUME_UP", "VOLUME_DOWN", "SCROLL"];
const actions = ["NEXT_MEDIA", "PREVIOUS_MEDIA", "NEXT_YOUTUBE_VIDEO", "PREVIOUS_YOUTUBE_VIDEO", "PAUSE", "PLAY", "VOLUME_UP", "VOLUME_DOWN", "SCROLL_UP", "SCROLL_DOWN", "GO_BACK", "GO_FORWARD", "NEXT_SLIDE", "PREVIOUS_SLIDE"];
const profiles = ["youtube", "powerpoint", "browser", "generic"];
const blankMapping: GestureMappingInput = { gesture: "SWIPE_RIGHT", action: "NEXT_MEDIA", application: "youtube", enabled: true };

export function GestureStudio() {
  const [mappings, setMappings] = useState<GestureMapping[]>([]);
  const [draft, setDraft] = useState<GestureMappingInput>(blankMapping);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function loadMappings() {
    setLoading(true);
    try {
      setMappings(await kyraApi.listGestureMappings());
      setMessage(null);
    } catch {
      setMessage("Gesture mappings are unavailable until persistence is configured.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadMappings();
  }, []);

  async function createMapping() {
    setSaving(true);
    try {
      const created = await kyraApi.createGestureMapping(draft);
      setMappings((current) => [created, ...current]);
      setMessage("Mapping saved.");
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "The mapping could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function updateMapping(mapping: GestureMapping) {
    setSaving(true);
    try {
      const updated = await kyraApi.updateGestureMapping(mapping.mapping_id, {
        gesture: mapping.gesture,
        action: mapping.action,
        application: mapping.application,
        enabled: mapping.enabled,
      });
      setMappings((current) => current.map((item) => item.mapping_id === updated.mapping_id ? updated : item));
      setMessage("Mapping updated.");
    } catch {
      setMessage("The mapping could not be updated.");
    } finally {
      setSaving(false);
    }
  }

  async function deleteMapping(mappingId: string) {
    setSaving(true);
    try {
      await kyraApi.deleteGestureMapping(mappingId);
      setMappings((current) => current.filter((item) => item.mapping_id !== mappingId));
      setMessage("Mapping deleted.");
    } catch {
      setMessage("The mapping could not be deleted.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <GlassPanel className="kyra-gesture-studio" tone="strong" aria-labelledby="gesture-studio-title">
      <div className="kyra-dashboard__panel-heading">
        <div>
          <p className="kyra-dashboard__eyebrow">Gesture Studio</p>
          <h2 id="gesture-studio-title">Shape the mappings</h2>
        </div>
        <span className="kyra-dashboard__state">{loading ? "Loading" : `${mappings.length} saved`}</span>
      </div>

      <div className="kyra-gesture-studio__form">
        <label>Gesture<select value={draft.gesture} onChange={(event) => setDraft({ ...draft, gesture: event.target.value })}>{gestures.map((gesture) => <option key={gesture}>{gesture}</option>)}</select></label>
        <label>Action<select value={draft.action} onChange={(event) => setDraft({ ...draft, action: event.target.value })}>{actions.map((action) => <option key={action}>{action}</option>)}</select></label>
        <label>Profile<select value={draft.application} onChange={(event) => setDraft({ ...draft, application: event.target.value })}>{profiles.map((profile) => <option key={profile}>{profile}</option>)}</select></label>
        <NeumorphicButton disabled={saving || loading} onClick={() => void createMapping()} size="sm" tone="primary">Save mapping</NeumorphicButton>
      </div>

      {message ? <p className="kyra-gesture-studio__message" role="status">{message}</p> : null}
      {mappings.length === 0 && !loading ? <p className="kyra-dashboard__empty">No saved mappings for this account.</p> : null}
      <div className="kyra-gesture-studio__list">
        {mappings.map((mapping) => <div className="kyra-gesture-studio__row" key={mapping.mapping_id}>
          <div><strong>{mapping.gesture}</strong><span>{mapping.application} / {mapping.action}</span></div>
          <div className="kyra-gesture-studio__actions">
            <NeumorphicToggle checked={mapping.enabled} label={`${mapping.gesture} mapping`} disabled={saving} onCheckedChange={(enabled) => void updateMapping({ ...mapping, enabled })} />
            <NeumorphicButton disabled={saving} onClick={() => void deleteMapping(mapping.mapping_id)} size="sm" tone="danger">Delete</NeumorphicButton>
          </div>
        </div>)}
      </div>
    </GlassPanel>
  );
}
