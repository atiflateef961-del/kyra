import { lazy, Suspense } from "react";

import { AuthProvider } from "../components/auth/AuthProvider";
import { RequireAuth } from "../components/auth/RequireAuth";
import { SignInForm } from "../components/auth/SignInForm";
import { MotionProvider } from "../components/motion/MotionProvider";

const Dashboard = lazy(async () => {
  const module = await import("../components/dashboard/Dashboard");
  return { default: module.Dashboard };
});

export default function App() {
  return (
    <MotionProvider>
      <AuthProvider>
        <RequireAuth fallback={<SignInForm />}>
          <Suspense fallback={<p aria-live="polite">Loading the local console…</p>}>
            <Dashboard />
          </Suspense>
        </RequireAuth>
      </AuthProvider>
    </MotionProvider>
  );
}
