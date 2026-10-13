"use client";

import { onIdTokenChanged, signOut, type User } from "firebase/auth";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { getFirebaseAuth, isFirebaseClientConfigured } from "../../lib/firebase";

type AuthState = {
  configured: boolean;
  error: string | null;
  loading: boolean;
  signOut: () => Promise<void>;
  user: User | null;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const configured = isFirebaseClientConfigured();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(configured);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!configured) {
      setLoading(false);
      setError("Firebase authentication is not configured for this environment.");
      return;
    }

    let unsubscribe: (() => void) | undefined;
    try {
      unsubscribe = onIdTokenChanged(
        getFirebaseAuth(),
        (nextUser) => {
          setUser(nextUser);
          setError(null);
          setLoading(false);
        },
        () => {
          setUser(null);
          setError("Your session could not be restored. Please sign in again.");
          setLoading(false);
        },
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Authentication could not start.");
      setLoading(false);
    }

    return () => unsubscribe?.();
  }, [configured]);

  const value = useMemo<AuthState>(
    () => ({
      configured,
      error,
      loading,
      signOut: async () => {
        if (!configured) return;
        await signOut(getFirebaseAuth());
      },
      user,
    }),
    [configured, error, loading, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider.");
  return context;
}
