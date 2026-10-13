"""
Parent notifications via Web Push (VAPID). Payloads carry only the child's nickname and
the quest/reward name — no other personal data (docs/09).
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.game import Outcome
from app.models import Child, Parent, PushSubscription, Routine, utcnow
from app.timeutil import minute_of_day

log = logging.getLogger("rq.notify")


@dataclass
class PushMessage:
    title: str
    body: str
    tag: str
    url: str = "/"


def in_quiet_hours(parent: Parent, tz: str) -> bool:
    if parent.quiet_start_min is None or parent.quiet_end_min is None:
        return False
    m = minute_of_day(tz)
    s, e = parent.quiet_start_min, parent.quiet_end_min
    return s <= m < e if s < e else (m >= s or m < e)  # window may cross midnight


def build_message(o: Outcome, child: Child, routine: Routine | None) -> PushMessage | None:
    name = child.nickname
    quest = routine.name if routine else "quest"
    if o.kind == "step_done":
        return PushMessage(
            "Routine Quest",
            f"{o.data['icon']} {name}: {o.data['step']} ✓ ({o.data['done']}/{o.data['total']})",
            tag=f"quest-{o.routine_id}",
        )
    if o.kind == "quest_complete":
        fast = " ⚡" if o.data.get("fast") else ""
        return PushMessage(
            "Routine Quest", f"🎉 {name} ολοκλήρωσε: {quest}!{fast}", tag=f"quest-{o.routine_id}"
        )
    if o.kind == "quest_expired":
        return PushMessage(
            "Routine Quest",
            f"⏰ {quest}: έκλεισε με {o.data['done']}/{o.data['total']} βήματα.",
            tag=f"quest-{o.routine_id}",
        )
    if o.kind == "reward_ready":
        return PushMessage(
            "Routine Quest",
            f"{o.data['icon']} {name} μάζεψε {o.data['cost']} ⭐ — «{o.data['reward']}» είναι έτοιμο!",
            tag="reward",
            url="/rewards",
        )
    if o.kind == "level_up":
        return PushMessage("Routine Quest", f"🌈 {name} ανέβηκε στο Level {o.data['level']}!", tag="level")
    return None


def should_notify(o: Outcome, routine: Routine | None) -> bool:
    max_age = timedelta(minutes=get_settings().notify_max_age_min)
    if o.event_ts is not None and utcnow() - o.event_ts > max_age:
        return False  # offline backlog: don't wake the parent for old news
    if o.kind in ("reward_ready", "level_up"):
        return True
    if routine is None:
        return False
    if routine.notify_mode == "mute":
        return False
    if o.kind == "step_done":
        return routine.notify_mode == "each_step"
    if o.kind == "quest_complete":
        return True
    if o.kind == "quest_expired":
        return routine.notify_expired
    return False


# Pluggable sender so tests can capture messages: (subscription, message) -> keep_subscription
Sender = Callable[[PushSubscription, PushMessage], bool]


def webpush_sender(sub: PushSubscription, msg: PushMessage) -> bool:
    from pywebpush import WebPushException, webpush

    s = get_settings()
    if not s.vapid_private_key:
        log.warning("VAPID key not configured; push skipped: %s", msg.body)
        return True
    try:
        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=json.dumps(msg.__dict__, ensure_ascii=False),
            vapid_private_key=s.vapid_private_key,
            vapid_claims={"sub": s.vapid_subject},
            ttl=3600,
        )
        return True
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):  # subscription expired or unsubscribed
            return False
        log.warning("web push failed (%s): %s", status, e)
        return True


_sender: Sender = webpush_sender


def set_sender(sender: Sender) -> None:
    global _sender
    _sender = sender


def dispatch(db: Session, outcomes: list[Outcome]) -> int:
    """Send pushes for outcomes. Call after the transaction that produced them is committed."""
    sent = 0
    for o in outcomes:
        child = db.get(Child, o.child_id)
        if child is None:
            continue
        routine = db.get(Routine, o.routine_id) if o.routine_id else None
        if not should_notify(o, routine):
            continue
        msg = build_message(o, child, routine)
        if msg is None:
            continue
        tz = child.family.tz
        for parent in child.family.parents:
            if in_quiet_hours(parent, tz):
                continue
            subs = db.scalars(select(PushSubscription).where(PushSubscription.parent_id == parent.id)).all()
            for sub in subs:
                if _sender(sub, msg):
                    sent += 1
                else:
                    db.delete(sub)
    db.commit()
    return sent


def dispatch_in_new_session(outcomes: list[Outcome]) -> None:
    """BackgroundTasks entry point: uses its own DB session."""
    from app.db import session_factory

    with session_factory()() as db:
        try:
            dispatch(db, outcomes)
        except Exception:
            log.exception("notification dispatch failed")
