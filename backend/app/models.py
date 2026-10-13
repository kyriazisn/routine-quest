"""
Data model. Privacy by design (docs/01 §4, docs/09):
  - the child has no account, email or birth date: only a nickname and an emoji avatar
  - secrets (sessions, magic links, claim codes, device tokens) are stored as SHA-256 hashes
  - XP and stars are append-only ledgers; balances are sums, so every change is auditable
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Family(Base):
    __tablename__ = "family"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    tz: Mapped[str] = mapped_column(String(64), default="Europe/Athens")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    parents: Mapped[list["Parent"]] = relationship(back_populates="family", cascade="all, delete-orphan")
    children: Mapped[list["Child"]] = relationship(back_populates="family", cascade="all, delete-orphan")


class Parent(Base):
    __tablename__ = "parent"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("family.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    quiet_start_min: Mapped[int | None] = mapped_column(SmallInteger)
    quiet_end_min: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    family: Mapped[Family] = relationship(back_populates="parents")
    sessions: Mapped[list["AuthSession"]] = relationship(cascade="all, delete-orphan")
    push_subscriptions: Mapped[list["PushSubscription"]] = relationship(cascade="all, delete-orphan")


class MagicLink(Base):
    __tablename__ = "magic_link"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(320), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invite_family_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("family.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    __tablename__ = "auth_session"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    parent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parent.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Child(Base):
    __tablename__ = "child"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("family.id", ondelete="CASCADE"), index=True)
    nickname: Mapped[str] = mapped_column(String(40))
    avatar: Mapped[str] = mapped_column(String(16), default="🦊")
    level: Mapped[int] = mapped_column(SmallInteger, default=1)
    # One-shot device animations (treasure / level up), deduplicated on the device by seq
    anim_seq: Mapped[int] = mapped_column(Integer, default=0)
    anim_type: Mapped[str | None] = mapped_column(String(16))
    treasure_signaled_reward_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    family: Mapped[Family] = relationship(back_populates="children")
    routines: Mapped[list["Routine"]] = relationship(
        back_populates="child", cascade="all, delete-orphan", order_by="Routine.start_min"
    )
    devices: Mapped[list["Device"]] = relationship(back_populates="child", cascade="all, delete-orphan")
    rewards: Mapped[list["Reward"]] = relationship(
        back_populates="child", cascade="all, delete-orphan", order_by="Reward.position"
    )


class Device(Base):
    __tablename__ = "device"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    device_id: Mapped[str] = mapped_column(String(32), unique=True)  # "rq-<mac>"
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    fw_version: Mapped[str | None] = mapped_column(String(32))
    volume: Mapped[int] = mapped_column(SmallInteger, default=2)
    brightness: Mapped[int] = mapped_column(SmallInteger, default=2)
    paired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    child: Mapped[Child] = relationship(back_populates="devices")

    __table_args__ = (
        CheckConstraint("volume BETWEEN 0 AND 3", name="ck_device_volume"),
        CheckConstraint("brightness BETWEEN 0 AND 3", name="ck_device_brightness"),
    )


class ClaimCode(Base):
    __tablename__ = "claim_code"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Routine(Base):
    __tablename__ = "routine"

    # Integer id: the device firmware stores it as uint32 routine_id
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    icon: Mapped[str] = mapped_column(String(16), default="🌅")
    start_min: Mapped[int] = mapped_column(SmallInteger)
    end_min: Mapped[int] = mapped_column(SmallInteger)
    days_mask: Mapped[int] = mapped_column(SmallInteger)  # bit0 = Monday ... bit6 = Sunday
    notify_mode: Mapped[str] = mapped_column(String(16), default="complete_only")
    notify_expired: Mapped[bool] = mapped_column(Boolean, default=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    child: Mapped[Child] = relationship(back_populates="routines")
    steps: Mapped[list["RoutineStep"]] = relationship(
        back_populates="routine", cascade="all, delete-orphan", order_by="RoutineStep.position"
    )

    __table_args__ = (
        CheckConstraint(
            "start_min >= 0 AND end_min <= 1440 AND start_min < end_min", name="ck_routine_window"
        ),
        CheckConstraint("days_mask BETWEEN 1 AND 127", name="ck_routine_days"),
        CheckConstraint("notify_mode IN ('each_step','complete_only','mute')", name="ck_routine_notify"),
    )


class RoutineStep(Base):
    __tablename__ = "routine_step"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    routine_id: Mapped[int] = mapped_column(ForeignKey("routine.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(SmallInteger)
    button: Mapped[int] = mapped_column(SmallInteger)  # 0..3 (red, blue, green, yellow)
    icon: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(40))

    routine: Mapped[Routine] = relationship(back_populates="steps")

    __table_args__ = (
        UniqueConstraint("routine_id", "position"),
        UniqueConstraint("routine_id", "button"),
        CheckConstraint("button BETWEEN 0 AND 3", name="ck_step_button"),
        CheckConstraint("position BETWEEN 0 AND 3", name="ck_step_position"),
    )


class DeviceEvent(Base):
    __tablename__ = "device_event"

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)  # idempotency key from the device
    device_pk: Mapped[uuid.UUID] = mapped_column(ForeignKey("device.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(24))
    ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    day_index: Mapped[int] = mapped_column(Integer)
    routine_id: Mapped[int | None] = mapped_column(Integer)
    step: Mapped[int] = mapped_column(SmallInteger, default=0)
    fast: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuestDay(Base):
    """Server-side state of one routine on one local day."""

    __tablename__ = "quest_day"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"))
    routine_id: Mapped[int] = mapped_column(ForeignKey("routine.id", ondelete="CASCADE"))
    day_index: Mapped[int] = mapped_column(Integer)
    done_mask: Mapped[int] = mapped_column(SmallInteger, default=0)
    status: Mapped[str] = mapped_column(String(16), default="in_progress")
    fast: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("child_id", "routine_id", "day_index"),
        CheckConstraint("status IN ('in_progress','complete','expired')", name="ck_quest_status"),
        Index("ix_quest_day_child_day", "child_id", "day_index"),
    )


class XpEntry(Base):
    __tablename__ = "xp_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(24))
    ref: Mapped[str] = mapped_column(String(64))
    day_index: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StarEntry(Base):
    __tablename__ = "star_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(24))
    ref: Mapped[str] = mapped_column(String(64))
    day_index: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Reward(Base):
    __tablename__ = "reward"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    icon: Mapped[str] = mapped_column(String(16), default="🎁")
    cost: Mapped[int] = mapped_column(SmallInteger)
    repeatable: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    child: Mapped[Child] = relationship(back_populates="rewards")

    __table_args__ = (CheckConstraint("cost BETWEEN 1 AND 100", name="ck_reward_cost"),)


class Redemption(Base):
    __tablename__ = "redemption"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    reward_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reward.id", ondelete="CASCADE"))
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"), index=True)
    stars: Mapped[int] = mapped_column(SmallInteger)
    given_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parent.id", ondelete="SET NULL"))
    given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PauseDay(Base):
    __tablename__ = "pause_day"

    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"), primary_key=True)
    day_index: Mapped[int] = mapped_column(Integer, primary_key=True)


class PushSubscription(Base):
    __tablename__ = "push_subscription"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    parent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parent.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1024), unique=True)
    p256dh: Mapped[str] = mapped_column(String(256))
    auth: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
