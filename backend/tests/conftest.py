"""
Tests run against a real PostgreSQL database (RQ_TEST_DATABASE_URL), migrated with Alembic.
Each test starts from empty tables.
"""

import os
import re
import uuid
from datetime import UTC, datetime

import pytest

os.environ.setdefault("RQ_TEST_DATABASE_URL", "postgresql+psycopg://postgres@/rq_test?host=/tmp&port=5433")
os.environ["RQ_DATABASE_URL"] = os.environ["RQ_TEST_DATABASE_URL"]
os.environ["RQ_ENV"] = "test"
os.environ["RQ_COOKIE_SECURE"] = "false"
os.environ["RQ_PUBLIC_APP_URL"] = "http://app.test"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import mailer, notify  # noqa: E402
from app.db import Base, get_engine, session_factory  # noqa: E402
from app.main import create_app  # noqa: E402
from app.security import claim_limiter, magic_link_limiter  # noqa: E402
from app.timeutil import today_index  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    with get_engine().begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "migrations"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables():
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with get_engine().begin() as c:
        c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    magic_link_limiter.reset()
    claim_limiter.reset()
    mailer.outbox.clear()
    yield


class PushCapture:
    def __init__(self):
        self.messages: list[tuple[str, notify.PushMessage]] = []
        self.gone: set[str] = set()

    def __call__(self, sub, msg) -> bool:
        if sub.endpoint in self.gone:
            return False
        self.messages.append((sub.endpoint, msg))
        return True

    def bodies(self) -> list[str]:
        return [m.body for _, m in self.messages]


@pytest.fixture
def pushes():
    cap = PushCapture()
    notify.set_sender(cap)
    yield cap
    notify.set_sender(notify.webpush_sender)


@pytest.fixture
def db():
    with session_factory()() as s:
        yield s


@pytest.fixture
def client():
    return TestClient(create_app())


# ------------------------------------------------------------------ helpers


def login(client: TestClient, email: str) -> dict:
    r = client.post("/v1/auth/magic-link", json={"email": email})
    assert r.status_code == 202, r.text
    link = [link for to, link in mailer.outbox if to == email.lower()][-1]
    token = re.search(r"token=([\w-]+)", link).group(1)
    r = client.post("/v1/auth/verify", json={"token": token})
    assert r.status_code == 200, r.text
    session = client.cookies.get("rq_session")
    client.cookies.clear()
    return {"Authorization": f"Bearer {session}"}


MORNING = {
    "name": "Πρωινό quest",
    "icon": "🌅",
    "start_min": 0,
    "end_min": 720,
    "days_mask": 127,
    "notify_mode": "complete_only",
    "notify_expired": True,
    "steps": [
        {"button": 0, "icon": "🪥", "label": "Δόντια"},
        {"button": 1, "icon": "👕", "label": "Ντύσιμο"},
        {"button": 2, "icon": "🥣", "label": "Πρωινό"},
        {"button": 3, "icon": "🎒", "label": "Τσάντα"},
    ],
}
EVENING = {
    "name": "Βραδινό quest",
    "icon": "🌙",
    "start_min": 720,
    "end_min": 1440,
    "days_mask": 127,
    "notify_mode": "complete_only",
    "notify_expired": True,
    "steps": [
        {"button": 3, "icon": "🛁", "label": "Μπάνιο"},
        {"button": 1, "icon": "🩳", "label": "Πιτζάμες"},
        {"button": 0, "icon": "🪥", "label": "Δόντια"},
    ],
}


class Family:
    """A signed-in parent with one child, two routines and a paired device."""

    def __init__(self, client: TestClient, email: str = "parent@example.com"):
        self.client = client
        self.h = login(client, email)
        r = client.post("/v1/children", json={"nickname": "Λένα", "avatar": "🦊"}, headers=self.h)
        assert r.status_code == 201, r.text
        self.child_id = r.json()["id"]
        r = client.put(
            f"/v1/children/{self.child_id}/routines", json={"routines": [MORNING, EVENING]}, headers=self.h
        )
        assert r.status_code == 200, r.text
        self.routines = r.json()
        self.morning, self.evening = self.routines[0]["id"], self.routines[1]["id"]
        code = client.post(f"/v1/children/{self.child_id}/claim-codes", headers=self.h).json()["code"]
        self.device_id = "rq-240ac4000110"
        r = client.post(
            "/v1/device/claim", json={"device_id": self.device_id, "claim_code": code, "fw_version": "0.1.0"}
        )
        assert r.status_code == 200, r.text
        self.dh = {"Authorization": f"Bearer {r.json()['device_token']}", "X-Device-Id": self.device_id}
        self.seq = 0
        self.today = today_index("Europe/Athens")

    def subscribe(self, endpoint: str = "https://push.example.com/sub/1") -> None:
        r = self.client.post(
            "/v1/push/subscriptions",
            headers=self.h,
            json={"endpoint": endpoint, "keys": {"p256dh": "BPk", "auth": "auth"}},
        )
        assert r.status_code == 201, r.text

    def ev(
        self,
        type_: str,
        routine_id: int,
        step: int = 0,
        *,
        fast: bool = False,
        day: int | None = None,
        ts: int | None = None,
    ) -> dict:
        """Event exactly as firmware/main/cloud.c serialises it (numbers as cJSON doubles)."""
        self.seq += 1
        return {
            "event_id": str(uuid.uuid4()),
            "seq": float(self.seq),
            "type": type_,
            "ts": float(ts if ts is not None else int(datetime.now(UTC).timestamp())),
            "day_index": float(self.today if day is None else day),
            "routine_id": float(routine_id),
            "step": float(step),
            "fast": fast,
        }

    def send(self, *events: dict):
        r = self.client.post(
            "/v1/device/events", headers=self.dh, json={"device_id": self.device_id, "events": list(events)}
        )
        assert r.status_code == 200, r.text
        return r.json()

    def complete(self, routine_id: int, nsteps: int, *, fast: bool = False, day: int | None = None):
        evs = [self.ev("window_open", routine_id, day=day)]
        evs += [self.ev("step_done", routine_id, s, day=day) for s in range(nsteps - 1)]
        evs.append(self.ev("quest_complete", routine_id, nsteps - 1, fast=fast, day=day))
        return self.send(*evs)

    def today_view(self) -> dict:
        r = self.client.get(f"/v1/children/{self.child_id}/today", headers=self.h)
        assert r.status_code == 200, r.text
        return r.json()

    def config(self, etag: str | None = None):
        h = dict(self.dh)
        if etag:
            h["If-None-Match"] = etag
        return self.client.get("/v1/device/config", headers=h)


@pytest.fixture
def family(client) -> Family:
    return Family(client)
