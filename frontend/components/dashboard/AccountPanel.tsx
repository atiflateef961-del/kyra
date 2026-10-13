import { useEffect, useState } from "react";

import { useAuth } from "../auth/AuthProvider";
import { NeumorphicButton } from "../ui/NeumorphicButton";
import { kyraApi } from "../../lib/api";

export function AccountPanel() {
  const { user, signOut } = useAuth();
  const [identity, setIdentity] = useState<{ firebase_uid: string; email: string | null; name: string | null } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const loadIdentity = async () => {
      try {
        const next = await kyraApi.me();
        if (mounted) setIdentity(next);
      } catch {
        if (mounted) setIdentity(null);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    void loadIdentity();
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <section className="kyra-account-panel" aria-labelledby="account-panel-title">
      <div className="kyra-dashboard__panel-heading">
        <div>
          <p className="kyra-dashboard__eyebrow">Account</p>
          <h2 id="account-panel-title">Profile</h2>
        </div>
        <span className="kyra-dashboard__state">{user ? "Verified" : "Guest"}</span>
      </div>

      <div className="kyra-account-panel__grid">
        <div className="kyra-account-panel__field">
          <span>Name</span>
          <strong>{identity?.name ?? user?.displayName ?? "No display name"}</strong>
        </div>
        <div className="kyra-account-panel__field">
          <span>Email</span>
          <strong>{identity?.email ?? user?.email ?? "No email"}</strong>
        </div>
        <div className="kyra-account-panel__field kyra-account-panel__field--wide">
          <span>Firebase UID</span>
          <strong>{identity?.firebase_uid ?? user?.uid ?? "Unavailable"}</strong>
        </div>
      </div>

      <div className="kyra-account-panel__actions">
        <span className="kyra-account-panel__status">{loading ? "Loading profile..." : "Authenticated"}</span>
        <NeumorphicButton onClick={() => void signOut()} size="sm" tone="danger">Sign out</NeumorphicButton>
      </div>
    </section>
  );
}
