import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API is served from the same origin in production (reverse proxy → backend), so the
// HttpOnly session cookie works without CORS. In development Vite proxies /v1 to the backend.
const API = process.env.RQ_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/v1": { target: API, changeOrigin: false } } },
  preview: { port: 4173, proxy: { "/v1": { target: API, changeOrigin: false } } },
  build: { sourcemap: true, target: "es2022" },
});
