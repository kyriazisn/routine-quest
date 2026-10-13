import { defineConfig } from "@playwright/test";
import { E2E_LOG, PORTS } from "./e2e/env";

/*
 * Full-stack e2e: real backend (Postgres) + device simulator (provisioning over HTTP) + production
 * build of the PWA with VITE_ALLOW_SIM=1. Web Bluetooth itself cannot be automated; the BLE
 * transport is verified on hardware (docs/065-pwa.md).
 *
 * Env: RQ_DATABASE_URL (must contain "e2e"), RQ_PYTHON (venv with backend + grpcio-tools),
 *      CHROMIUM_PATH (optional; otherwise @sparticuz/chromium is used, see e2e/chromium.ts).
 */
const { API_PORT, SIM_PORT, APP_PORT } = PORTS;
const PY = process.env.RQ_PYTHON ?? "python3";

export default defineConfig({
  testDir: "e2e",
  testMatch: "*.spec.ts",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${APP_PORT}`,
    locale: "el-GR",
    timezoneId: "Europe/Athens",
    viewport: { width: 390, height: 844 },
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "./e2e/start-backend.sh",
      url: `http://127.0.0.1:${API_PORT}/healthz`,
      env: { RQ_PYTHON: PY, RQ_E2E_LOG: E2E_LOG, RQ_API_PORT: String(API_PORT), RQ_PUBLIC_APP_URL: `http://127.0.0.1:${APP_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `${PY} e2e/sim/prov_sim.py --port ${SIM_PORT} --pop rq-e2e-pop --networks "HomeNet:secret123,Guest:"`,
      url: `http://127.0.0.1:${SIM_PORT}/_state`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx vite build --mode e2e && npx vite preview --port ${APP_PORT} --strictPort --host 127.0.0.1`,
      url: `http://127.0.0.1:${APP_PORT}/`,
      env: { VITE_ALLOW_SIM: "1", RQ_API_URL: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
