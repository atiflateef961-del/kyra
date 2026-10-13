# Kyra architecture foundation

Kyra is a local-first monorepo. The browser UI never performs privileged Windows
operations. The local Python agent owns device access, intent validation, safety
checks, and controlled execution.

## Boundaries

```text
frontend/  Browser UI and presentation only
    | authenticated, typed requests and event subscriptions
backend/   Local agent, safety boundary, and device integrations
    | optional, explicit cloud integrations
Cloud       Firebase identity and optional MongoDB persistence
```

The backend accepts structured intents only. Future computer-control adapters must
be reached through an allowlisted action registry and respect `KYRA_DRY_RUN`.

Camera frames, microphone audio, temporary transcripts, active-window context,
and direct Windows control remain local by default. No cloud integration is
required by this foundation.

## Planned ownership

```text
frontend/
  app/          Routes (Task 19 and later)
  components/   UI system (Tasks 3–6)
  lib/          API and contract clients (Task 10)
  types/        Frontend contract types (Task 10)

backend/
  app/          FastAPI application (Task 8)
  tests/        Safe automated tests (Task 8 onward)
```

Directories are created when their owning task begins, preventing placeholder
implementations from looking like working features.
