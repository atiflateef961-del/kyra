import { existsSync, readFileSync } from "node:fs";
import { Agent as HttpsAgent } from "node:https";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const projectRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, projectRoot, "");
  const httpsEnabled = environment.KYRA_DEV_HTTPS === "true";
  const certificatePath = environment.KYRA_DEV_TLS_CERT
    ? resolve(projectRoot, environment.KYRA_DEV_TLS_CERT)
    : resolve(projectRoot, "dev-certs/kyra-lan-cert.pem");
  const privateKeyPath = environment.KYRA_DEV_TLS_KEY
    ? resolve(projectRoot, environment.KYRA_DEV_TLS_KEY)
    : resolve(projectRoot, "dev-certs/kyra-lan-key.pem");
  const agentUrl = environment.VITE_AGENT_URL || process.env.VITE_AGENT_URL || "http://127.0.0.1:8000";
  const agentTarget = new URL(agentUrl);
  const localCaPath = resolve(projectRoot, "dev-certs/kyra-dev-ca.crt");
  const proxyCa = agentTarget.protocol === "https:" && existsSync(localCaPath)
    ? readFileSync(localCaPath)
    : undefined;
  const proxyAgent = proxyCa ? new HttpsAgent({ ca: proxyCa }) : undefined;

  if (httpsEnabled && (!environment.KYRA_DEV_TLS_CERT || !environment.KYRA_DEV_TLS_KEY)) {
    throw new Error("LAN HTTPS is enabled but KYRA_DEV_TLS_CERT and KYRA_DEV_TLS_KEY are not configured.");
  }
  if (mode === "lan" && !httpsEnabled) {
    throw new Error("LAN mode requires KYRA_DEV_HTTPS=true so camera and microphone access use a secure origin.");
  }

  return {
    plugins: [react()],
    css: {
      postcss: "./postcss.config.cjs",
    },
    envDir: projectRoot,
    server: {
      host: "0.0.0.0",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target: agentUrl,
          changeOrigin: true,
          ...(proxyAgent ? { agent: proxyAgent } : {}),
        },
        "/ws": {
          target: agentUrl,
          changeOrigin: true,
          ws: true,
          ...(proxyAgent ? { agent: proxyAgent } : {}),
        },
      },
      ...(httpsEnabled
        ? {
            https: {
              cert: readFileSync(certificatePath),
              key: readFileSync(privateKeyPath),
            },
          }
        : {}),
    },
  };
});
