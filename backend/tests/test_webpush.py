"""
Exercises the real pywebpush path (RFC 8291 payload encryption + RFC 8292 VAPID) against a
local HTTP endpoint standing in for the browser push service. Proves our VAPID key format
(raw base64url from `app.cli vapid-keys`) and subscription keys are accepted end to end.
"""

import base64
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app import notify
from app.config import get_settings
from app.models import PushSubscription


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


@pytest.fixture
def push_server():
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append({"headers": dict(self.headers), "body": body})
            self.send_response(201)
            self.end_headers()

        def log_message(self, *args):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/push/abc", received
    srv.shutdown()


@pytest.fixture
def vapid(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setenv(
        "RQ_VAPID_PRIVATE_KEY", b64url(key.private_numbers().private_value.to_bytes(32, "big"))
    )
    monkeypatch.setenv("RQ_VAPID_SUBJECT", "mailto:test@example.com")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    os.environ.pop("no_proxy", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_real_webpush_encryption_and_vapid(push_server, vapid):
    endpoint, received = push_server
    browser_key = ec.generate_private_key(ec.SECP256R1())
    p256dh = b64url(
        browser_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    sub = PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=b64url(os.urandom(16)))
    msg = notify.PushMessage("Routine Quest", "🎉 Λένα ολοκλήρωσε: Πρωινό quest!", tag="quest-1")

    assert notify.webpush_sender(sub, msg) is True
    assert len(received) == 1
    h = {k.lower(): v for k, v in received[0]["headers"].items()}
    assert h["content-encoding"] == "aes128gcm"  # RFC 8291 payload encryption
    assert h["authorization"].startswith("vapid t=")  # RFC 8292 VAPID JWT
    assert h["ttl"] == "3600"
    body = received[0]["body"]
    assert b"Routine Quest" not in body and "Λένα".encode() not in body  # payload is encrypted
    assert len(body) > len(json.dumps(msg.__dict__))
