from datetime import date

import pytest

from app.game import level_for_xp, xp_for_level
from app.timeutil import day_index_of, posix_tz, week_start, weekday_of


@pytest.mark.parametrize(
    ("xp", "level"),
    [
        (0, 1),
        (149, 1),
        (150, 2),
        (399, 2),
        (400, 3),
        (800, 4),
        (1399, 4),
        (1400, 5),
        (2199, 5),
        (2200, 6),
        (3000, 7),
    ],
)
def test_levels_match_game_design(xp, level):
    assert level_for_xp(xp) == level


def test_xp_for_level_roundtrip():
    for lvl in range(1, 12):
        assert level_for_xp(xp_for_level(lvl)) == lvl


def test_day_index_matches_firmware():
    # firmware/test/host: MON = 20738 for 2026-10-12, weekday 0 = Monday
    assert day_index_of(date(2026, 10, 12)) == 20738
    assert weekday_of(20738) == 0
    assert week_start(20738 + 6) == 20738
    assert day_index_of(date(1970, 1, 1)) == 0


def test_posix_tz_for_device():
    assert posix_tz("Europe/Athens") == "EET-2EEST,M3.5.0/3,M10.5.0/4"  # same string as the Wokwi build
    assert posix_tz("UTC") == "UTC0"
