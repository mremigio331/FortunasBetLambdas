"""Unit tests for WeekHelper's ET-aware containing-week finder.

Requirements: 5.6, 6.6
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from common.helpers.week_helper import WeekHelper

EASTERN = ZoneInfo("America/New_York")


@pytest.fixture
def helper():
    return WeekHelper(request_id="containing-week-test")


def _week(label, value, start, end):
    return {
        "label": label,
        "value": value,
        "startDate": start,
        "endDate": end,
    }


@pytest.fixture
def calendar():
    """A trimmed ESPN calendar: two regular-season weeks plus a playoff week."""
    return [
        {
            "label": "Regular Season",
            "value": "2",
            "entries": [
                _week("Week 1", "1", "2024-09-05T07:00Z", "2024-09-11T06:59Z"),
                _week("Week 2", "2", "2024-09-11T07:00Z", "2024-09-18T06:59Z"),
            ],
        },
        {
            "label": "Postseason",
            "value": "3",
            "entries": [
                _week("Wild Card", "1", "2025-01-08T08:00Z", "2025-01-15T07:59Z"),
            ],
        },
    ]


class TestFindContainingWeek:
    def test_returns_the_week_containing_the_moment(self, helper, calendar):
        now = datetime(2024, 9, 12, 18, 0, tzinfo=timezone.utc)

        found = helper._find_containing_week(calendar, now)

        assert found is not None
        assert found["week"]["label"] == "Week 2"
        assert found["season"]["label"] == "Regular Season"

    def test_returns_the_playoff_week_for_a_january_moment(self, helper, calendar):
        """A January playoff date resolves to the postseason entry (Req 5.2/8.3)."""
        now = datetime(2025, 1, 12, 21, 30, tzinfo=timezone.utc)

        found = helper._find_containing_week(calendar, now)

        assert found is not None
        assert found["week"]["label"] == "Wild Card"
        assert found["season"]["value"] == "3"

    def test_returns_none_when_no_week_contains_the_moment(self, helper, calendar):
        """Off-season: the moment sits between the two seasons."""
        now = datetime(2024, 12, 25, 12, 0, tzinfo=timezone.utc)

        assert helper._find_containing_week(calendar, now) is None

    def test_boundaries_are_inclusive(self, helper, calendar):
        start = datetime(2024, 9, 5, 7, 0, tzinfo=timezone.utc)
        end = datetime(2024, 9, 11, 6, 59, tzinfo=timezone.utc)

        assert (
            helper._find_containing_week(calendar, start)["week"]["label"] == "Week 1"
        )
        assert helper._find_containing_week(calendar, end)["week"]["label"] == "Week 1"

    def test_naive_now_is_treated_as_utc_without_raising(self, helper, calendar):
        """A naive datetime must not trigger a naive/aware comparison error."""
        found = helper._find_containing_week(calendar, datetime(2024, 9, 12, 18, 0))

        assert found is not None
        assert found["week"]["label"] == "Week 2"

    def test_equivalent_instants_in_different_zones_resolve_identically(
        self, helper, calendar
    ):
        """Requirement 6.6: comparisons depend on the instant, not the zone."""
        utc_now = datetime(2024, 9, 12, 18, 0, tzinfo=timezone.utc)
        eastern_now = utc_now.astimezone(EASTERN)
        tokyo_now = utc_now.astimezone(ZoneInfo("Asia/Tokyo"))
        los_angeles_now = utc_now.astimezone(ZoneInfo("America/Los_Angeles"))

        labels = {
            helper._find_containing_week(calendar, moment)["week"]["label"]
            for moment in (utc_now, eastern_now, tokyo_now, los_angeles_now)
        }

        assert labels == {"Week 2"}

    def test_entries_without_offsets_are_treated_as_utc(self, helper):
        calendar = [
            {
                "label": "Regular Season",
                "value": "2",
                "entries": [
                    _week("Week 1", "1", "2024-09-05T07:00:00", "2024-09-11T06:59:00")
                ],
            }
        ]
        now = datetime(2024, 9, 8, 12, 0, tzinfo=timezone.utc)

        assert helper._find_containing_week(calendar, now)["week"]["label"] == "Week 1"

    @pytest.mark.parametrize(
        "malformed",
        [
            [],
            None,
            "not-a-calendar",
            ["2024-09-05T07:00Z"],  # ESPN sometimes returns a flat date list
            [{"label": "Regular Season"}],  # no entries
            [{"label": "Regular Season", "entries": None}],
            [{"label": "Regular Season", "entries": ["Week 1"]}],
            [{"label": "Regular Season", "entries": [{"label": "Week 1"}]}],
        ],
    )
    def test_malformed_calendars_return_none_instead_of_raising(
        self, helper, malformed
    ):
        now = datetime(2024, 9, 8, 12, 0, tzinfo=timezone.utc)

        assert helper._find_containing_week(malformed, now) is None

    def test_unparseable_dates_are_skipped_and_later_weeks_still_match(self, helper):
        calendar = [
            {
                "label": "Regular Season",
                "value": "2",
                "entries": [
                    _week("Bad Week", "0", "not-a-date", "also-not-a-date"),
                    _week("Week 1", "1", "2024-09-05T07:00Z", "2024-09-11T06:59Z"),
                ],
            }
        ]
        now = datetime(2024, 9, 8, 12, 0, tzinfo=timezone.utc)

        assert helper._find_containing_week(calendar, now)["week"]["label"] == "Week 1"


class TestExtractScheduleCalendar:
    def test_returns_the_nested_calendar(self, helper, calendar):
        payload = {"leagues": [{"calendar": calendar}]}

        assert helper._extract_schedule_calendar(payload) is calendar

    @pytest.mark.parametrize(
        "payload",
        [
            {},  # ESPNClient returns {} when the request fails
            {"leagues": []},
            {"leagues": None},
            {"leagues": "nfl"},
            {"leagues": [None]},
            {"leagues": [{}]},  # missing 'calendar'
            {"leagues": [{"calendar": None}]},
            {"leagues": [{"calendar": "week-1"}]},
            None,
            "not-a-payload",
        ],
    )
    def test_missing_or_malformed_keys_yield_an_empty_calendar(self, helper, payload):
        """Requirement 5.6 guard: no KeyError/IndexError from a bad payload."""
        assert helper._extract_schedule_calendar(payload) == []

    def test_guarded_extraction_composes_with_the_finder(self, helper):
        """An empty payload flows through to "no containing week" cleanly."""
        empty_calendar = helper._extract_schedule_calendar({})

        assert (
            helper._find_containing_week(empty_calendar, datetime.now(timezone.utc))
            is None
        )


class TestEnsureAware:
    def test_naive_values_become_utc(self, helper):
        aware = helper._ensure_aware(datetime(2024, 9, 8, 12, 0))

        assert aware.tzinfo is not None
        assert aware.utcoffset() == timedelta(0)

    def test_aware_values_are_returned_unchanged(self, helper):
        original = datetime(2024, 9, 8, 12, 0, tzinfo=EASTERN)

        assert helper._ensure_aware(original) == original
