import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

# ----------------------------------------------------------------- device API (firmware contract)

DeviceEventType = Literal[
    "window_open", "step_done", "step_undone", "quest_complete", "quest_expired", "boot"
]


class DeviceClaimIn(BaseModel):
    device_id: str = Field(pattern=r"^rq-[0-9a-f]{12}$")
    claim_code: str = Field(min_length=6, max_length=64)
    fw_version: str = Field(default="", max_length=32)


class DeviceClaimOut(BaseModel):
    device_token: str


class DeviceEventIn(BaseModel):
    event_id: uuid.UUID
    seq: int = Field(ge=0)
    type: DeviceEventType
    ts: int = Field(ge=0, description="unix seconds, 0 if the device had no valid time")
    day_index: int = Field(ge=0)
    routine_id: int = Field(ge=0)
    step: int = Field(ge=0, le=3)
    fast: bool = False


class DeviceEventsIn(BaseModel):
    device_id: str
    events: list[DeviceEventIn] = Field(max_length=50)


class DeviceEventsOut(BaseModel):
    accepted: int
    duplicates: int


# ----------------------------------------------------------------- auth


class MagicLinkIn(BaseModel):
    email: EmailStr


class VerifyIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


# ----------------------------------------------------------------- parent API


class ParentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    quiet_start_min: int | None
    quiet_end_min: int | None


class ChildIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=40)
    avatar: str = Field(default="🦊", max_length=16)


class ChildPatch(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=40)
    avatar: str | None = Field(default=None, max_length=16)


class ChildOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    nickname: str
    avatar: str
    level: int


class MeOut(BaseModel):
    parent: ParentOut
    family_tz: str
    children: list[ChildOut]


class MePatch(BaseModel):
    quiet_start_min: int | None = Field(default=None, ge=0, le=1439)
    quiet_end_min: int | None = Field(default=None, ge=0, le=1439)
    family_tz: str | None = None


class DeleteMeIn(BaseModel):
    confirm: Literal["ΔΙΑΓΡΑΦΗ", "DELETE"]


class InviteIn(BaseModel):
    email: EmailStr


class StepIn(BaseModel):
    button: int = Field(ge=0, le=3)
    icon: str = Field(min_length=1, max_length=16)
    label: str = Field(min_length=1, max_length=40)


class RoutineIn(BaseModel):
    id: int | None = None  # keep the id when editing an existing routine
    name: str = Field(min_length=1, max_length=40)
    icon: str = Field(default="🌅", max_length=16)
    start_min: int = Field(ge=0, le=1439)
    end_min: int = Field(ge=1, le=1440)
    days_mask: int = Field(ge=1, le=127)
    steps: list[StepIn] = Field(min_length=1, max_length=4)
    notify_mode: Literal["each_step", "complete_only", "mute"] = "complete_only"
    notify_expired: bool = True

    @model_validator(mode="after")
    def check(self):
        if self.start_min >= self.end_min:
            raise ValueError("start_min must be before end_min (windows cannot cross midnight)")
        buttons = [s.button for s in self.steps]
        if len(set(buttons)) != len(buttons):
            raise ValueError("each button can be used once per routine")
        return self


class RoutinesIn(BaseModel):
    routines: list[RoutineIn] = Field(max_length=2)

    @model_validator(mode="after")
    def no_overlap(self):
        rs = self.routines
        for i in range(len(rs)):
            for j in range(i):
                a, b = rs[i], rs[j]
                if a.days_mask & b.days_mask and a.start_min < b.end_min and b.start_min < a.end_min:
                    raise ValueError(f"routines '{a.name}' and '{b.name}' overlap")
        return self


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    position: int
    button: int
    icon: str
    label: str


class RoutineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    icon: str
    start_min: int
    end_min: int
    days_mask: int
    notify_mode: str
    notify_expired: bool
    steps: list[StepOut]


class NotifyPatch(BaseModel):
    notify_mode: Literal["each_step", "complete_only", "mute"] | None = None
    notify_expired: bool | None = None


class QuestTodayOut(BaseModel):
    routine: RoutineOut
    scheduled_today: bool
    status: Literal["upcoming", "active", "in_progress", "complete", "expired", "paused", "not_today"]
    done_mask: int
    fast: bool


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    device_id: str
    fw_version: str | None
    volume: int
    brightness: int
    last_seen_at: datetime | None
    online: bool = False


class TodayOut(BaseModel):
    child: ChildOut
    date: str
    paused: bool
    quests: list[QuestTodayOut]
    xp: int
    level: int
    xp_next_level: int
    stars: int
    week_stars: int
    streak_days: int
    shields_left: int
    devices: list[DeviceOut]


class HistoryQuestOut(BaseModel):
    routine_id: int
    routine_name: str
    status: str
    done: int
    total: int
    fast: bool
    xp: int


class HistoryDayOut(BaseModel):
    date: str
    paused: bool
    quests: list[HistoryQuestOut]


class RewardIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    icon: str = Field(default="🎁", max_length=16)
    cost: int = Field(ge=1, le=100)
    repeatable: bool = False
    position: int = 0


class RewardPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    icon: str | None = Field(default=None, max_length=16)
    cost: int | None = Field(default=None, ge=1, le=100)
    repeatable: bool | None = None
    position: int | None = None


class RewardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    icon: str
    cost: int
    repeatable: bool
    position: int
    archived: bool


class RewardsOut(BaseModel):
    stars: int
    active_reward_id: uuid.UUID | None
    rewards: list[RewardOut]


class ClaimCodeOut(BaseModel):
    code: str
    expires_at: datetime


class DevicePatch(BaseModel):
    volume: int | None = Field(default=None, ge=0, le=3)
    brightness: int | None = Field(default=None, ge=0, le=3)


class PauseIn(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(max_length=1024)
    keys: dict[str, str]

    @field_validator("endpoint")
    @classmethod
    def https_only(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("push endpoint must be https")
        return v

    @field_validator("keys")
    @classmethod
    def has_keys(cls, v: dict[str, str]) -> dict[str, str]:
        if "p256dh" not in v or "auth" not in v:
            raise ValueError("keys.p256dh and keys.auth are required")
        return v
