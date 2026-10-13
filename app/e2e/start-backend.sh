#!/usr/bin/env bash
# Starts the FastAPI backend for Playwright e2e against a DEDICATED e2e database.
# The schema is reset on every run, so this refuses any database whose name lacks "e2e".
set -euo pipefail
: "${RQ_DATABASE_URL:?set RQ_DATABASE_URL to a dedicated e2e database}"
case "$RQ_DATABASE_URL" in
  *e2e*) ;;
  *) echo "refusing: RQ_DATABASE_URL must point to a database whose name contains 'e2e'" >&2; exit 1 ;;
esac
export RQ_ENV=dev RQ_MAILER=console RQ_COOKIE_SECURE=false
export RQ_PUBLIC_APP_URL="${RQ_PUBLIC_APP_URL:-http://127.0.0.1:4173}"
PY="${RQ_PYTHON:-python3}"
LOG="${RQ_E2E_LOG:?set RQ_E2E_LOG (magic links are read from it)}"
cd "$(dirname "$0")/../../backend"
"$PY" -m alembic downgrade base >/dev/null
"$PY" -m alembic upgrade head >/dev/null
: >"$LOG"
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "${RQ_API_PORT:-8001}" >>"$LOG" 2>&1
