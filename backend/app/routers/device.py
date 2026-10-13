"""
Device API — contract implemented by firmware/main/cloud.c.

  POST /v1/device/claim   {device_id, claim_code, fw_version}  -> {device_token}
  POST /v1/device/events  Bearer, {device_id, events[]}        -> {accepted, duplicates}
  GET  /v1/device/config  Bearer, If-None-Match: "<version>"   -> 200 config | 304
"""

import json
import zlib
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.deps import DB, CurrentDevice
from app.game import Game, week_stars
from app.models import ClaimCode, Device, DeviceEvent, PauseDay, utcnow
from app.notify import dispatch_in_new_session
from app.schemas import DeviceClaimIn, DeviceClaimOut, DeviceEventsIn, DeviceEventsOut
from app.security import claim_limiter, new_token, sha256
from app.timeutil import posix_tz, today_index

router = APIRouter(prefix="/v1/device", tags=["device"])

MAX_FUTURE_DAYS = 1  # tolerate timezone edges, reject clearly wrong device clocks
MAX_PAST_DAYS = 30  # offline backlog older than this is stored but not scored


@router.post("/claim", response_model=DeviceClaimOut)
def claim(body: DeviceClaimIn, request: Request, db: DB) -> DeviceClaimOut:
    ip = request.client.host if request.client else "?"
    if not claim_limiter.allow(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many attempts")
    code = db.scalars(select(ClaimCode).where(ClaimCode.code_hash == sha256(body.claim_code.upper()))).first()
    if code is None or code.used_at is not None or code.expires_at <= utcnow():
        # 410 tells the firmware to discard the code (cloud.c try_claim)
        raise HTTPException(status.HTTP_410_GONE, "claim code invalid or expired")
    code.used_at = utcnow()

    token = new_token()
    dev = db.scalars(select(Device).where(Device.device_id == body.device_id)).first()
    if dev is None:
        dev = Device(device_id=body.device_id, child_id=code.child_id, token_hash=sha256(token))
        db.add(dev)
    else:
        # Re-pairing (factory reset, new family, or a revoked device): rotate the token
        dev.child_id = code.child_id
        dev.token_hash = sha256(token)
        dev.revoked_at = None
        dev.paired_at = utcnow()
    dev.fw_version = body.fw_version or None
    dev.last_seen_at = utcnow()
    db.commit()
    return DeviceClaimOut(device_token=token)


@router.post("/events", response_model=DeviceEventsOut)
def events(body: DeviceEventsIn, background: BackgroundTasks, db: DB, dev: CurrentDevice) -> DeviceEventsOut:
    if body.device_id != dev.device_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "device id mismatch")
    child = dev.child
    today = today_index(child.family.tz)
    game = Game(db, child)
    accepted = duplicates = 0

    for ev in sorted(body.events, key=lambda e: e.seq):
        if db.get(DeviceEvent, ev.event_id) is not None:
            duplicates += 1  # resend after a lost ack: idempotent
            continue
        ts = datetime.fromtimestamp(ev.ts, UTC) if ev.ts > 0 else None
        db.add(
            DeviceEvent(
                event_id=ev.event_id,
                device_pk=dev.id,
                seq=ev.seq,
                type=ev.type,
                ts=ts,
                day_index=ev.day_index,
                routine_id=ev.routine_id or None,
                step=ev.step,
                fast=ev.fast,
            )
        )
        accepted += 1

        if ev.type == "boot" or not (today - MAX_PAST_DAYS <= ev.day_index <= today + MAX_FUTURE_DAYS):
            continue
        ref = str(ev.event_id)
        if ev.type == "window_open":
            game.window_open(ev.routine_id, ev.day_index)
        elif ev.type == "step_done":
            game.step_done(ev.routine_id, ev.step, ev.day_index, ref, ts)
        elif ev.type == "quest_complete":
            game.quest_complete(ev.routine_id, ev.step, ev.day_index, ref, ts, ev.fast)
        elif ev.type == "step_undone":
            game.step_undone(ev.routine_id, ev.step, ev.day_index, ref, ts)
        elif ev.type == "quest_expired":
            game.quest_expired(ev.routine_id, ev.day_index, ts)

    try:
        db.commit()
    except IntegrityError as e:
        # Concurrent upload of the same batch: let the device retry, it will see duplicates
        db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "retry") from e

    if game.outcomes:
        background.add_task(dispatch_in_new_session, game.outcomes)
    return DeviceEventsOut(accepted=accepted, duplicates=duplicates)


def device_config(db, dev: Device) -> dict:
    child = dev.child
    tz = child.family.tz
    today = today_index(tz)
    routines = [r for r in child.routines if not r.archived]
    body: dict = {
        "tz": posix_tz(tz),
        "volume": dev.volume,
        "brightness": dev.brightness,
        "level": child.level,
        "week_stars": week_stars(db, child.id, today),
        "routines": [
            {
                "id": r.id,
                "start_min": r.start_min,
                "end_min": r.end_min,
                "days": r.days_mask,
                "buttons": [s.button for s in r.steps],
            }
            for r in routines
        ],
    }
    if db.get(PauseDay, (child.id, today)) is not None:
        body["paused_day"] = today
    if child.anim_seq > 0 and child.anim_type:
        body["anim"] = {"seq": child.anim_seq, "type": child.anim_type}
    s = get_settings()
    if s.fw_latest_version and s.fw_latest_url:
        body["ota"] = {"version": s.fw_latest_version, "url": s.fw_latest_url}
    # Content hash as version: the firmware echoes it in If-None-Match
    body["version"] = zlib.crc32(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()) or 1
    return body


@router.get("/config")
def config(
    response: Response,
    db: DB,
    dev: CurrentDevice,
    if_none_match: str | None = Header(default=None),
    x_fw_version: str | None = Header(default=None),
):
    if x_fw_version:
        dev.fw_version = x_fw_version[:32]
    body = device_config(db, dev)
    db.commit()
    etag = f'"{body["version"]}"'
    if if_none_match == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-store"
    return body
