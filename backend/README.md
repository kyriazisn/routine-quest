# Routine Quest — Backend

FastAPI + PostgreSQL. Device API (claim, events, config), parent API for the PWA, game rules, Web Push.
Design and API reference: [`docs/05-backend.md`](../docs/05-backend.md).

## Local development (Docker)

```bash
cd backend
cp .env.example .env
docker compose up --build
# API + OpenAPI UI: http://localhost:8000/docs
# Magic links are printed in the `api` service logs (console mailer, dev only)
```

Web Push keys:

```bash
docker compose run --rm api python -m app.cli vapid-keys   # put the output in .env, never commit it
```

## Local development (without Docker)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
export RQ_DATABASE_URL=postgresql+psycopg://<user>@localhost:5432/routinequest RQ_COOKIE_SECURE=false
alembic upgrade head
uvicorn app.main:app --reload
python -m app.cli run-jobs --loop 60      # second terminal: closes expired quest windows
```

## Tests

Tests need a disposable PostgreSQL database (the schema is dropped and re-migrated):

```bash
export RQ_TEST_DATABASE_URL=postgresql+psycopg://<user>@localhost:5432/rq_test
pytest
ruff check app tests migrations && ruff format --check app tests migrations
```

## Migrations

```bash
alembic revision --autogenerate -m "<change>"   # review the generated file before committing
alembic upgrade head
alembic check                                   # CI fails if models and migrations drift
```

## Layout

| Path | |
|---|---|
| `app/game.py` | XP, levels, stars, streak, rewards (source of truth) |
| `app/routers/device.py` | Firmware contract (`firmware/main/cloud.c`) |
| `app/routers/parent.py` | PWA API |
| `app/notify.py` | Web Push messages, quiet hours, mute, backlog filter |
| `app/jobs.py` | Server-side expiry of quest windows |
| `app/timeutil.py` | `day_index`, Monday weeks, IANA → POSIX TZ for the device |
