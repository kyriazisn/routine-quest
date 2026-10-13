from datetime import UTC, datetime, timedelta

from conftest import MORNING, Family, login

from app.models import PauseDay, QuestDay

# ------------------------------------------------------------------ auth & isolation


def test_magic_link_login_and_me(client):
    h = login(client, "Parent@Example.com")
    me = client.get("/v1/me", headers=h).json()
    assert me["parent"]["email"] == "parent@example.com"
    assert me["family_tz"] == "Europe/Athens"
    assert client.get("/v1/me").status_code == 401


def test_magic_link_is_single_use(client):
    from app import mailer

    client.post("/v1/auth/magic-link", json={"email": "a@example.com"})
    token = mailer.outbox[-1][1].split("token=")[1]
    assert client.post("/v1/auth/verify", json={"token": token}).status_code == 200
    assert client.post("/v1/auth/verify", json={"token": token}).status_code == 400


def test_magic_link_rate_limited(client):
    for _ in range(5):
        assert client.post("/v1/auth/magic-link", json={"email": "b@example.com"}).status_code == 202
    assert client.post("/v1/auth/magic-link", json={"email": "b@example.com"}).status_code == 429


def test_other_family_cannot_see_child(client, family):
    other = login(client, "stranger@example.com")
    assert client.get(f"/v1/children/{family.child_id}/today", headers=other).status_code == 404
    assert client.post(f"/v1/children/{family.child_id}/claim-codes", headers=other).status_code == 404


def test_second_parent_invite_joins_family(client, family):
    from app import mailer

    assert (
        client.post("/v1/family/invites", json={"email": "partner@example.com"}, headers=family.h).status_code
        == 202
    )
    token = mailer.outbox[-1][1].split("token=")[1]
    r = client.post("/v1/auth/verify", json={"token": token})
    assert r.status_code == 200
    assert [c["id"] for c in r.json()["children"]] == [family.child_id]


# ------------------------------------------------------------------ routines validation


def test_routine_validation(client, family):
    url = f"/v1/children/{family.child_id}/routines"
    overlap = dict(MORNING, name="Άλλο", start_min=600, end_min=800)
    assert client.put(url, json={"routines": [MORNING, overlap]}, headers=family.h).status_code == 422
    dup = dict(MORNING, steps=[MORNING["steps"][0], MORNING["steps"][0]])
    assert client.put(url, json={"routines": [dup]}, headers=family.h).status_code == 422
    midnight = dict(MORNING, start_min=1300, end_min=60)
    assert client.put(url, json={"routines": [midnight]}, headers=family.h).status_code == 422
    assert (
        client.put(url, json={"routines": [MORNING, MORNING, MORNING]}, headers=family.h).status_code == 422
    )


def test_editing_routine_keeps_id_and_archives_removed(client, family):
    url = f"/v1/children/{family.child_id}/routines"
    edited = dict(MORNING, id=family.morning, name="Πρωί", steps=MORNING["steps"][:2])
    r = client.put(url, json={"routines": [edited]}, headers=family.h)
    assert r.status_code == 200
    assert [x["id"] for x in r.json()] == [family.morning]
    assert len(r.json()[0]["steps"]) == 2
    cfg = family.config().json()
    assert [x["id"] for x in cfg["routines"]] == [family.morning]
    assert cfg["routines"][0]["buttons"] == [0, 1]


# ------------------------------------------------------------------ device claim & config


def test_claim_code_single_use_and_invalid(client, family):
    code = client.post(f"/v1/children/{family.child_id}/claim-codes", headers=family.h).json()["code"]
    body = {"device_id": "rq-aabbccddeeff", "claim_code": code}
    assert client.post("/v1/device/claim", json=body).status_code == 200
    assert client.post("/v1/device/claim", json=body).status_code == 410
    bad = {"device_id": "rq-aabbccddeeff", "claim_code": "WRONGCODE1"}
    assert client.post("/v1/device/claim", json=bad).status_code == 410


def test_config_matches_firmware_contract_and_etag(family):
    r = family.config()
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["tz"] == "EET-2EEST,M3.5.0/3,M10.5.0/4"
    assert cfg["level"] == 1 and cfg["week_stars"] == 0
    assert cfg["routines"][0] == {
        "id": family.morning,
        "start_min": 0,
        "end_min": 720,
        "days": 127,
        "buttons": [0, 1, 2, 3],
    }
    assert cfg["routines"][1]["buttons"] == [3, 1, 0]
    assert isinstance(cfg["version"], int) and r.headers["etag"] == f'"{cfg["version"]}"'
    assert family.config(etag=r.headers["etag"]).status_code == 304


def test_revoked_device_gets_401(client, family):
    dev = family.today_view()["devices"][0]
    assert dev["online"] is True
    assert client.delete(f"/v1/devices/{dev['id']}", headers=family.h).status_code == 204
    assert family.config().status_code == 401


def test_device_settings_reach_config(client, family):
    dev = family.today_view()["devices"][0]
    client.patch(f"/v1/devices/{dev['id']}", json={"volume": 0, "brightness": 1}, headers=family.h)
    cfg = family.config().json()
    assert (cfg["volume"], cfg["brightness"]) == (0, 1)


# ------------------------------------------------------------------ game over the device API


def test_full_quest_scores_and_notifies(family, pushes):
    family.subscribe()
    out = family.complete(family.morning, 4, fast=True)
    assert out == {"accepted": 5, "duplicates": 0}

    t = family.today_view()
    morning = next(q for q in t["quests"] if q["routine"]["id"] == family.morning)
    assert morning["status"] == "complete" and morning["done_mask"] == 0b1111 and morning["fast"]
    assert t["xp"] == 4 * 10 + 20  # steps + quest bonus (no perfect day: evening still open)
    assert t["stars"] == 1 and t["week_stars"] == 1
    assert pushes.bodies() == ["🎉 Λένα ολοκλήρωσε: Πρωινό quest! ⚡"]  # complete_only mode
    assert family.config().json()["week_stars"] == 1


def test_idempotent_resend(family):
    evs = [family.ev("window_open", family.morning), family.ev("step_done", family.morning, 0)]
    assert family.send(*evs) == {"accepted": 2, "duplicates": 0}
    assert family.send(*evs) == {"accepted": 0, "duplicates": 2}
    assert family.today_view()["xp"] == 10


def test_each_step_notifications(client, family, pushes):
    family.subscribe()
    client.patch(
        f"/v1/routines/{family.morning}/notifications", json={"notify_mode": "each_step"}, headers=family.h
    )
    family.complete(family.morning, 4)
    assert len(pushes.messages) == 3 + 1  # 3 step_done + quest_complete
    assert pushes.bodies()[0] == "🪥 Λένα: Δόντια ✓ (1/4)"


def test_muted_and_quiet_hours(client, family, pushes):
    family.subscribe()
    client.patch(
        f"/v1/routines/{family.morning}/notifications", json={"notify_mode": "mute"}, headers=family.h
    )
    family.complete(family.morning, 4)
    assert pushes.messages == []
    # quiet hours covering the whole day suppress everything
    client.patch("/v1/me", json={"quiet_start_min": 0, "quiet_end_min": 1439}, headers=family.h)
    family.complete(family.evening, 3)
    assert pushes.messages == []


def test_old_backlog_does_not_notify(family, pushes):
    family.subscribe()
    old = int((datetime.now(UTC) - timedelta(hours=2)).timestamp())
    family.send(
        family.ev("window_open", family.morning, ts=old),
        *[family.ev("step_done", family.morning, s, ts=old) for s in range(3)],
        family.ev("quest_complete", family.morning, 3, ts=old),
    )
    assert pushes.messages == []
    assert family.today_view()["stars"] == 1  # still scored


def test_undo_after_complete_takes_back_star_and_xp(family, db):
    family.complete(family.morning, 4)
    family.send(family.ev("step_undone", family.morning, 2))
    # Check stored state: the /today view also folds in wall-clock time (window may have ended)
    q = db.query(QuestDay).filter_by(routine_id=family.morning, day_index=family.today).one()
    assert q.status == "in_progress" and q.done_mask == 0b1011
    t = family.today_view()
    assert t["xp"] == 60 - 10 - 20 and t["stars"] == 0
    # redo the step: complete again, star returns once
    family.send(family.ev("quest_complete", family.morning, 2))
    t = family.today_view()
    assert t["xp"] == 60 and t["stars"] == 1


def test_perfect_day_bonus_and_reversal(family):
    family.complete(family.morning, 4)
    family.complete(family.evening, 3)
    assert family.today_view()["xp"] == (40 + 20) + (30 + 20) + 20
    family.send(family.ev("step_undone", family.evening, 0))
    assert family.today_view()["xp"] == (40 + 20) + (20) + 0


def test_stale_routine_id_is_stored_but_ignored(family):
    assert family.send(family.ev("step_done", 999999, 0)) == {"accepted": 1, "duplicates": 0}
    assert family.today_view()["xp"] == 0


def test_bad_device_clock_is_not_scored(family):
    family.send(family.ev("step_done", family.morning, 0, day=family.today + 10))
    assert family.today_view()["xp"] == 0


# ------------------------------------------------------------------ rewards, levels, treasure


def test_reward_ready_treasure_and_give(client, family, pushes):
    family.subscribe()
    url = f"/v1/children/{family.child_id}/rewards"
    client.post(url, json={"name": "Παιδική χαρά", "icon": "🛝", "cost": 2}, headers=family.h)
    family.complete(family.morning, 4)
    assert family.config().json().get("anim") is None
    family.complete(family.evening, 3)
    assert "🛝 Λένα μάζεψε 2 ⭐ — «Παιδική χαρά» είναι έτοιμο!" in pushes.bodies()
    anim = family.config().json()["anim"]
    assert anim["type"] == "treasure" and anim["seq"] >= 1

    rewards = client.get(url, headers=family.h).json()
    rid = rewards["active_reward_id"]
    assert rewards["stars"] == 2
    r = client.post(f"/v1/rewards/{rid}/give", headers=family.h)
    assert r.status_code == 200 and r.json()["stars"] == 0 and r.json()["rewards"] == []
    assert client.post(f"/v1/rewards/{rid}/give", headers=family.h).status_code == 409


def test_give_requires_enough_stars(client, family):
    url = f"/v1/children/{family.child_id}/rewards"
    rid = client.post(url, json={"name": "Παραμύθι", "cost": 3}, headers=family.h).json()["active_reward_id"]
    assert client.post(f"/v1/rewards/{rid}/give", headers=family.h).status_code == 409


def test_level_up_reaches_device(family, pushes):
    family.subscribe()
    # 150 XP for level 2: morning (60) + evening (50) + perfect day (20) = 130, + tomorrow's morning (60)
    family.complete(family.morning, 4)
    family.complete(family.evening, 3)
    assert family.config().json()["level"] == 1
    family.complete(family.morning, 4, day=family.today - 1)
    cfg = family.config().json()
    assert cfg["level"] == 2 and cfg["anim"]["type"] == "level_up"
    assert "🌈 Λένα ανέβηκε στο Level 2!" in pushes.bodies()


# ------------------------------------------------------------------ streak, pause, expiry


def test_streak_with_shield_and_pause(client, family, db):
    t = family.today
    for d in (t - 1, t - 2, t - 4):  # t-3 missed (shield), t-5 missed too
        family.complete(family.morning, 4, day=d)
        family.complete(family.evening, 3, day=d)
    view = family.today_view()
    # same Monday-based week decides the shield; just assert the invariants
    assert view["streak_days"] in (2, 3)
    db.add(PauseDay(child_id=view["child"]["id"], day_index=t - 3))
    db.commit()
    assert family.today_view()["streak_days"] == 3


def test_pause_day_reaches_device_config(client, family):
    today = datetime.now(UTC).astimezone().date()
    from app.timeutil import date_of

    d = date_of(family.today).isoformat()
    assert (
        client.put(f"/v1/children/{family.child_id}/pause", json={"date": d}, headers=family.h).status_code
        == 204
    )
    assert family.config().json()["paused_day"] == family.today
    assert family.today_view()["paused"] is True
    past = (today - timedelta(days=3)).isoformat()
    assert (
        client.put(f"/v1/children/{family.child_id}/pause", json={"date": past}, headers=family.h).status_code
        == 422
    )


def test_server_closes_expired_windows(family, pushes, db):
    from zoneinfo import ZoneInfo

    from app.jobs import close_expired_windows
    from app.notify import dispatch
    from app.timeutil import date_of

    family.subscribe()
    family.send(family.ev("window_open", family.morning), family.ev("step_done", family.morning, 0))
    # 13:00 Athens on the same day: the 00:00–12:00 morning window has ended
    now = datetime.combine(date_of(family.today), datetime.min.time(), ZoneInfo("Europe/Athens")) + timedelta(
        hours=13
    )
    outcomes = close_expired_windows(db, now)
    assert [o.kind for o in outcomes].count("quest_expired") >= 1
    q = db.query(QuestDay).filter_by(routine_id=family.morning, day_index=family.today).one()
    assert q.status == "expired"
    dispatch(db, outcomes)
    assert "⏰ Πρωινό quest: έκλεισε με 1/4 βήματα." in pushes.bodies()
    # running again does not notify twice
    assert [o for o in close_expired_windows(db, now) if o.routine_id == family.morning] == []


def test_late_completion_reopens_expired_quest(family, db):
    from zoneinfo import ZoneInfo

    from app.jobs import close_expired_windows
    from app.timeutil import date_of

    now = datetime.combine(date_of(family.today), datetime.min.time(), ZoneInfo("Europe/Athens")) + timedelta(
        hours=13
    )
    close_expired_windows(db, now)
    family.complete(family.morning, 4)  # offline device uploads presses made inside the window
    assert (
        next(q for q in family.today_view()["quests"] if q["routine"]["id"] == family.morning)["status"]
        == "complete"
    )


# ------------------------------------------------------------------ push subscription hygiene, privacy


def test_gone_push_subscription_is_removed(family, pushes, db):
    family.subscribe("https://push.example.com/sub/gone")
    pushes.gone.add("https://push.example.com/sub/gone")
    family.complete(family.morning, 4)
    from app.models import PushSubscription

    assert db.query(PushSubscription).count() == 0


def test_export_and_delete_account(client, family):
    family.complete(family.morning, 4)
    data = client.get("/v1/me/export", headers=family.h).json()
    assert data["children"][0]["nickname"] == "Λένα"
    assert len(data["children"][0]["xp"]) == 5
    assert client.request("DELETE", "/v1/me", json={"confirm": "nope"}, headers=family.h).status_code == 422
    assert (
        client.request("DELETE", "/v1/me", json={"confirm": "ΔΙΑΓΡΑΦΗ"}, headers=family.h).status_code == 204
    )
    assert client.get("/v1/me", headers=family.h).status_code == 401
    assert family.config().status_code == 401  # device token went with the family


def test_second_family_device_repair(client, family):
    """Factory reset + pairing to another family moves the device and rotates its token."""
    other = Family.__new__(Family)
    other.client = client
    other.h = login(client, "new-owner@example.com")
    child = client.post("/v1/children", json={"nickname": "Νίκος"}, headers=other.h).json()["id"]
    code = client.post(f"/v1/children/{child}/claim-codes", headers=other.h).json()["code"]
    r = client.post("/v1/device/claim", json={"device_id": family.device_id, "claim_code": code})
    assert r.status_code == 200
    assert family.config().status_code == 401  # old token no longer valid
