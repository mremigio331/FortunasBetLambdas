"""Unit tests for NFLHelper's Eastern-Time week boundary math.

Task 3.2 - asserts boundary comparisons and epoch conversions are correct and
locale-independent.

Requirements: 3.1, 5.6
"""

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from common.helpers import nfl_helper
from common.helpers.nfl_helper import NFLHelper

EASTERN = ZoneInfo("America/New_York")
EDT = timedelta(hours=-4)
EST = timedelta(hours=-5)

REPO_ROOT = Path(__file__).resolve().parents[1]

WEEK_KEYS = {
    "year",
    "season_type",
    "season_name",
    "week",
    "week_start",
    "week_end",
    "week_start_epoch",
    "week_end_epoch",
}


@pytest.fixture
def helper():
    return NFLHelper(request_id="nfl-eastern-time-test")


def _utc_epoch(year, month, day, hour):
    """Epoch seconds for an explicit UTC wall clock, used as an oracle."""
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp())


class TestEtMidnight:
    """_et_midnight builds ET-aware midnights that respect DST."""

    def test_returns_an_aware_datetime_at_midnight(self):
        result = NFLHelper._et_midnight(date(2024, 9, 8))

        assert result.tzinfo is not None
        assert result.utcoffset() is not None
        assert (result.hour, result.minute, result.second, result.microsecond) == (
            0,
            0,
            0,
            0,
        )
        assert (result.year, result.month, result.day) == (2024, 9, 8)

    @pytest.mark.parametrize(
        "day,expected_offset",
        [
            (date(2024, 8, 1), EDT),  # preseason, summer
            (date(2024, 9, 8), EDT),  # regular season opener
            (date(2024, 11, 2), EDT),  # day before fall back
            (date(2024, 11, 3), EDT),  # fall back is at 02:00, so midnight is EDT
            (date(2024, 11, 4), EST),  # first full EST day
            (date(2024, 12, 22), EST),  # late December
            (date(2025, 1, 14), EST),  # playoffs
            (date(2025, 3, 8), EST),  # day before spring forward
            (date(2025, 3, 9), EST),  # spring forward at 02:00, midnight still EST
            (date(2025, 3, 10), EDT),  # first full EDT day
        ],
    )
    def test_offset_follows_the_dst_calendar(self, day, expected_offset):
        assert NFLHelper._et_midnight(day).utcoffset() == expected_offset

    def test_fall_back_day_is_25_absolute_hours_long(self):
        """The DST-correct construction yields a 25-hour civil day.

        Adding a timedelta to an aware datetime would preserve the old offset
        and produce 24 hours here, so this pins the intended behavior. The
        comparison is made on absolute instants because subtracting two
        datetimes sharing a tzinfo yields the naive (wall-clock) difference.
        """
        before = NFLHelper._et_midnight(date(2024, 11, 3))
        after = NFLHelper._et_midnight(date(2024, 11, 4))

        assert after.timestamp() - before.timestamp() == 25 * 3600

    def test_spring_forward_day_is_23_absolute_hours_long(self):
        before = NFLHelper._et_midnight(date(2025, 3, 9))
        after = NFLHelper._et_midnight(date(2025, 3, 10))

        assert after.timestamp() - before.timestamp() == 23 * 3600


class TestGetWeekDatesForSeason:
    @pytest.mark.parametrize("season_type", [1, 2, 3])
    def test_boundaries_are_eastern_time_aware(self, helper, season_type):
        week_start, week_end = helper.get_week_dates_for_season(2024, season_type, 1)

        for boundary in (week_start, week_end):
            assert boundary.tzinfo is not None
            assert boundary.utcoffset() in (EST, EDT)
            assert boundary.tzname() in ("EST", "EDT")

    @pytest.mark.parametrize(
        "year,season_type,week,expected_start,expected_end,expected_offset",
        [
            # Preseason starts Aug 1 of the season year.
            (2024, 1, 1, "2024-08-01T00:00:00-04:00", "2024-08-07T00:00:00-04:00", EDT),
            # Regular season starts Sep 8 of the season year.
            (2024, 2, 1, "2024-09-08T00:00:00-04:00", "2024-09-14T00:00:00-04:00", EDT),
            # September weeks sit in EDT (-04:00).
            (2024, 2, 3, "2024-09-22T00:00:00-04:00", "2024-09-28T00:00:00-04:00", EDT),
            # Late-December weeks sit in EST (-05:00).
            (
                2024,
                2,
                16,
                "2024-12-22T00:00:00-05:00",
                "2024-12-28T00:00:00-05:00",
                EST,
            ),
            (
                2024,
                2,
                18,
                "2025-01-05T00:00:00-05:00",
                "2025-01-11T00:00:00-05:00",
                EST,
            ),
            # Playoffs land in January of the year AFTER the season year.
            (2024, 3, 1, "2025-01-14T00:00:00-05:00", "2025-01-20T00:00:00-05:00", EST),
        ],
    )
    def test_known_week_boundaries(
        self,
        helper,
        year,
        season_type,
        week,
        expected_start,
        expected_end,
        expected_offset,
    ):
        week_start, week_end = helper.get_week_dates_for_season(year, season_type, week)

        assert week_start.isoformat() == expected_start
        assert week_end.isoformat() == expected_end
        assert week_start.utcoffset() == expected_offset

    def test_dst_transition_is_reflected_across_the_regular_season(self, helper):
        """September weeks are -04:00 and December weeks are -05:00."""
        september_start, _ = helper.get_week_dates_for_season(2024, 2, 1)
        december_start, _ = helper.get_week_dates_for_season(2024, 2, 16)

        assert september_start.utcoffset() == EDT
        assert december_start.utcoffset() == EST

    def test_week_spans_six_days_in_civil_time(self, helper):
        week_start, week_end = helper.get_week_dates_for_season(2024, 2, 1)

        assert (week_end.date() - week_start.date()).days == 6

    def test_consecutive_weeks_are_contiguous(self, helper):
        _, week_one_end = helper.get_week_dates_for_season(2024, 2, 1)
        week_two_start, _ = helper.get_week_dates_for_season(2024, 2, 2)

        assert week_two_start.date() - week_one_end.date() == timedelta(days=1)

    @pytest.mark.parametrize(
        "year,season_type,week,expected_epoch",
        [
            # 2024-09-08 00:00 EDT == 2024-09-08 04:00 UTC
            (2024, 2, 1, _utc_epoch(2024, 9, 8, 4)),
            # 2024-12-22 00:00 EST == 2024-12-22 05:00 UTC
            (2024, 2, 16, _utc_epoch(2024, 12, 22, 5)),
            # 2025-01-14 00:00 EST == 2025-01-14 05:00 UTC
            (2024, 3, 1, _utc_epoch(2025, 1, 14, 5)),
            # 2024-08-01 00:00 EDT == 2024-08-01 04:00 UTC
            (2024, 1, 1, _utc_epoch(2024, 8, 1, 4)),
        ],
    )
    def test_epoch_conversion_matches_the_utc_instant(
        self, helper, year, season_type, week, expected_epoch
    ):
        week_start, _ = helper.get_week_dates_for_season(year, season_type, week)

        assert int(week_start.timestamp()) == expected_epoch

    def test_epoch_round_trips_back_to_the_same_eastern_wall_clock(self, helper):
        week_start, week_end = helper.get_week_dates_for_season(2024, 2, 16)

        for boundary in (week_start, week_end):
            round_tripped = datetime.fromtimestamp(boundary.timestamp(), tz=EASTERN)
            assert round_tripped == boundary
            assert round_tripped.hour == 0

    @pytest.mark.parametrize("season_type", [0, 4, -1, 99])
    def test_invalid_season_type_raises_value_error(self, helper, season_type):
        with pytest.raises(ValueError, match="Invalid season_type"):
            helper.get_week_dates_for_season(2024, season_type, 1)


class TestFindNflWeeksInRange:
    def test_output_shape_is_preserved(self, helper):
        start = _utc_epoch(2024, 9, 8, 4)
        end = _utc_epoch(2024, 10, 8, 4)

        weeks = helper.find_nfl_weeks_in_range(start, end)

        assert weeks
        for week in weeks:
            assert set(week.keys()) == WEEK_KEYS
            assert isinstance(week["year"], int)
            assert isinstance(week["season_type"], int)
            assert isinstance(week["season_name"], str)
            assert isinstance(week["week"], int)
            assert isinstance(week["week_start"], str)
            assert isinstance(week["week_end"], str)
            assert isinstance(week["week_start_epoch"], int)
            assert isinstance(week["week_end_epoch"], int)

    def test_iso_strings_carry_an_eastern_offset_and_match_their_epochs(self, helper):
        start = _utc_epoch(2024, 9, 1, 4)
        end = _utc_epoch(2025, 1, 20, 5)

        weeks = helper.find_nfl_weeks_in_range(start, end)

        assert weeks
        for week in weeks:
            parsed_start = datetime.fromisoformat(week["week_start"])
            parsed_end = datetime.fromisoformat(week["week_end"])

            assert parsed_start.utcoffset() in (EST, EDT)
            assert parsed_end.utcoffset() in (EST, EDT)
            assert int(parsed_start.timestamp()) == week["week_start_epoch"]
            assert int(parsed_end.timestamp()) == week["week_end_epoch"]
            assert week["week_start_epoch"] < week["week_end_epoch"]

    def test_results_are_sorted_by_year_season_type_and_week(self, helper):
        weeks = helper.find_nfl_weeks_in_range(
            _utc_epoch(2024, 8, 1, 4), _utc_epoch(2025, 2, 1, 5)
        )

        keys = [(w["year"], w["season_type"], w["week"]) for w in weeks]
        assert keys == sorted(keys)

    def test_returned_weeks_overlap_the_requested_range(self, helper):
        start = _utc_epoch(2024, 10, 1, 4)
        end = _utc_epoch(2024, 10, 20, 4)

        weeks = helper.find_nfl_weeks_in_range(start, end)

        assert weeks
        for week in weeks:
            assert week["week_start_epoch"] <= end
            assert week["week_end_epoch"] >= start

    def test_narrow_range_selects_the_containing_regular_season_week(self, helper):
        # 2024-10-15 12:00 ET sits inside regular-season week 6 (Oct 13 - Oct 19).
        moment = int(datetime(2024, 10, 15, 12, 0, tzinfo=EASTERN).timestamp())

        weeks = helper.find_nfl_weeks_in_range(moment, moment)
        regular = [w for w in weeks if w["season_type"] == 2]

        assert [(w["year"], w["week"]) for w in regular] == [(2024, 6)]

    def test_boundary_comparison_is_inclusive(self, helper):
        week_start, week_end = helper.get_week_dates_for_season(2024, 2, 6)
        start_epoch = int(week_start.timestamp())
        end_epoch = int(week_end.timestamp())

        at_start = helper.find_nfl_weeks_in_range(start_epoch, start_epoch)
        at_end = helper.find_nfl_weeks_in_range(end_epoch, end_epoch)

        assert (2024, 2, 6) in [
            (w["year"], w["season_type"], w["week"]) for w in at_start
        ]
        assert (2024, 2, 6) in [
            (w["year"], w["season_type"], w["week"]) for w in at_end
        ]

    def test_off_season_range_returns_no_weeks(self, helper):
        # Mid-May sits outside preseason, regular season, and playoffs.
        start = int(datetime(2024, 5, 10, 0, 0, tzinfo=EASTERN).timestamp())
        end = int(datetime(2024, 5, 20, 0, 0, tzinfo=EASTERN).timestamp())

        assert helper.find_nfl_weeks_in_range(start, end) == []

    def test_equivalent_instants_from_different_zones_yield_identical_output(
        self, helper
    ):
        """Epoch inputs describe an instant, so the caller's zone cannot matter."""
        instant = datetime(2024, 10, 15, 12, 0, tzinfo=timezone.utc)
        epochs = [
            int(instant.astimezone(zone).timestamp())
            for zone in (
                timezone.utc,
                EASTERN,
                ZoneInfo("Asia/Tokyo"),
                ZoneInfo("America/Los_Angeles"),
                ZoneInfo("Pacific/Kiritimati"),
            )
        ]

        results = [helper.find_nfl_weeks_in_range(e, e) for e in epochs]

        assert all(result == results[0] for result in results)
        assert results[0]

    def test_december_and_september_weeks_have_different_offsets_in_one_call(
        self, helper
    ):
        weeks = helper.find_nfl_weeks_in_range(
            _utc_epoch(2024, 9, 8, 4), _utc_epoch(2025, 1, 11, 5)
        )
        regular = {w["week"]: w["week_start"] for w in weeks if w["season_type"] == 2}

        assert regular[1].endswith("-04:00")
        assert regular[16].endswith("-05:00")


class _FrozenDatetime(datetime):
    """datetime subclass whose ``now`` is pinned to ``_FrozenDatetime.frozen``."""

    frozen = datetime(2024, 10, 15, 12, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.frozen.astimezone(tz) if tz else cls.frozen.replace(tzinfo=None)


@pytest.fixture
def freeze_clock(monkeypatch):
    def _freeze(moment):
        _FrozenDatetime.frozen = moment
        monkeypatch.setattr(nfl_helper, "datetime", _FrozenDatetime)

    return _freeze


class TestGetCurrentNflWeek:
    def test_resolves_the_week_containing_the_frozen_moment(self, helper, freeze_clock):
        # 2024-10-15 16:00 UTC == 12:00 ET, inside regular-season week 6.
        freeze_clock(datetime(2024, 10, 15, 16, 0, tzinfo=timezone.utc))

        current = helper.get_current_nfl_week()

        assert current is not None
        assert set(current.keys()) == WEEK_KEYS
        assert (current["year"], current["season_type"], current["week"]) == (
            2024,
            2,
            6,
        )
        assert (
            current["week_start_epoch"]
            <= int(datetime(2024, 10, 15, 16, 0, tzinfo=timezone.utc).timestamp())
            <= current["week_end_epoch"]
        )

    def test_returns_none_during_the_off_season(self, helper, freeze_clock):
        freeze_clock(datetime(2024, 5, 15, 16, 0, tzinfo=timezone.utc))

        assert helper.get_current_nfl_week() is None

    def test_resolution_depends_only_on_the_instant_not_the_clock_zone(
        self, helper, freeze_clock
    ):
        """The same instant expressed in several zones resolves to one week."""
        instant = datetime(2024, 10, 15, 16, 0, tzinfo=timezone.utc)
        resolved = []

        for zone in (
            timezone.utc,
            EASTERN,
            ZoneInfo("Asia/Tokyo"),
            ZoneInfo("America/Los_Angeles"),
        ):
            freeze_clock(instant.astimezone(zone))
            resolved.append(helper.get_current_nfl_week())

        assert all(week == resolved[0] for week in resolved)
        assert resolved[0]["week"] == 6

    def test_january_playoff_moment_resolves_to_the_postseason(
        self, helper, freeze_clock
    ):
        # 2025-01-16 is inside the 2024 postseason (Jan 14 - Jan 20).
        freeze_clock(datetime(2025, 1, 16, 17, 0, tzinfo=timezone.utc))

        current = helper.get_current_nfl_week()

        assert current is not None
        assert (current["year"], current["season_type"], current["week"]) == (
            2024,
            3,
            1,
        )


class TestGetWeekBoundaryByGameId:
    @pytest.fixture
    def stub_schedule(self, monkeypatch):
        """Stub ESPNClient.get_nfl_schedule; no live HTTP in tests."""

        def _stub(payload):
            from clients.espn_client import ESPNClient

            monkeypatch.setattr(
                ESPNClient,
                "get_nfl_schedule",
                lambda self, year: payload,
                raising=True,
            )

        return _stub

    @staticmethod
    def _schedule(game_id, week, season_type, year):
        return {
            "events": [
                {
                    "id": game_id,
                    "name": "Team A at Team B",
                    "date": "2024-12-22T18:00Z",
                    "season": {"week": week, "type": season_type, "year": year},
                }
            ]
        }

    def test_boundaries_are_eastern_time_epochs(self, helper, stub_schedule):
        stub_schedule(self._schedule("401671000", week=16, season_type=2, year=2024))

        boundary = helper.get_week_boundary_by_game_id("401671000", 2024)

        assert boundary is not None
        start_epoch, end_epoch = boundary
        # 2024-12-22 00:00 EST == 2024-12-22 05:00 UTC
        assert start_epoch == _utc_epoch(2024, 12, 22, 5)
        assert end_epoch == _utc_epoch(2024, 12, 28, 5)
        assert start_epoch < end_epoch

    def test_boundaries_match_get_week_dates_for_season(self, helper, stub_schedule):
        stub_schedule(self._schedule("401671001", week=3, season_type=2, year=2024))

        start_epoch, end_epoch = helper.get_week_boundary_by_game_id("401671001", 2024)
        week_start, week_end = helper.get_week_dates_for_season(2024, 2, 3)

        assert start_epoch == int(week_start.timestamp())
        assert end_epoch == int(week_end.timestamp())

    def test_epochs_round_trip_to_eastern_midnight(self, helper, stub_schedule):
        stub_schedule(self._schedule("401671002", week=1, season_type=3, year=2024))

        start_epoch, end_epoch = helper.get_week_boundary_by_game_id("401671002", 2024)

        for epoch in (start_epoch, end_epoch):
            in_eastern = datetime.fromtimestamp(epoch, tz=EASTERN)
            assert in_eastern.hour == 0
            assert in_eastern.utcoffset() == EST

    def test_unknown_game_id_returns_none(self, helper, stub_schedule):
        stub_schedule(self._schedule("401671003", week=1, season_type=2, year=2024))

        assert helper.get_week_boundary_by_game_id("does-not-exist", 2024) is None

    def test_empty_schedule_payload_returns_none(self, helper, stub_schedule):
        stub_schedule({})

        assert helper.get_week_boundary_by_game_id("401671004", 2024) is None

    def test_missing_week_metadata_returns_none(self, helper, stub_schedule):
        stub_schedule(self._schedule("401671005", week=None, season_type=2, year=2024))

        assert helper.get_week_boundary_by_game_id("401671005", 2024) is None


_TZ_PROBE = """
import json
from common.helpers.nfl_helper import NFLHelper

helper = NFLHelper(request_id="tz-probe")
out = {}
for season_type, week in ((1, 1), (2, 1), (2, 16), (3, 1)):
    start, end = helper.get_week_dates_for_season(2024, season_type, week)
    out[f"{season_type}-{week}"] = [
        start.isoformat(),
        end.isoformat(),
        int(start.timestamp()),
        int(end.timestamp()),
    ]
out["range"] = helper.find_nfl_weeks_in_range(1725768000, 1736053200)
print("PROBE:" + json.dumps(out, sort_keys=True))
"""


def _run_probe_under_tz(tz):
    env = dict(os.environ, TZ=tz, PYTHONPATH=str(REPO_ROOT))
    completed = subprocess.run(
        [sys.executable, "-c", _TZ_PROBE],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    # Powertools also logs JSON to stdout, so the payload is tagged.
    payload = next(
        line for line in completed.stdout.splitlines() if line.startswith("PROBE:")
    )
    return json.loads(payload[len("PROBE:") :])


@pytest.mark.skipif(
    os.name != "posix", reason="TZ environment variable is POSIX-specific"
)
def test_boundary_math_is_independent_of_the_server_time_zone():
    """Requirement 3.1: the ET offset is explicit, so the host zone is irrelevant.

    The process time zone cannot be changed reliably mid-process for
    zoneinfo-backed code, so each zone is probed in a fresh interpreter.
    """
    baseline = _run_probe_under_tz("America/New_York")

    for tz in ("UTC", "Asia/Tokyo", "America/Los_Angeles", "Pacific/Kiritimati"):
        assert _run_probe_under_tz(tz) == baseline, f"output differed under TZ={tz}"

    assert baseline["2-1"][0].endswith("-04:00")
    assert baseline["2-16"][0].endswith("-05:00")
