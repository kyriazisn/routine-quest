"""
Admin CLI.
  python -m app.cli vapid-keys          generate a VAPID key pair for Web Push
  python -m app.cli run-jobs [--loop N] close expired quest windows (every N seconds)
"""

import argparse
import base64
import logging
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def vapid_keys() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    print("# Store as secrets, never commit:")
    print(f"RQ_VAPID_PRIVATE_KEY={_b64url(private_raw)}")
    print(f"RQ_VAPID_PUBLIC_KEY={_b64url(public_raw)}")


def run_jobs(loop: int | None) -> None:
    from app.db import session_factory
    from app.jobs import close_expired_windows
    from app.notify import dispatch

    while True:
        with session_factory()() as db:
            outcomes = close_expired_windows(db)
            sent = dispatch(db, outcomes)
            logging.getLogger("rq.jobs").info("expired=%d pushes=%d", len(outcomes), sent)
        if not loop:
            return
        time.sleep(loop)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("vapid-keys")
    j = sub.add_parser("run-jobs")
    j.add_argument("--loop", type=int, default=None, help="repeat every N seconds")
    a = p.parse_args()
    if a.cmd == "vapid-keys":
        vapid_keys()
    elif a.cmd == "run-jobs":
        run_jobs(a.loop)


if __name__ == "__main__":
    main()
