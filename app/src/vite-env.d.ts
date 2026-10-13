/// <reference types="vite/client" />
interface ImportMetaEnv {
  /** "1" enables the ?sim=<url> HTTP provisioning transport (dev/e2e only). */
  readonly VITE_ALLOW_SIM?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
