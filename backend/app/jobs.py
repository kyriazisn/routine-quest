"""
Periodic jobs. Run every minute: `python -m app.cli run-jobs --loop 60` (sidecar / cron).

close_expired_windows: a device that is offline cannot report QUEST_EXPIRED, so the server
closes windows itself (P4: "notify me if the routine was not completed").
"""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.game import Game, Outcome, scheduled_routines
from app.models import Child, PauseDay, QuestDay
from app.timeutil import minute_of_day, today_index

log = logging.getLogger("rq.jobs")


def close_expired_windows(db: Session, now: datetime | None = None) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for child in db.scalars(select(Child)):
        routines = [r for r in child.routines if not r.archived]
        if not routines:
            continue
        tz = child.family.tz
        t = today_index(tz, now)
        m = minute_of_day(tz, now)
        game = Game(db, child)
        for day in (t - 1, t):  # yesterday's windows have all ended; today's only once past end_min
            if db.get(PauseDay, (child.id, day)) is not None:
                continue
            for r in scheduled_routines(routines, day):
                if day == t and m < r.end_min:
                    continue
                q = db.scalars(
                    select(QuestDay).where(
                        QuestDay.child_id == child.id, QuestDay.routine_id == r.id, QuestDay.day_index == day
                    )
                ).first()
                if q is None or q.status == "in_progress":
                    game.quest_expired(r.id, day, None)
        outcomes.extend(game.outcomes)
    db.commit()
    return outcomes
