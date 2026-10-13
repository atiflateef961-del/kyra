# Authentication foundation

This component uses the Vite React application and requires Firebase browser
configuration in the root `.env` file. It does not include credentials.

## Required runtime packages

Install the official packages when the frontend and backend runtime setup is
performed:

```text
frontend: firebase, react, react-dom, motion
backend: firebase-admin
```

## Required configuration

Set `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`,
`VITE_FIREBASE_PROJECT_ID`, and `VITE_FIREBASE_APP_ID` from Firebase's web
application configuration. Set `FIREBASE_PROJECT_ID`,
`FIREBASE_CLIENT_EMAIL`, and `FIREBASE_PRIVATE_KEY` only for the local backend.
The Admin values must never be exposed to the browser.

`RequireAuth` protects rendered content; a later route integration may redirect
unauthenticated users. The backend verifier accepts a bearer token, verifies it
with Firebase Admin, and returns a trusted UID rather than accepting a claimed
client UID.
