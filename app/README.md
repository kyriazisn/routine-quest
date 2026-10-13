# Routine Quest — parent PWA

Vite + React + TypeScript. Design and decisions: [`docs/065-pwa.md`](../docs/065-pwa.md).

## Develop

```bash
cd app
npm ci
RQ_API_URL=http://127.0.0.1:8000 npm run dev      # proxies /v1 to the backend
```

Backend: see `backend/README.md` (use `RQ_MAILER=console`, `RQ_COOKIE_SECURE=false`,
`RQ_PUBLIC_APP_URL=http://localhost:5173` locally; magic links appear in the API log).

Pair without hardware (dev only):

```bash
pip install -r e2e/sim/requirements.txt
python e2e/sim/prov_sim.py --port 8765 --pop rq-dev-pop --networks "HomeNet:secret123,Guest:"
VITE_ALLOW_SIM=1 npm run dev
# open http://localhost:5173/setup/pair?sim=http://127.0.0.1:8765
```

## Test

```bash
npm run typecheck
RQ_PYTHON=<venv>/bin/python npm test               # protobuf + Security 1 client vs simulator

# E2E: real backend + simulator + PWA in Chromium. Needs a DEDICATED database whose name
# contains "e2e" — its schema is reset on every run.
export RQ_DATABASE_URL="postgresql+psycopg://<user>@<host>/rq_e2e"
export RQ_PYTHON=<venv>/bin/python                 # backend deps + e2e/sim/requirements.txt
npx playwright test                                # optional: RQ_SHOTS=<dir> for screenshots
```

Chromium comes from the `@sparticuz/chromium` npm package (no `playwright install`); set
`CHROMIUM_PATH` to use a local Chrome instead.

## Build

```bash
npm run build      # → dist/ ; serve behind the same origin as /v1
```

Never set `VITE_ALLOW_SIM` for production builds.
