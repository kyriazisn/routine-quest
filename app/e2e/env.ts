import { fileURLToPath } from "node:url";

export const PORTS = { API_PORT: 8001, SIM_PORT: 8765, APP_PORT: 4173 } as const;
export const E2E_LOG = fileURLToPath(new URL("./.backend.log", import.meta.url));
