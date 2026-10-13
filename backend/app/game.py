"""
Server-side game rules — the source of truth for XP, levels, stars, streaks and rewards
(docs/02-game-design.md §4). The device runs the same state machine for instant feedback
and reconciles from /v1/device/config.

All mutations are append-only ledger entries, so an undo is a compensating entry, never a delete.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Child, PauseDay, QuestDay, Reward, Routine, StarEntry, XpEntry, utcnow
from app.timeutil import week_start, weekday_of

XP_STEP = 10
XP_QUEST_BONUS = 20
XP_PERFECT_DAY = 20
LEVEL_THRESHOLDS = [0, 150, 400, 800, 1400]
LEVEL_STEP_AFTER = 800
RING_STARS = 12
SHIELDS_PER_WEEK = 1
STREAK_LOOKBACK_DAYS = 400


# --------------------------------------------------------------------------- levels


def level_for_xp(xp: int) -> int:
    level = 1
    for i, threshold in enumerate(LEVEL_THRESHOLDS):
        if xp >= threshold:
            level = i + 1
    if xp >= LEVEL_THRESHOLDS[-1]:
        level = len(LEVEL_THRESHOLDS) + (xp - LEVEL_THRESHOLDS[-1]) // LEVEL_STEP_AFTER
    return level


def xp_for_level(level: int) -> int:
    if level <= len(LEVEL_THRESHOLDS):
        return LEVEL_THRESHOLDS[level - 1]
    return LEVEL_THRESHOLDS[-1] + (level - len(LEVEL_THRESHOLDS)) * LEVEL_STEP_AFTER


# --------------------------------------------------------------------------- balances


def xp_total(db: Session, child_id: uuid.UUID) -> int:
    return int(
        db.scalar(select(func.coalesce(func.sum(XpEntry.delta), 0)).where(XpEntry.child_id == child_id))
    )


def star_balance(db: Session, child_id: uuid.UUID) -> int:
    return int(
        db.scalar(select(func.coalesce(func.sum(StarEntry.delta), 0)).where(StarEntry.child_id == child_id))
    )


def week_stars(db: Session, child_id: uuid.UUID, today: int) -> int:
    """Stars earned this week (display on the device ring), not affected by redemptions."""
    ws = week_start(today)
    n = db.scalar(
        select(func.coalesce(func.sum(StarEntry.delta), 0)).where(
            StarEntry.child_id == child_id,
            StarEntry.reason.in_(("quest_complete", "quest_undo")),
            StarEntry.day_index >= ws,
            StarEntry.day_index < ws + 7,
        )
    )
    return max(0, min(RING_STARS, int(n)))


def active_reward(db: Session, child_id: uuid.UUID) -> Reward | None:
    return db.scalars(
        select(Reward)
        .where(Reward.child_id == child_id, Reward.archived.is_(False))
        .order_by(Reward.position, Reward.id)
        .limit(1)
    ).first()


# --------------------------------------------------------------------------- schedule


def scheduled_routines(routines: list[Routine], day_index: int) -> list[Routine]:
    wd = weekday_of(day_index)
    return [r for r in routines if not r.archived and (r.days_mask >> wd) & 1]


def full_mask(routine: Routine) -> int:
    return (1 << len(routine.steps)) - 1


# --------------------------------------------------------------------------- outcomes


@dataclass
class Outcome:
    """Things the caller should notify about after commit."""

    kind: str  # step_done | quest_complete | quest_expired | reward_ready | level_up
    child_id: uuid.UUID
    routine_id: int | None = None
    data: dict = field(default_factory=dict)
    event_ts: datetime | None = None


# --------------------------------------------------------------------------- engine


class Game:
    def __init__(self, db: Session, child: Child):
        self.db = db
        self.child = child
        self.outcomes: list[Outcome] = []
        self._routines = {r.id: r for r in child.routines}

    # ---- helpers

    def _quest(self, routine: Routine, day_index: int) -> QuestDay:
        q = self.db.scalars(
            select(QuestDay).where(
                QuestDay.child_id == self.child.id,
                QuestDay.routine_id == routine.id,
                QuestDay.day_index == day_index,
            )
        ).first()
        if q is None:
            q = QuestDay(
                child_id=self.child.id,
                routine_id=routine.id,
                day_index=day_index,
                done_mask=0,
                status="in_progress",
            )
            self.db.add(q)
            self.db.flush()
        return q

    def _xp(self, delta: int, reason: str, ref: str, day_index: int) -> None:
        self.db.add(XpEntry(child_id=self.child.id, delta=delta, reason=reason, ref=ref, day_index=day_index))

    def _star(self, delta: int, reason: str, ref: str, day_index: int) -> None:
        self.db.add(
            StarEntry(child_id=self.child.id, delta=delta, reason=reason, ref=ref, day_index=day_index)
        )

    def _perfect_day_awarded(self, day_index: int) -> int:
        return int(
            self.db.scalar(
                select(func.coalesce(func.sum(XpEntry.delta), 0)).where(
                    XpEntry.child_id == self.child.id,
                    XpEntry.reason.in_(("perfect_day", "perfect_day_undo")),
                    XpEntry.day_index == day_index,
                )
            )
        )

    def _day_complete(self, day_index: int) -> bool:
        sched = scheduled_routines(list(self._routines.values()), day_index)
        if not sched:
            return False
        done = set(
            self.db.scalars(
                select(QuestDay.routine_id).where(
                    QuestDay.child_id == self.child.id,
                    QuestDay.day_index == day_index,
                    QuestDay.status == "complete",
                )
            )
        )
        return all(r.id in done for r in sched)

    def _after_change(self, day_index: int, ts: datetime | None) -> None:
        self.db.flush()
        # perfect day
        awarded = self._perfect_day_awarded(day_index)
        complete = self._day_complete(day_index)
        if complete and awarded <= 0:
            self._xp(XP_PERFECT_DAY, "perfect_day", f"day:{day_index}", day_index)
        elif not complete and awarded > 0:
            self._xp(-XP_PERFECT_DAY, "perfect_day_undo", f"day:{day_index}", day_index)
        self.db.flush()

        # level (only announce increases; an undo may silently lower it)
        new_level = level_for_xp(xp_total(self.db, self.child.id))
        if new_level > self.child.level:
            self.child.level = new_level
            self.child.anim_seq += 1
            self.child.anim_type = "level_up"
            self.outcomes.append(Outcome("level_up", self.child.id, data={"level": new_level}, event_ts=ts))
        elif new_level < self.child.level:
            self.child.level = new_level

        self.check_treasure(ts)

    def check_treasure(self, ts: datetime | None = None) -> None:
        reward = active_reward(self.db, self.child.id)
        if reward is None:
            return
        balance = star_balance(self.db, self.child.id)
        if balance >= reward.cost and self.child.treasure_signaled_reward_id != reward.id:
            self.child.treasure_signaled_reward_id = reward.id
            self.child.anim_seq += 1
            self.child.anim_type = "treasure"
            self.outcomes.append(
                Outcome(
                    "reward_ready",
                    self.child.id,
                    data={"reward": reward.name, "icon": reward.icon, "cost": reward.cost},
                    event_ts=ts,
                )
            )
        elif balance < reward.cost and self.child.treasure_signaled_reward_id == reward.id:
            self.child.treasure_signaled_reward_id = None  # an undo took the star back

    # ---- events from the device

    def step_done(self, routine_id: int, step: int, day_index: int, ref: str, ts: datetime | None) -> None:
        r = self._routines.get(routine_id)
        if r is None or step >= len(r.steps):
            return
        q = self._quest(r, day_index)
        bit = 1 << step
        if q.done_mask & bit:
            return
        q.done_mask |= bit
        if q.status == "expired":
            q.status = "in_progress"  # late upload of a press made inside the window
        self._xp(XP_STEP, "step", ref, day_index)
        self.outcomes.append(
            Outcome(
                "step_done",
                self.child.id,
                r.id,
                {
                    "step": r.steps[step].label,
                    "icon": r.steps[step].icon,
                    "done": bin(q.done_mask).count("1"),
                    "total": len(r.steps),
                },
                ts,
            )
        )
        self._after_change(day_index, ts)

    def quest_complete(
        self, routine_id: int, step: int, day_index: int, ref: str, ts: datetime | None, fast: bool
    ) -> None:
        r = self._routines.get(routine_id)
        if r is None:
            return
        q = self._quest(r, day_index)
        bit = 1 << step if step < len(r.steps) else 0
        if bit and not q.done_mask & bit:
            q.done_mask |= bit
            self._xp(XP_STEP, "step", ref, day_index)
        if q.status == "complete":
            return
        q.done_mask = full_mask(r)
        q.status = "complete"
        q.fast = fast
        q.completed_at = ts or utcnow()
        self._xp(XP_QUEST_BONUS, "quest_complete", ref, day_index)
        self._star(1, "quest_complete", ref, day_index)
        self.outcomes.append(Outcome("quest_complete", self.child.id, r.id, {"fast": fast}, ts))
        self._after_change(day_index, ts)

    def step_undone(self, routine_id: int, step: int, day_index: int, ref: str, ts: datetime | None) -> None:
        r = self._routines.get(routine_id)
        if r is None or step >= len(r.steps):
            return
        q = self._quest(r, day_index)
        bit = 1 << step
        if not q.done_mask & bit:
            return
        q.done_mask &= ~bit
        self._xp(-XP_STEP, "step_undo", ref, day_index)
        if q.status == "complete":
            q.status = "in_progress"
            q.completed_at = None
            q.fast = False
            self._xp(-XP_QUEST_BONUS, "quest_undo", ref, day_index)
            if star_balance(self.db, self.child.id) > 0:  # never push the wallet below zero
                self._star(-1, "quest_undo", ref, day_index)
        self._after_change(day_index, ts)

    def quest_expired(self, routine_id: int, day_index: int, ts: datetime | None) -> None:
        r = self._routines.get(routine_id)
        if r is None:
            return
        q = self._quest(r, day_index)
        if q.status == "in_progress":
            q.status = "expired"
            self.outcomes.append(
                Outcome(
                    "quest_expired",
                    self.child.id,
                    r.id,
                    {"done": bin(q.done_mask).count("1"), "total": len(r.steps)},
                    ts,
                )
            )

    def window_open(self, routine_id: int, day_index: int) -> None:
        r = self._routines.get(routine_id)
        if r is not None:
            self._quest(r, day_index)


# --------------------------------------------------------------------------- streak


def streak(db: Session, child: Child, today: int) -> dict:
    """
    Consecutive successful days ending today (if already complete) or yesterday.
    A day counts if all its scheduled quests are complete. Paused days and days with
    nothing scheduled are skipped. One shield per Monday-based week covers one missed day.
    MVP limitation: uses the *current* schedule for past days (no schedule history).
    """
    routines = [r for r in child.routines if not r.archived]
    if not routines:
        return {"days": 0, "shields_left": SHIELDS_PER_WEEK}

    since = today - STREAK_LOOKBACK_DAYS
    paused = set(
        db.scalars(
            select(PauseDay.day_index).where(PauseDay.child_id == child.id, PauseDay.day_index >= since)
        )
    )
    complete: dict[int, set[int]] = {}
    for rid, d in db.execute(
        select(QuestDay.routine_id, QuestDay.day_index).where(
            QuestDay.child_id == child.id, QuestDay.status == "complete", QuestDay.day_index >= since
        )
    ):
        complete.setdefault(d, set()).add(rid)

    def day_ok(d: int) -> bool | None:
        if d in paused:
            return None
        sched = scheduled_routines(routines, d)
        if not sched:
            return None
        return all(r.id in complete.get(d, set()) for r in sched)

    shields_used: dict[int, int] = {}
    count = 0
    d = today
    if day_ok(today) is not True:
        d = today - 1  # today still in progress: does not break the streak
    first_activity = min([*complete.keys(), today])
    while d >= since and d >= first_activity:
        ok = day_ok(d)
        if ok is True:
            count += 1
        elif ok is False:
            wk = week_start(d)
            if shields_used.get(wk, 0) < SHIELDS_PER_WEEK:
                shields_used[wk] = shields_used.get(wk, 0) + 1
            else:
                break
        d -= 1
    used_this_week = shields_used.get(week_start(today), 0)
    return {"days": count, "shields_left": max(0, SHIELDS_PER_WEEK - used_this_week)}
