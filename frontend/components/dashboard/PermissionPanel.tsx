import { useEffect, useState } from "react";

import { kyraApi } from "../../lib/api";
import type { Permission } from "../../types/contracts";
import { NeumorphicToggle } from "../ui/NeumorphicToggle";

export function PermissionPanel() {
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  async function loadPermissions() {
    setLoading(true);
    try {
      setPermissions(await kyraApi.listPermissions());
      setMessage(null);
    } catch {
      setMessage("Permission state is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadPermissions();
  }, []);

  async function togglePermission(actionIdentifier: string, changed: Partial<Permission>) {
    const next = permissions.find((item) => item.action_identifier === actionIdentifier);
    if (!next) return;
    try {
      const saved = await kyraApi.updatePermission(actionIdentifier, {
        granted: changed.granted ?? next.granted,
        requires_confirmation: changed.requires_confirmation ?? next.requires_confirmation,
      });
      setPermissions((current) => current.map((item) => item.action_identifier === actionIdentifier ? saved : item));
      setMessage(null);
    } catch {
      setMessage("The permission could not be updated.");
    }
  }

  return (
    <section className="kyra-permission-panel" aria-labelledby="permission-panel-title">
      <div className="kyra-dashboard__panel-heading">
        <div>
          <p className="kyra-dashboard__eyebrow">Safety</p>
          <h2 id="permission-panel-title">Action permissions</h2>
        </div>
        <span className="kyra-dashboard__state">{loading ? "Loading" : `${permissions.length} actions`}</span>
      </div>

      {message ? <p className="kyra-permission-panel__message" role="status">{message}</p> : null}

      <div className="kyra-permission-panel__list">
        {permissions.map((permission) => (
          <div className="kyra-permission-panel__row" key={permission.action_identifier}>
            <div>
              <strong>{permission.action_identifier}</strong>
              <small>{permission.granted ? "Allowed" : "Blocked"}</small>
            </div>
            <div className="kyra-permission-panel__toggles">
              <div>
                <span>Allow</span>
                <NeumorphicToggle checked={permission.granted} label={`Allow ${permission.action_identifier}`} onCheckedChange={(checked) => void togglePermission(permission.action_identifier, { granted: checked })} />
              </div>
              <div>
                <span>Confirm</span>
                <NeumorphicToggle checked={permission.requires_confirmation} label={`Require confirmation for ${permission.action_identifier}`} onCheckedChange={(checked) => void togglePermission(permission.action_identifier, { requires_confirmation: checked })} />
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
