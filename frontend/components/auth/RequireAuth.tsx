"use client";

import type { ReactNode } from "react";

import { useAuth } from "./AuthProvider";

export function RequireAuth({ children, fallback }: { children: ReactNode; fallback: ReactNode }) {
  const { error, loading, user } = useAuth();
  if (loading) return <p aria-live="polite">Restoring session…</p>;
  if (error || !user) return <>{fallback}</>;
  return <>{children}</>;
}
