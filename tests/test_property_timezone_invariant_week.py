"""Property-based test for timezone-invariant NFL week resolution (backend).

Feature: current-week-selection-fix, Property 4: Timezone-invariant week
resolution - For any instant in time and any pair of viewer time zones
(including at least one east of and one west of Eastern Time), Week_Resolution
SHALL produce identical results for both time zones.

Backend framing: the resolver compares absolute instants, so the same moment
must resolve to the same week no matter which zone that moment is expressed in,
and no matter which offset the ESPN schedule boundaries carry.

Validates: Requirements 3.1, 5.6, 8.2

`ESPNClient.get_nfl_schedule` is stubbed throughout - no live HTTP.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from common.helpers import week_helper as week_helper_module
from common.helpers.week_helper import WeekHelper

EASTERN = ZoneInfo("America/New_York")
# At least one zone east of Eastern Time and one west of it (Requirement 8.2).
EAST_OF_ET = (ZoneInfo("Europe/Berlin"), ZoneInfo("Asia/Tokyo"))
WEST_OF_ET = (ZoneInfo("America/Los_Angeles"), ZoneInfo("Pacific/Honolulu"))

ONE_WEEK = timedelta(days=7)
ONE_SECOND = timedelta(seconds=1)

EMPTY_SCHEDULE = {}

# Instants are generated in UTC and then re-expressed in each viewer zone, so
# every expression describes the identical absolute moment. The range stays
# well inside the datetime domain so zone conversion can never overflow.
instants = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2035, 12, 31, 23, 59, 59),
    timezones=st.just(timezone.utc),
)

# `None` means "write the boundary with no offset at all", which is the
# `_ensure_aware` assume-UTC path.
boundary_zones = st.lists(st.one_of(st.none(), st.timezones()), min_size=1, max_size=2)

extra_viewer_zones = st.lists(st.timezones(), min_size=0, max_size=2)


class _StubESPNClient:
    """Replays a canned schedule per year; doubles as its own factory."""

    def __init__(self, schedules_by_year):
        self.schedules_by_year = schedules_by_year

    def __call__(self, request_id=None, **kwargs):
        return self

    def get_nfl_schedule(self, year):
        return self.schedules_by_year.get(year, EMPTY_SCHEDULE)


def _iso(moment: datetime, zone) -> str:
    """Render an absolute instant as ESPN would, in the given zone.

    `zone=None` drops the offset entirely, which the helper must read as UTC.
    """
    if zone is None:
        return moment.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
    return moment.astimezone(zone).isoformat()


def _week(label, value, start, end, zone):
    return {
        "label": label,
        "value": value,
        "startDate": _iso(start, zone),
        "endDate": _iso(end, zone),
    }


def _calendar(week_start: datetime, week_end: datetime, zone) -> list:
    """A three-week season whose middle entry is the target week.

    The flanking weeks make the match non-trivial: only one entry can contain
    the moment, so a zone-sensitive comparison would pick a neighbour (or
    nothing) instead of the target.
    """
    return [
        {
            "label": "Regular Season",
            "value": "2",
            "entries": [
                _week(
                    "Previous Week",
                    "1",
                    week_start - ONE_WEEK,
                    week_start - ONE_SECOND,
                    zone,
                ),
                _week("Target Week", "2", week_start, week_end, zone),
                _week(
                    "Next Week",
                    "3",
                    week_end + ONE_SECOND,
                    week_end + ONE_WEEK,
                    zone,
                ),
            ],
        }
    ]


def _viewer_expressions(instant: datetime, extra_zones) -> list:
    """The same instant expressed every way a caller might hand it over."""
    zones = (EASTERN,) + EAST_OF_ET + WEST_OF_ET + tuple(extra_zones)
    return (
        [instant]
        + [instant.astimezone(zone) for zone in zones]
        # Naive: `_ensure_aware` must read it as the UTC instant it is.
        + [instant.replace(tzinfo=None)]
    )


def _resolve_full_payload(helper, schedule_year, schedule, moment):
    """Run `get_nfl_current_week` with `now` arriving as `moment`."""

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            # The moment reaches the resolver carrying the viewer's zone (or no
            # zone at all), whatever zone was asked for.
            return moment

    stub = _StubESPNClient({schedule_year: schedule})

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(week_helper_module, "ESPNClient", stub)
        mp.setattr(week_helper_module, "datetime", _FrozenDatetime)
        return helper.get_nfl_current_week()


@pytest.fixture(scope="module")
def helper():
    return WeekHelper(request_id="property-4-timezone-invariance")


# Feature: current-week-selection-fix, Property 4: Timezone-invariant week
# resolution - for any instant and any pair of viewer time zones (including at
# least one east of and one west of Eastern Time), Week_Resolution produces
# identical results for both time zones.
# Validates: Requirements 3.1, 5.6, 8.2
@settings(max_examples=100)
@given(
    instant=instants,
    seconds_into_week=st.integers(
        min_value=0, max_value=int(ONE_WEEK.total_seconds()) - 1
    ),
    schedule_zones=boundary_zones,
    viewer_zones=extra_viewer_zones,
)
def test_week_resolution_is_identical_east_and_west_of_eastern_time(
    helper, instant, seconds_into_week, schedule_zones, viewer_zones
):
    # A week that contains the instant, positioned anywhere within it.
    week_start = instant - timedelta(seconds=seconds_into_week)
    week_end = week_start + ONE_WEEK - ONE_SECOND

    expressions = _viewer_expressions(instant, viewer_zones)

    # The same absolute boundaries, written with different offsets.
    calendars = [
        _calendar(week_start, week_end, zone)
        for zone in [timezone.utc, EASTERN] + schedule_zones
    ]

    matches = set()
    for calendar in calendars:
        for moment in expressions:
            found = helper._find_containing_week(calendar, moment)

            assert found is not None
            matches.add((found["season"]["label"], found["week"]["label"]))

    # One outcome across every viewer zone and every boundary offset.
    assert matches == {("Regular Season", "Target Week")}

    # Same invariance through the full resolver, including the numeric and ISO
    # normalization applied to the payload.
    schedule_year = helper.get_nfl_season_year(instant)
    schedule = {
        "leagues": [{"calendar": _calendar(week_start, week_end, timezone.utc)}]
    }

    payloads = [
        _resolve_full_payload(helper, schedule_year, schedule, moment)
        for moment in expressions
    ]

    assert all(payload == payloads[0] for payload in payloads)
    assert payloads[0]["is_off_season"] is False
    assert payloads[0]["week_label"] == "Target Week"
    assert payloads[0]["week_value"] == 2
    assert payloads[0]["season_year"] == schedule_year
