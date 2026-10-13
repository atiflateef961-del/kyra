"use client";

import { createUserWithEmailAndPassword, signInWithEmailAndPassword, signInWithPopup } from "firebase/auth";
import { useState, type FormEvent } from "react";

import { createGoogleProvider, getFirebaseAuth } from "../../lib/firebase";
import { NeumorphicButton } from "../ui/NeumorphicButton";
import { useAuth } from "./AuthProvider";

export function SignInForm() {
  const { configured } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"sign-in" | "sign-up">("sign-in");
  const [pending, setPending] = useState<"email" | "google" | null>(null);

  const describeError = (cause: unknown) => {
    if (cause && typeof cause === "object" && "code" in cause) {
      switch (cause.code) {
        case "auth/invalid-credential":
          return "That email or password is not valid. Create an account or try again.";
        case "auth/invalid-email":
          return "Enter a valid email address.";
        case "auth/email-already-in-use":
          return "That email already has a Kyra account. Sign in instead.";
        case "auth/weak-password":
          return "Choose a password with at least 6 characters.";
        case "auth/api-key-not-valid":
          return "Firebase browser configuration is invalid for this environment.";
        case "auth/operation-not-allowed":
          return "This sign-in method is not enabled in Firebase Authentication.";
        case "auth/too-many-requests":
          return "Too many attempts were made. Wait a moment and try again.";
        case "auth/network-request-failed":
          return "Firebase could not be reached. Check the network and try again.";
        case "auth/popup-closed-by-user":
          return "Google sign-in was cancelled.";
        case "auth/unauthorized-domain":
          return "This web address is not authorized in Firebase Authentication.";
      }
    }
    return cause instanceof Error ? cause.message : "Authentication failed. Please try again.";
  };

  async function handleEmailSignIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending("email");
    try {
      const auth = getFirebaseAuth();
      if (mode === "sign-up") await createUserWithEmailAndPassword(auth, email, password);
      else await signInWithEmailAndPassword(auth, email, password);
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setPending(null);
    }
  }

  async function handleGoogleSignIn() {
    setError(null);
    setPending("google");
    try {
      await signInWithPopup(getFirebaseAuth(), createGoogleProvider());
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setPending(null);
    }
  }

  if (!configured) {
    return (
      <main className="kyra-auth" aria-labelledby="auth-title">
        <section className="kyra-auth__shell kyra-auth__shell--notice">
          <div className="kyra-auth__brand"><span className="kyra-auth__mark" aria-hidden="true">K</span><span>KYRA</span></div>
          <p className="kyra-auth__eyebrow">Local intelligence console</p>
          <h1 id="auth-title">Your computer,<br /><em>more intuitive.</em></h1>
          <p className="kyra-auth__description">Connect vision, voice, and safe automation in one calm control surface.</p>
          <p className="kyra-auth__notice" role="alert">Firebase authentication is not configured for this environment.</p>
        </section>
      </main>
    );
  }

  return (
    <main className="kyra-auth" aria-labelledby="auth-title">
      <section className="kyra-auth__shell">
        <div className="kyra-auth__story">
          <div className="kyra-auth__brand"><span className="kyra-auth__mark" aria-hidden="true">K</span><span>KYRA</span></div>
          <div className="kyra-auth__story-copy">
            <p className="kyra-auth__eyebrow">Local intelligence console</p>
            <h1 id="auth-title">Your computer,<br /><em>more intuitive.</em></h1>
            <p className="kyra-auth__description">Connect vision, voice, and safe automation in one calm control surface.</p>
          </div>
          <div className="kyra-auth__signal" aria-label="Kyra system capabilities">
            <span><i aria-hidden="true" />Vision</span><span><i aria-hidden="true" />Voice</span><span><i aria-hidden="true" />Control</span>
          </div>
        </div>
        <div className="kyra-auth__form-area">
          <div className="kyra-auth__form-heading"><p className="kyra-auth__eyebrow">{mode === "sign-in" ? "Welcome back" : "New account"}</p><h2>{mode === "sign-in" ? "Sign in to continue" : "Create your Kyra account"}</h2><p>Use your Kyra account to access your local agent.</p></div>
          <form aria-label="Sign in to Kyra" onSubmit={handleEmailSignIn}>
            <label className="kyra-auth__field"><span>Email address</span><input autoComplete="email" onChange={(event) => setEmail(event.target.value)} required type="email" value={email} /></label>
            <label className="kyra-auth__field"><span>Password</span><input autoComplete="current-password" minLength={6} onChange={(event) => setPassword(event.target.value)} required type="password" value={password} /></label>
            {error ? <p className="kyra-auth__error" role="alert">{error}</p> : null}
            <NeumorphicButton className="kyra-auth__submit" disabled={pending !== null} tone="primary" type="submit">
              {pending === "email" ? (mode === "sign-in" ? "Signing in…" : "Creating account…") : mode === "sign-in" ? "Sign in" : "Create account"}
            </NeumorphicButton>
            <div className="kyra-auth__divider"><span>or</span></div>
            <NeumorphicButton className="kyra-auth__google" disabled={pending !== null} onClick={handleGoogleSignIn} type="button">
              {pending === "google" ? "Opening Google…" : "Continue with Google"}
            </NeumorphicButton>
            <button className="kyra-auth__mode" disabled={pending !== null} onClick={() => { setMode(mode === "sign-in" ? "sign-up" : "sign-in"); setError(null); }} type="button">
              {mode === "sign-in" ? "Need an account? Create one" : "Already have an account? Sign in"}
            </button>
          </form>
          <p className="kyra-auth__privacy">Your camera, microphone, and computer controls stay local to the agent.</p>
        </div>
      </section>
    </main>
  );
}
