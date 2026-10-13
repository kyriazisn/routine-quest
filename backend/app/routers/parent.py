import uuid
from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from sqlalchemy import delete, select

from app.config import get_settings
from app.deps import DB, CurrentParent, owned_child
from app.game import (
    Game,
    active_reward,
    level_for_xp,
    scheduled_routines,
    star_balance,
    streak,
    week_stars,
    xp_for_level,
    xp_total,
)
from app.models import (
    Child,
    ClaimCode,
    Device,
    DeviceEvent,
    Parent,
    PauseDay,
    PushSubscription,
    QuestDay,
    Redemption,
    Reward,
    Routine,
    RoutineStep,
    StarEntry,
    XpEntry,
    utcnow,
)
from app.notify import dispatch_in_new_session
from app.routers.auth import issue_magic_link
from app.schemas import (
    ChildIn,
    ChildOut,
    ChildPatch,
    ClaimCodeOut,
    DeleteMeIn,
    DeviceOut,
    DevicePatch,
    HistoryDayOut,
    HistoryQuestOut,
    InviteIn,
    MeOut,
    MePatch,
    NotifyPatch,
    ParentOut,
    PauseIn,
    PushSubscriptionIn,
    QuestTodayOut,
    RewardIn,
    RewardOut,
    RewardPatch,
    RewardsOut,
    RoutineOut,
    RoutinesIn,
    TodayOut,
)
from app.security import new_claim_code, sha256
from app.timeutil import date_of, day_index_of, is_valid_tz, minute_of_day, today_index

router = APIRouter(prefix="/v1", tags=["parent"])

MAX_CHILDREN = 4
DEVICE_ONLINE_WINDOW = timedelta(minutes=2)


# ------------------------------------------------------------------------- me / family


def me_out(db, parent: Parent) -> MeOut:
    db.refresh(parent)
    return MeOut(
        parent=ParentOut.model_validate(parent),
        family_tz=parent.family.tz,
        children=[ChildOut.model_validate(c) for c in parent.family.children],
    )


@router.get("/me", response_model=MeOut)
def get_me(db: DB, parent: CurrentParent) -> MeOut:
    return me_out(db, parent)


@router.patch("/me", response_model=MeOut)
def patch_me(body: MePatch, db: DB, parent: CurrentParent) -> MeOut:
    fields = body.model_fields_set
    if "quiet_start_min" in fields:
        parent.quiet_start_min = body.quiet_start_min
    if "quiet_end_min" in fields:
        parent.quiet_end_min = body.quiet_end_min
    if body.family_tz is not None:
        if not is_valid_tz(body.family_tz):
            raise HTTPException(422, "unknown timezone")
        parent.family.tz = body.family_tz
    db.commit()
    return me_out(db, parent)


@router.post("/family/invites", status_code=status.HTTP_202_ACCEPTED)
def invite(body: InviteIn, db: DB, parent: CurrentParent) -> dict:
    email = body.email.lower()
    existing = db.scalars(select(Parent).where(Parent.email == email)).first()
    if existing is not None and existing.family_id != parent.family_id:
        # Same response as success: do not reveal that the address has an account elsewhere
        return {"status": "sent"}
    issue_magic_link(db, email, invite_family_id=parent.family_id)
    return {"status": "sent"}


@router.get("/me/export")
def export(db: DB, parent: CurrentParent) -> dict:
    """GDPR data portability: everything we hold about this family."""
    fam = parent.family
    out: dict = {
        "family": {"tz": fam.tz, "created_at": fam.created_at.isoformat()},
        "parents": [p.email for p in fam.parents],
        "children": [],
    }
    for c in fam.children:
        out["children"].append(
            {
                "nickname": c.nickname,
                "avatar": c.avatar,
                "level": c.level,
                "routines": [RoutineOut.model_validate(r).model_dump() for r in c.routines],
                "rewards": [RewardOut.model_validate(r).model_dump(mode="json") for r in c.rewards],
                "devices": [
                    {"device_id": d.device_id, "paired_at": d.paired_at.isoformat()} for d in c.devices
                ],
                "quests": [
                    {
                        "date": date_of(q.day_index).isoformat(),
                        "routine_id": q.routine_id,
                        "status": q.status,
                        "done_mask": q.done_mask,
                        "fast": q.fast,
                    }
                    for q in db.scalars(
                        select(QuestDay).where(QuestDay.child_id == c.id).order_by(QuestDay.day_index)
                    )
                ],
                "xp": [
                    {"delta": x.delta, "reason": x.reason, "date": date_of(x.day_index).isoformat()}
                    for x in db.scalars(select(XpEntry).where(XpEntry.child_id == c.id).order_by(XpEntry.id))
                ],
                "stars": [
                    {"delta": s.delta, "reason": s.reason, "date": date_of(s.day_index).isoformat()}
                    for s in db.scalars(
                        select(StarEntry).where(StarEntry.child_id == c.id).order_by(StarEntry.id)
                    )
                ],
            }
        )
    return out


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(body: DeleteMeIn, response: Response, db: DB, parent: CurrentParent) -> None:
    """Hard delete. The last parent takes the whole family (children, devices, history) with them."""
    fam = parent.family
    if len(fam.parents) <= 1:
        db.delete(fam)
    else:
        db.delete(parent)
    db.commit()
    response.delete_cookie("rq_session", path="/")


# ------------------------------------------------------------------------- children


@router.post("/children", response_model=ChildOut, status_code=status.HTTP_201_CREATED)
def create_child(body: ChildIn, db: DB, parent: CurrentParent) -> Child:
    if len(parent.family.children) >= MAX_CHILDREN:
        raise HTTPException(status.HTTP_409_CONFLICT, "too many children for one family")
    child = Child(family_id=parent.family_id, nickname=body.nickname.strip(), avatar=body.avatar)
    db.add(child)
    db.commit()
    return child


@router.patch("/children/{child_id}", response_model=ChildOut)
def patch_child(child_id: uuid.UUID, body: ChildPatch, db: DB, parent: CurrentParent) -> Child:
    child = owned_child(db, parent, child_id)
    if body.nickname is not None:
        child.nickname = body.nickname.strip()
    if body.avatar is not None:
        child.avatar = body.avatar
    db.commit()
    return child


# ------------------------------------------------------------------------- routines


@router.get("/children/{child_id}/routines", response_model=list[RoutineOut])
def list_routines(child_id: uuid.UUID, db: DB, parent: CurrentParent) -> list[Routine]:
    child = owned_child(db, parent, child_id)
    return [r for r in child.routines if not r.archived]


@router.put("/children/{child_id}/routines", response_model=list[RoutineOut])
def put_routines(child_id: uuid.UUID, body: RoutinesIn, db: DB, parent: CurrentParent) -> list[Routine]:
    """
    Replace the child's routines (max 2, validated like the firmware's qe_schedule_valid).
    Existing ids are kept so history and in-flight device events still match; removed
    routines are archived, not deleted.
    """
    child = owned_child(db, parent, child_id)
    current = {r.id: r for r in child.routines if not r.archived}
    keep: set[int] = set()
    for rin in body.routines:
        r = current.get(rin.id) if rin.id is not None else None
        if rin.id is not None and r is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"routine {rin.id} not found")
        if r is None:
            r = Routine(child_id=child.id)
            db.add(r)
        r.name, r.icon = rin.name, rin.icon
        r.start_min, r.end_min, r.days_mask = rin.start_min, rin.end_min, rin.days_mask
        r.notify_mode, r.notify_expired = rin.notify_mode, rin.notify_expired
        db.flush()
        db.execute(delete(RoutineStep).where(RoutineStep.routine_id == r.id))
        for pos, s in enumerate(rin.steps):
            db.add(RoutineStep(routine_id=r.id, position=pos, button=s.button, icon=s.icon, label=s.label))
        keep.add(r.id)
    for rid, r in current.items():
        if rid not in keep:
            r.archived = True
    db.commit()
    db.refresh(child)
    return [r for r in child.routines if not r.archived]


@router.patch("/routines/{routine_id}/notifications", response_model=RoutineOut)
def patch_notifications(routine_id: int, body: NotifyPatch, db: DB, parent: CurrentParent) -> Routine:
    r = db.get(Routine, routine_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "routine not found")
    owned_child(db, parent, r.child_id)
    if body.notify_mode is not None:
        r.notify_mode = body.notify_mode
    if body.notify_expired is not None:
        r.notify_expired = body.notify_expired
    db.commit()
    return r


# ------------------------------------------------------------------------- today / history


def _device_out(d: Device) -> DeviceOut:
    out = DeviceOut.model_validate(d)
    out.online = d.last_seen_at is not None and utcnow() - d.last_seen_at < DEVICE_ONLINE_WINDOW
    return out


@router.get("/children/{child_id}/today", response_model=TodayOut)
def today(child_id: uuid.UUID, db: DB, parent: CurrentParent) -> TodayOut:
    child = owned_child(db, parent, child_id)
    tz = child.family.tz
    t = today_index(tz)
    now_min = minute_of_day(tz)
    paused = db.get(PauseDay, (child.id, t)) is not None
    routines = [r for r in child.routines if not r.archived]
    sched_ids = {r.id for r in scheduled_routines(routines, t)}
    qd = {
        q.routine_id: q
        for q in db.scalars(select(QuestDay).where(QuestDay.child_id == child.id, QuestDay.day_index == t))
    }
    quests = []
    for r in routines:
        q = qd.get(r.id)
        if r.id not in sched_ids:
            st = "not_today"
        elif paused:
            st = "paused"
        elif q is not None and q.status in ("complete", "expired"):
            st = q.status
        elif now_min < r.start_min:
            st = "upcoming"
        elif now_min >= r.end_min:
            st = "expired"
        else:
            st = "in_progress" if q is not None and q.done_mask else "active"
        quests.append(
            QuestTodayOut(
                routine=RoutineOut.model_validate(r),
                scheduled_today=r.id in sched_ids,
                status=st,
                done_mask=q.done_mask if q else 0,
                fast=q.fast if q else False,
            )
        )
    xp = xp_total(db, child.id)
    lvl = level_for_xp(xp)
    sk = streak(db, child, t)
    return TodayOut(
        child=ChildOut.model_validate(child),
        date=date_of(t).isoformat(),
        paused=paused,
        quests=quests,
        xp=xp,
        level=lvl,
        xp_next_level=xp_for_level(lvl + 1),
        stars=star_balance(db, child.id),
        week_stars=week_stars(db, child.id, t),
        streak_days=sk["days"],
        shields_left=sk["shields_left"],
        devices=[_device_out(d) for d in child.devices if d.revoked_at is None],
    )


@router.get("/children/{child_id}/history", response_model=list[HistoryDayOut])
def history(child_id: uuid.UUID, db: DB, parent: CurrentParent, days: int = 7) -> list[HistoryDayOut]:
    child = owned_child(db, parent, child_id)
    days = max(1, min(days, 60))
    t = today_index(child.family.tz)
    first = t - days + 1
    routines = {r.id: r for r in child.routines}
    paused = set(
        db.scalars(
            select(PauseDay.day_index).where(PauseDay.child_id == child.id, PauseDay.day_index >= first)
        )
    )
    qds = db.scalars(select(QuestDay).where(QuestDay.child_id == child.id, QuestDay.day_index >= first)).all()
    # XP per (day, routine): each quest XP entry references the device event that caused it
    entries = db.execute(
        select(XpEntry.day_index, XpEntry.ref, XpEntry.delta).where(
            XpEntry.child_id == child.id,
            XpEntry.day_index >= first,
            XpEntry.reason.in_(("step", "step_undo", "quest_complete", "quest_undo")),
        )
    ).all()
    ref_ids = {uuid.UUID(ref) for _, ref, _ in entries}
    routine_of = (
        dict(
            db.execute(
                select(DeviceEvent.event_id, DeviceEvent.routine_id).where(DeviceEvent.event_id.in_(ref_ids))
            ).all()
        )
        if ref_ids
        else {}
    )
    xp_by_quest: dict[tuple[int, int], int] = {}
    for d, ref, delta in entries:
        rid = routine_of.get(uuid.UUID(ref))
        if rid is not None:
            xp_by_quest[(d, rid)] = xp_by_quest.get((d, rid), 0) + delta
    out = []
    for d in range(t, first - 1, -1):
        qs = [q for q in qds if q.day_index == d]
        out.append(
            HistoryDayOut(
                date=date_of(d).isoformat(),
                paused=d in paused,
                quests=[
                    HistoryQuestOut(
                        routine_id=q.routine_id,
                        routine_name=routines[q.routine_id].name,
                        status=q.status,
                        done=bin(q.done_mask).count("1"),
                        total=len(routines[q.routine_id].steps),
                        fast=q.fast,
                        xp=xp_by_quest.get((d, q.routine_id), 0),
                    )
                    for q in qs
                    if q.routine_id in routines
                ],
            )
        )
    return out


# ------------------------------------------------------------------------- pause day


def _pause_day_index(child: Child, body: PauseIn) -> int:
    try:
        d = date.fromisoformat(body.date)
    except ValueError as e:
        raise HTTPException(422, "invalid date") from e
    idx = day_index_of(d)
    t = today_index(child.family.tz)
    if not (t <= idx <= t + 60):
        raise HTTPException(422, "pause days must be today or in the future")
    return idx


@router.put("/children/{child_id}/pause", status_code=status.HTTP_204_NO_CONTENT)
def pause_day(child_id: uuid.UUID, body: PauseIn, db: DB, parent: CurrentParent) -> None:
    child = owned_child(db, parent, child_id)
    idx = _pause_day_index(child, body)
    if db.get(PauseDay, (child.id, idx)) is None:
        db.add(PauseDay(child_id=child.id, day_index=idx))
        db.commit()


@router.delete("/children/{child_id}/pause", status_code=status.HTTP_204_NO_CONTENT)
def unpause_day(child_id: uuid.UUID, body: PauseIn, db: DB, parent: CurrentParent) -> None:
    child = owned_child(db, parent, child_id)
    idx = _pause_day_index(child, body)
    p = db.get(PauseDay, (child.id, idx))
    if p is not None:
        db.delete(p)
        db.commit()


# ------------------------------------------------------------------------- rewards


def _rewards_out(db, child: Child) -> RewardsOut:
    act = active_reward(db, child.id)
    return RewardsOut(
        stars=star_balance(db, child.id),
        active_reward_id=act.id if act else None,
        rewards=[RewardOut.model_validate(r) for r in child.rewards if not r.archived],
    )


def _owned_reward(db, parent: Parent, reward_id: uuid.UUID) -> Reward:
    r = db.get(Reward, reward_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "reward not found")
    owned_child(db, parent, r.child_id)
    return r


@router.get("/children/{child_id}/rewards", response_model=RewardsOut)
def list_rewards(child_id: uuid.UUID, db: DB, parent: CurrentParent) -> RewardsOut:
    return _rewards_out(db, owned_child(db, parent, child_id))


@router.post("/children/{child_id}/rewards", response_model=RewardsOut, status_code=status.HTTP_201_CREATED)
def create_reward(
    child_id: uuid.UUID, body: RewardIn, background: BackgroundTasks, db: DB, parent: CurrentParent
) -> RewardsOut:
    child = owned_child(db, parent, child_id)
    db.add(Reward(child_id=child.id, **body.model_dump()))
    db.flush()
    g = Game(db, child)
    g.check_treasure()
    db.commit()
    if g.outcomes:
        background.add_task(dispatch_in_new_session, g.outcomes)
    db.refresh(child)
    return _rewards_out(db, child)


@router.patch("/rewards/{reward_id}", response_model=RewardsOut)
def patch_reward(reward_id: uuid.UUID, body: RewardPatch, db: DB, parent: CurrentParent) -> RewardsOut:
    r = _owned_reward(db, parent, reward_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    db.flush()
    Game(db, r.child).check_treasure()
    db.commit()
    return _rewards_out(db, r.child)


@router.delete("/rewards/{reward_id}", response_model=RewardsOut)
def archive_reward(reward_id: uuid.UUID, db: DB, parent: CurrentParent) -> RewardsOut:
    r = _owned_reward(db, parent, reward_id)
    r.archived = True
    db.commit()
    return _rewards_out(db, r.child)


@router.post("/rewards/{reward_id}/give", response_model=RewardsOut)
def give_reward(
    reward_id: uuid.UUID, background: BackgroundTasks, db: DB, parent: CurrentParent
) -> RewardsOut:
    """Parent confirms the reward was given: stars are spent, the next reward becomes active."""
    r = _owned_reward(db, parent, reward_id)
    if r.archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "reward archived")
    child = r.child
    if star_balance(db, child.id) < r.cost:
        raise HTTPException(status.HTTP_409_CONFLICT, "not enough stars yet")
    t = today_index(child.family.tz)
    db.add(Redemption(reward_id=r.id, child_id=child.id, stars=r.cost, given_by=parent.id))
    db.add(StarEntry(child_id=child.id, delta=-r.cost, reason="redemption", ref=str(r.id), day_index=t))
    if not r.repeatable:
        r.archived = True
    child.treasure_signaled_reward_id = None
    db.flush()
    g = Game(db, child)
    g.check_treasure()  # enough stars left for the next reward?
    db.commit()
    if g.outcomes:
        background.add_task(dispatch_in_new_session, g.outcomes)
    return _rewards_out(db, child)


# ------------------------------------------------------------------------- devices


@router.post(
    "/children/{child_id}/claim-codes", response_model=ClaimCodeOut, status_code=status.HTTP_201_CREATED
)
def create_claim_code(child_id: uuid.UUID, db: DB, parent: CurrentParent) -> ClaimCodeOut:
    """One-time code the PWA sends to the device over BLE (endpoint "rq-claim")."""
    child = owned_child(db, parent, child_id)
    code = new_claim_code()
    expires = utcnow() + timedelta(minutes=get_settings().claim_code_ttl_min)
    db.add(ClaimCode(child_id=child.id, code_hash=sha256(code), expires_at=expires))
    db.commit()
    return ClaimCodeOut(code=code, expires_at=expires)


def _owned_device(db, parent: Parent, device_pk: uuid.UUID) -> Device:
    d = db.get(Device, device_pk)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    owned_child(db, parent, d.child_id)
    return d


@router.patch("/devices/{device_pk}", response_model=DeviceOut)
def patch_device(device_pk: uuid.UUID, body: DevicePatch, db: DB, parent: CurrentParent) -> DeviceOut:
    d = _owned_device(db, parent, device_pk)
    if body.volume is not None:
        d.volume = body.volume
    if body.brightness is not None:
        d.brightness = body.brightness
    db.commit()
    return _device_out(d)


@router.delete("/devices/{device_pk}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_device(device_pk: uuid.UUID, db: DB, parent: CurrentParent) -> None:
    """Unpair: the device token stops working immediately (the device gets 401)."""
    d = _owned_device(db, parent, device_pk)
    d.revoked_at = utcnow()
    d.token_hash = sha256(f"revoked:{uuid.uuid4()}")
    db.commit()


# ------------------------------------------------------------------------- web push


@router.get("/push/vapid-public-key")
def vapid_public_key() -> dict:
    return {"key": get_settings().vapid_public_key}


@router.post("/push/subscriptions", status_code=status.HTTP_201_CREATED)
def subscribe(body: PushSubscriptionIn, db: DB, parent: CurrentParent) -> dict:
    sub = db.scalars(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)).first()
    if sub is None:
        sub = PushSubscription(parent_id=parent.id, endpoint=body.endpoint)
        db.add(sub)
    sub.parent_id = parent.id
    sub.p256dh, sub.auth = body.keys["p256dh"], body.keys["auth"]
    db.commit()
    return {"status": "subscribed"}


@router.delete("/push/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(body: PushSubscriptionIn, db: DB, parent: CurrentParent) -> None:
    db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == body.endpoint, PushSubscription.parent_id == parent.id
        )
    )
    db.commit()
