# Kyra

Kyra is a local-first computer-control platform. The React dashboard connects
to a Python FastAPI agent that owns authentication checks, intent validation,
action safety, and local Windows control.

## Development setup

Configure Firebase browser values (`VITE_FIREBASE_*`) and server-only Admin
credentials (`FIREBASE_PROJECT_ID`, `FIREBASE_CLIENT_EMAIL`,
`FIREBASE_PRIVATE_KEY`) in the ignored root `.env`. Never expose Admin
credentials to frontend code. `KYRA_DRY_RUN=true` is the safe default.

Install backend dependencies and start both services from the workspace root:

```powershell
.venv\Scripts\python.exe -m pip install -e .\backend
.venv\Scripts\python.exe scripts\dev.py
```

The dashboard is at `http://localhost:5173`; FastAPI uses port `8000`.
In development, `/api` and `/ws` go through the Vite server to FastAPI, so open
the dashboard on the same origin (`http://localhost:5173`) instead of pointing
the browser directly at port `8000`. This default mode is local-only. To use
KYRA from another device on your Wi-Fi, start both services in secure LAN mode:

```powershell
cd D:\KYRA
.venv\Scripts\python.exe scripts\dev.py --lan
```

Open the exact HTTPS dashboard URL printed by the launcher. The launcher can
switch verified KYRA processes between local and LAN modes. If it reports that
a port belongs to an unrelated or unverifiable process, stop that process
yourself before retrying. Do not use `npm run dev` or a standalone Uvicorn
command for LAN mode; those commands do not configure the matching HTTPS,
WebSocket origin, and proxy settings. To start only FastAPI for local debugging:

```powershell
cd D:\KYRA
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

The launcher checks both ports before startup, reports the owning process if a
port is occupied, and stops both services when you press Ctrl+C. It does not
silently select replacement ports. Backend host and port are configured with
`APP_HOST` and `APP_PORT`.

### Check the local connection

Run these from PowerShell on the KYRA computer:

```powershell
Test-NetConnection localhost -Port 8000
Test-NetConnection localhost -Port 5173
Invoke-WebRequest http://localhost:8000/api/health -UseBasicParsing
Invoke-WebRequest http://localhost:5173/api/health -UseBasicParsing
```

Both health requests should return HTTP 200 with `"api":"online"`. The second
request goes through Vite's `/api` proxy to FastAPI. The dashboard's `/ws/agent`
connection uses Vite's WebSocket proxy and still requires a signed-in Firebase
user. When using a LAN address, use the HTTPS URL reported by `scripts\dev.py
--lan`; the backend checks that exact frontend origin for WebSocket connections.

## Secure LAN development

LAN camera and microphone access requires HTTPS. Start the same services in
LAN mode:

```powershell
.venv\Scripts\python.exe scripts\dev.py --lan
```

For another computer or a dashboard opened by the KYRA machine's LAN IP, use
this LAN mode and open the reported HTTPS dashboard URL. It configures the
matching FastAPI CORS and WebSocket origin and proxies browser requests through
Vite. Do not use the plain HTTP LAN address for camera or microphone access.

The launcher discovers the current private IPv4 address and synchronizes the
LAN HTTPS certificate, explicit frontend origin for CORS and WebSocket origin
validation, frontend API URL, and `/ws/agent` WSS URL. It reports the current
dashboard and backend addresses. If the address changes, it creates a matching
certificate and you must trust its CA again.

Import `dev-certs/kyra-dev-ca.crt` into the trusted root store on the KYRA
computer and every device that will open the site. On Windows, run this as the
signed-in browser user:

```powershell
Import-Certificate -FilePath D:\KYRA\dev-certs\kyra-dev-ca.crt -CertStoreLocation Cert:\CurrentUser\Root
```

Never copy `kyra-dev-ca-key.pem` or `kyra-lan-key.pem` to client devices. The
generated `dev-certs/` directory is ignored by Git.

## Verification

Backend tests run from `backend/` with `pytest`. Frontend checks run from the
workspace root with `npm run typecheck`, `npm run lint`, and `npm run build`.
cd D:\KYRA
.\.venv\Scripts\python.exe scripts\dev.py --lan
