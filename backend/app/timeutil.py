"""
Day/time helpers shared with the firmware contract:
  - day_index = local days since 1970-01-01 (firmware qe_days_from_civil)
  - weekday 0 = Monday (firmware qe_clock_t.weekday)
  - weeks start on Monday (firmware qe_week_id)
"""

from datetime import date, datetime, timedelta
from functools import lru_cache
from importlib import resources
from zoneinfo import ZoneInfo, available_timezones

EPOCH = date(1970, 1, 1)


def day_index_of(d: date) -> int:
    return (d - EPOCH).days


def date_of(day_index: int) -> date:
    return EPOCH + timedelta(days=day_index)


def weekday_of(day_index: int) -> int:
    return date_of(day_index).weekday()  # Monday = 0, same as firmware


def week_start(day_index: int) -> int:
    return day_index - weekday_of(day_index)


def local_now(tz: str, now: datetime | None = None) -> datetime:
    z = ZoneInfo(tz)
    return now.astimezone(z) if now else datetime.now(z)


def today_index(tz: str, now: datetime | None = None) -> int:
    return day_index_of(local_now(tz, now).date())


def minute_of_day(tz: str, now: datetime | None = None) -> int:
    t = local_now(tz, now)
    return t.hour * 60 + t.minute


def is_valid_tz(tz: str) -> bool:
    return tz in _valid_tzs()


@lru_cache
def _valid_tzs() -> frozenset[str]:
    return frozenset(available_timezones())


@lru_cache
def posix_tz(iana: str) -> str:
    """
    POSIX TZ string for the device (newlib setenv("TZ")), e.g. Europe/Athens ->
    "EET-2EEST,M3.5.0/3,M10.5.0/4". Read from the footer of the TZif v2+ file shipped
    with the tzdata package, so DST rules stay correct when tzdata updates.
    """
    parts = iana.split("/")
    pkg = "tzdata.zoneinfo" + ("." + ".".join(parts[:-1]) if len(parts) > 1 else "")
    data = resources.files(pkg).joinpath(parts[-1]).read_bytes()
    footer = data.rstrip(b"\n").rsplit(b"\n", 1)[-1].decode("ascii")
    if not footer:
        raise ValueError(f"no POSIX footer for {iana}")
    return footer
