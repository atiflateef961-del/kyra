import { getApp, getApps, initializeApp, type FirebaseApp } from "firebase/app";
import { browserLocalPersistence, getAuth, GoogleAuthProvider, setPersistence, type Auth } from "firebase/auth";

const clientKeys = [
  "VITE_FIREBASE_API_KEY",
  "VITE_FIREBASE_AUTH_DOMAIN",
  "VITE_FIREBASE_PROJECT_ID",
  "VITE_FIREBASE_APP_ID",
] as const;

type FirebaseClientKey = (typeof clientKeys)[number];

function readClientConfig() {
  const values = Object.fromEntries(
    clientKeys.map((key) => [key, import.meta.env[key]?.trim() ?? ""]),
  ) as Record<FirebaseClientKey, string>;
  const missing = clientKeys.filter((key) => !values[key]);

  if (missing.length) {
    throw new Error(`Firebase browser configuration is incomplete: ${missing.join(", ")}`);
  }

  return {
    apiKey: values.VITE_FIREBASE_API_KEY,
    authDomain: values.VITE_FIREBASE_AUTH_DOMAIN,
    projectId: values.VITE_FIREBASE_PROJECT_ID,
    appId: values.VITE_FIREBASE_APP_ID,
  };
}

export function isFirebaseClientConfigured() {
  return clientKeys.every((key) => Boolean(import.meta.env[key]?.trim()));
}

export function getFirebaseApp(): FirebaseApp {
  return getApps().length ? getApp() : initializeApp(readClientConfig());
}

export function getFirebaseAuth(): Auth {
  const auth = getAuth(getFirebaseApp());
  void setPersistence(auth, browserLocalPersistence);
  return auth;
}

export function createGoogleProvider() {
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  return provider;
}
