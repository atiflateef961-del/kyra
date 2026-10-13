import { useEffect, useState } from "react";

import { kyraApi } from "../../lib/api";
import type { Device, DeviceRegistrationRequest } from "../../types/contracts";
import { NeumorphicButton } from "../ui/NeumorphicButton";

const blankDevice: DeviceRegistrationRequest = { device_id: "", display_name: "" };

export function DevicePanel() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [draft, setDraft] = useState<DeviceRegistrationRequest>(blankDevice);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function loadDevices() {
    setLoading(true);
    try {
      setDevices(await kyraApi.listDevices());
      setMessage(null);
    } catch {
      setMessage("Device registry is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadDevices();
  }, []);

  async function registerDevice() {
    if (!draft.device_id.trim() || !draft.display_name.trim()) {
      setMessage("Device ID and display name are required.");
      return;
    }
    setSaving(true);
    try {
      const saved = await kyraApi.registerDevice(draft);
      setDevices((current) => [saved, ...current.filter((item) => item.device_id !== saved.device_id)]);
      setDraft(blankDevice);
      setMessage("Device registered.");
    } catch {
      setMessage("The device could not be registered.");
    } finally {
      setSaving(false);
    }
  }

  async function removeDevice(deviceId: string) {
    setSaving(true);
    try {
      await kyraApi.deleteDevice(deviceId);
      setDevices((current) => current.filter((item) => item.device_id !== deviceId));
      setMessage("Device removed.");
    } catch {
      setMessage("The device could not be removed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="kyra-device-panel" aria-labelledby="device-panel-title">
      <div className="kyra-dashboard__panel-heading">
        <div>
          <p className="kyra-dashboard__eyebrow">Devices</p>
          <h2 id="device-panel-title">Connected devices</h2>
        </div>
        <span className="kyra-dashboard__state">{loading ? "Loading" : `${devices.length} registered`}</span>
      </div>

      <div className="kyra-device-panel__form">
        <label>
          <span>Device ID</span>
          <input value={draft.device_id} onChange={(event) => setDraft((current) => ({ ...current, device_id: event.target.value }))} placeholder="device-1" />
        </label>
        <label>
          <span>Display name</span>
          <input value={draft.display_name} onChange={(event) => setDraft((current) => ({ ...current, display_name: event.target.value }))} placeholder="Laptop" />
        </label>
        <NeumorphicButton disabled={saving || loading} onClick={() => void registerDevice()} size="sm" tone="primary">Register device</NeumorphicButton>
      </div>

      {message ? <p className="kyra-device-panel__message" role="status">{message}</p> : null}
      {devices.length === 0 && !loading ? <p className="kyra-dashboard__empty">No devices registered for this account.</p> : null}

      <div className="kyra-device-panel__list">
        {devices.map((device) => (
          <div className="kyra-device-panel__row" key={device.device_id}>
            <div>
              <strong>{device.display_name}</strong>
              <small>{device.device_id}</small>
            </div>
            <NeumorphicButton disabled={saving} onClick={() => void removeDevice(device.device_id)} size="sm" tone="danger">Remove</NeumorphicButton>
          </div>
        ))}
      </div>
    </section>
  );
}
