"""Unit tests for the rewritten WeekHelper.get_nfl_current_week resolver.

Covers Season_Year-driven schedule selection (5.1), adjacent-year retry (5.3),
Season_Year in the payload (5.4), the explicit off-season indicator (5.5), and
numeric normalization of the week contract (6.1).

`ESPNClient.get_nfl_schedule` is stubbed throughout - no live HTTP.
"""

from datetime import datetime, timezone

import pytest

from api.endpoints.bet.get_current_nfl_week import CurrentNflWeek
from common.helpers import week_helper as week_helper_module
from common.helpers.week_helper import WeekHelper


def _week(label, value, start, end):
    return {"label": label, "value": value, "startDate": start, "endDate": end}


def _schedule(seasons):
    """Wrap seasons in the ESPN payload envelope: leagues[0].calendar."""
    return {"leagues": [{"calendar": seasons}]}


REGULAR_SEASON_2024 = _schedule(
    [
        {
            "label": "Regular Season",
            "value": "2",
            "entries": [
                _week("Week 11", "11", "2024-11-12T08:00Z", "2024-11-19T07:59Z"),
                _week("Week 12", "12", "2024-11-19T08:00Z", "2024-11-26T07:59Z"),
            ],
        }
    ]
)

POSTSEASON_2024 = _schedule(
    [
        {
            "label": "Postseason",
            "value": "3",
            "entries": [
                _week("Wild Card", "1", "2025-01-08T08:00Z", "2025-01-15T07:59Z"),
            ],
        }
    ]
)

EMPTY_SCHEDULE = {}


class _StubESPNClient:
    """Records the years requested and replays a canned schedule per year."""

    def __init__(self, schedules_by_year):
        self.schedules_by_year = schedules_by_year
        self.requested_years = []

    def __call__(self, request_id=None, **kwargs):
        # WeekHelper constructs ESPNClient(request_id=...); the stub class
        # doubles as its own factory so one instance records every call.
        return self

    def get_nfl_schedule(self, year):
        self.requested_years.append(year)
        return self.schedules_by_year.get(year, EMPTY_SCHEDULE)


@pytest.fixture
def helper():
    return WeekHelper(request_id="current-week-test")


@pytest.fixture
def espn(monkeypatch):
    """Install a stub ESPNClient and freeze `now` inside week_helper."""

    def _install(schedules_by_year, now):
        stub = _StubESPNClient(schedules_by_year)
        monkeypatch.setattr(week_helper_module, "ESPNClient", stub)

        class _FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)
                )

        monkeypatch.setattr(week_helper_module, "datetime", _FrozenDatetime)
        return stub

    return _install


class TestSeasonYearDrivesScheduleSelection:
    def test_requests_the_current_season_year_in_november(self, helper, espn):
        now = datetime(2024, 11, 20, 18, 0, tzinfo=timezone.utc)
        stub = espn({2024: REGULAR_SEASON_2024}, now)

        result = helper.get_nfl_current_week()

        assert stub.requested_years == [2024]
        assert result["is_off_season"] is False
        assert result["season_year"] == 2024
        assert result["week_label"] == "Week 12"

    def test_january_playoffs_request_the_prior_calendar_year(self, helper, espn):
        """Requirement 5.2 / 8.3: a January moment asks for the 2024 schedule."""
        now = datetime(2025, 1, 12, 21, 30, tzinfo=timezone.utc)
        stub = espn({2024: POSTSEASON_2024}, now)

        result = helper.get_nfl_current_week()

        assert stub.requested_years[0] == 2024
        assert result["season_year"] == 2024
        assert result["season_type_label"] == "Postseason"
        assert result["week_label"] == "Wild Card"
        assert result["is_off_season"] is False

    def test_stops_after_the_first_matching_year(self, helper, espn):
        """No adjacent-year calls are made once the week is found."""
        now = datetime(2024, 11, 20, 18, 0, tzinfo=timezone.utc)
        stub = espn({2024: REGULAR_SEASON_2024, 2023: REGULAR_SEASON_2024}, now)

        helper.get_nfl_current_week()

        assert stub.requested_years == [2024]


class TestAdjacentYearRetry:
    def test_falls_back_to_the_prior_season_year(self, helper, espn):
        """Requirement 5.3: retry season_year - 1 before declaring off-season."""
        now = datetime(2025, 1, 12, 21, 30, tzinfo=timezone.utc)
        # Season_Year is 2024, but the containing week only exists under 2023.
        stub = espn(
            {
                2023: _schedule(
                    [
                        {
                            "label": "Postseason",
                            "value": "3",
                            "entries": [
                                _week(
                                    "Divisional Round",
                                    "2",
                                    "2025-01-10T08:00Z",
                                    "2025-01-15T07:59Z",
                                )
                            ],
                        }
                    ]
                )
            },
            now,
        )

        result = helper.get_nfl_current_week()

        assert stub.requested_years == [2024, 2023]
        assert result["is_off_season"] is False
        assert result["season_year"] == 2023
        assert result["week_label"] == "Divisional Round"

    def test_falls_back_to_the_next_season_year(self, helper, espn):
        """Requirement 5.3: season_year + 1 is the last candidate."""
        now = datetime(2024, 8, 2, 12, 0, tzinfo=timezone.utc)
        stub = espn(
            {
                2025: _schedule(
                    [
                        {
                            "label": "Preseason",
                            "value": "1",
                            "entries": [
                                _week(
                                    "Hall of Fame Week",
                                    "1",
                                    "2024-08-01T07:00Z",
                                    "2024-08-08T06:59Z",
                                )
                            ],
                        }
                    ]
                )
            },
            now,
        )

        result = helper.get_nfl_current_week()

        assert stub.requested_years == [2024, 2023, 2025]
        assert result["season_year"] == 2025
        assert result["season_type_value"] == 1
        assert result["week_label"] == "Hall of Fame Week"

    @pytest.mark.parametrize(
        "malformed",
        [
            {},
            {"leagues": []},
            {"leagues": [{}]},
            {"leagues": [{"calendar": None}]},
            None,
        ],
    )
    def test_malformed_primary_payload_triggers_retry_instead_of_raising(
        self, helper, espn, malformed
    ):
        """A bad payload must not raise KeyError; it falls through to retry."""
        now = datetime(2024, 11, 20, 18, 0, tzinfo=timezone.utc)
        stub = espn({2024: malformed, 2023: REGULAR_SEASON_2024}, now)

        result = helper.get_nfl_current_week()

        assert stub.requested_years == [2024, 2023]
        assert result["is_off_season"] is False
        assert result["season_year"] == 2023


class TestOffSeason:
    def test_off_season_returns_an_explicit_indicator_after_all_retries(
        self, helper, espn
    ):
        """Requirements 5.4, 5.5: explicit flag, Season_Year kept, nulls elsewhere."""
        now = datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)
        stub = espn({}, now)

        result = helper.get_nfl_current_week()

        assert stub.requested_years == [2024, 2023, 2025]
        assert result["is_off_season"] is True
        assert result["season_year"] == 2024
        assert result["season_type_label"] is None
        assert result["season_type_value"] is None
        assert result["week_label"] is None
        assert result["week_value"] is None
        assert result["week_start"] is None
        assert result["week_end"] is None

    def test_a_schedule_that_does_not_contain_now_is_off_season(self, helper, espn):
        """The schedule loads fine, but the moment sits between seasons."""
        now = datetime(2024, 12, 30, 12, 0, tzinfo=timezone.utc)
        espn({2024: REGULAR_SEASON_2024, 2023: REGULAR_SEASON_2024}, now)

        result = helper.get_nfl_current_week()

        assert result["is_off_season"] is True
        assert result["season_year"] == 2024


class TestNumericNormalization:
    def test_string_espn_values_become_ints(self, helper, espn):
        """Requirement 6.1: ESPN sends strings; the payload exposes numbers."""
        now = datetime(2024, 11, 20, 18, 0, tzinfo=timezone.utc)
        espn({2024: REGULAR_SEASON_2024}, now)

        result = helper.get_nfl_current_week()

        assert result["week_value"] == 12
        assert result["season_type_value"] == 2
        assert isinstance(result["week_value"], int)
        assert isinstance(result["season_type_value"], int)

    def test_already_numeric_values_are_preserved(self, helper, espn):
        now = datetime(2024, 11, 20, 18, 0, tzinfo=timezone.utc)
        espn(
            {
                2024: _schedule(
                    [
                        {
                            "label": "Regular Season",
                            "value": 2,
                            "entries": [
                                _week(
                                    "Week 12",
                                    12,
                                    "2024-11-19T08:00Z",
                                    "2024-11-26T07:59Z",
                                )
                            ],
                        }
                    ]
                )
            },
            now,
        )

        result = helper.get_nfl_current_week()

        assert result["week_value"] == 12
        assert result["season_type_value"] == 2

    def test_non_numeric_values_become_none_without_raising(self, helper, espn):
        now = datetime(2024, 11, 20, 18, 0, tzinfo=timezone.utc)
        espn(
            {
                2024: _schedule(
                    [
                        {
                            "label": "Regular Season",
                            "value": "regular",
                            "entries": [
                                _week(
                                    "Week 12",
                                    None,
                                    "2024-11-19T08:00Z",
                                    "2024-11-26T07:59Z",
                                )
                            ],
                        }
                    ]
                )
            },
            now,
        )

        result = helper.get_nfl_current_week()

        assert result["is_off_season"] is False
        assert result["week_label"] == "Week 12"
        assert result["week_value"] is None
        assert result["season_type_value"] is None

    def test_boundaries_are_full_iso_timestamps_with_offsets(self, helper, espn):
        now = datetime(2024, 11, 20, 18, 0, tzinfo=timezone.utc)
        espn({2024: REGULAR_SEASON_2024}, now)

        result = helper.get_nfl_current_week()

        assert result["week_start"] == "2024-11-19T08:00:00+00:00"
        assert result["week_end"] == "2024-11-26T07:59:00+00:00"


class TestResponseContractAgreement:
    """The helper output must satisfy the endpoint's declared response model."""

    def test_in_season_payload_validates_against_the_response_model(self, helper, espn):
        now = datetime(2024, 11, 20, 18, 0, tzinfo=timezone.utc)
        espn({2024: REGULAR_SEASON_2024}, now)

        model = CurrentNflWeek(**helper.get_nfl_current_week())

        assert model.is_off_season is False
        assert model.season_year == 2024
        assert model.week_value == 12

    def test_off_season_payload_validates_against_the_response_model(
        self, helper, espn
    ):
        now = datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)
        espn({}, now)

        model = CurrentNflWeek(**helper.get_nfl_current_week())

        assert model.is_off_season is True
        assert model.season_year == 2024
        assert model.week_value is None

    def test_payload_keys_match_the_model_fields_exactly(self, helper, espn):
        now = datetime(2024, 11, 20, 18, 0, tzinfo=timezone.utc)
        espn({2024: REGULAR_SEASON_2024}, now)

        assert set(helper.get_nfl_current_week()) == set(CurrentNflWeek.model_fields)
