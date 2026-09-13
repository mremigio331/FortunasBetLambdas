"""Edge-case tests for the branches of WeekHelper.get_nfl_current_week.

These fill the gaps left by `test_week_helper_current_week.py` (Season_Year
selection, adjacent-year retry, numeric normalization) and
`test_week_helper_containing_week.py` (unit-level guards on
`_extract_schedule_calendar` / `_find_containing_week`):

- Retry exhaustion when the containing week lives in a NON-adjacent Season_Year
  (5.3) - the resolver must report off-season rather than reaching for it.
- Off-season reached through a structurally valid schedule that simply has no
  usable week entries (5.3, 8.4) - the guards must compose end-to-end, not just
  in isolation.
- Deep off-season with fully populated schedules for every candidate year
  (8.4), distinct from the existing "every request came back empty" case.
- A failing ESPN lookup is NOT reported as off-season (5.5) - the two are
  different conditions and callers must be able to tell them apart.
- The off-season indicator is the flag itself, not the null fields (5.4, 5.5).

`ESPNClient.get_nfl_schedule` is stubbed throughout - no live HTTP.
"""

from datetime import datetime, timezone

import pytest

from common.helpers import week_helper as week_helper_module
from common.helpers.week_helper import WeekHelper


def _week(label, value, start, end):
    return {"label": label, "value": value, "startDate": start, "endDate": end}


def _schedule(seasons):
    """Wrap seasons in the ESPN payload envelope: leagues[0].calendar."""
    return {"leagues": [{"calendar": seasons}]}


def _regular_season(entries):
    return _schedule([{"label": "Regular Season", "value": "2", "entries": entries}])


# Schedules that load cleanly but cover only mid-November of their season.
NOVEMBER_2024 = _regular_season(
    [_week("Week 12", "12", "2024-11-19T08:00Z", "2024-11-26T07:59Z")]
)
NOVEMBER_2023 = _regular_season(
    [_week("Week 12", "12", "2023-11-21T08:00Z", "2023-11-28T07:59Z")]
)
NOVEMBER_2025 = _regular_season(
    [_week("Week 12", "12", "2025-11-18T08:00Z", "2025-11-25T07:59Z")]
)


class _StubESPNClient:
    """Records the years requested and replays a canned schedule per year."""

    def __init__(self, schedules_by_year, raise_for_years=()):
        self.schedules_by_year = schedules_by_year
        self.raise_for_years = set(raise_for_years)
        self.requested_years = []

    def __call__(self, request_id=None, **kwargs):
        # WeekHelper constructs ESPNClient(request_id=...); the stub class
        # doubles as its own factory so one instance records every call.
        return self

    def get_nfl_schedule(self, year):
        self.requested_years.append(year)
        if year in self.raise_for_years:
            raise RuntimeError(f"ESPN lookup blew up for {year}")
        return self.schedules_by_year.get(year, {})


@pytest.fixture
def helper():
    return WeekHelper(request_id="resolver-edge-test")


@pytest.fixture
def espn(monkeypatch):
    """Install a stub ESPNClient and freeze `now` inside week_helper."""

    def _install(schedules_by_year, now, raise_for_years=()):
        stub = _StubESPNClient(schedules_by_year, raise_for_years)
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


class TestRetryExhaustion:
    def test_a_containing_week_two_seasons_away_is_not_reached(self, helper, espn):
        """Requirement 5.3: the retry window is the adjacent years only.

        The containing week exists, but under season 2022 - two years off the
        derived Season_Year. The resolver must report off-season rather than
        widening its search and silently attributing the week to the wrong
        season.
        """
        now = datetime(2025, 1, 12, 21, 30, tzinfo=timezone.utc)
        stub = espn(
            {
                2022: _schedule(
                    [
                        {
                            "label": "Postseason",
                            "value": "3",
                            "entries": [
                                _week(
                                    "Wild Card",
                                    "1",
                                    "2025-01-08T08:00Z",
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

        assert stub.requested_years == [2024, 2023, 2025]
        assert 2022 not in stub.requested_years
        assert result["is_off_season"] is True
        assert result["season_year"] == 2024
        assert result["week_label"] is None

    def test_deep_off_season_with_every_candidate_schedule_populated(
        self, helper, espn
    ):
        """Requirement 8.4: mid-July, with all three schedules loading fine.

        Distinct from the existing off-season case, where every ESPN request
        came back empty. Here each candidate year returns a real calendar and
        none of them contains the moment.
        """
        now = datetime(2025, 7, 15, 16, 0, tzinfo=timezone.utc)
        stub = espn(
            {2024: NOVEMBER_2024, 2023: NOVEMBER_2023, 2025: NOVEMBER_2025},
            now,
        )

        result = helper.get_nfl_current_week()

        assert stub.requested_years == [2024, 2023, 2025]
        assert result["is_off_season"] is True
        assert result["season_year"] == 2024


class TestGuardedScheduleAccessEndToEnd:
    @pytest.mark.parametrize(
        "payload",
        [
            {"leagues": [{"calendar": []}]},  # calendar present, zero seasons
            _schedule([{"label": "Regular Season", "value": "2", "entries": []}]),
            _schedule([{"label": "Regular Season", "value": "2"}]),  # no 'entries'
            _schedule([{"label": "Regular Season", "value": "2", "entries": None}]),
        ],
    )
    def test_valid_payload_without_usable_entries_reports_off_season(
        self, helper, espn, payload
    ):
        """Requirements 5.3, 8.4: the guards compose through the full resolver.

        Nothing here is malformed enough to raise, but nothing is usable
        either. Every candidate year is tried and the result is off-season, not
        a KeyError and not a half-populated week.
        """
        now = datetime(2024, 11, 20, 18, 0, tzinfo=timezone.utc)
        stub = espn({2024: payload, 2023: payload, 2025: payload}, now)

        result = helper.get_nfl_current_week()

        assert stub.requested_years == [2024, 2023, 2025]
        assert result["is_off_season"] is True
        assert result["season_year"] == 2024


class TestFailureIsNotOffSeason:
    def test_an_espn_lookup_failure_propagates_instead_of_reporting_off_season(
        self, helper, espn
    ):
        """Requirement 5.5: a failed lookup and off-season are not the same thing.

        `ESPNClient.get_nfl_schedule` swallows `RequestException` into `{}`, but
        anything else escapes. The resolver must let that surface (the endpoint's
        exceptions decorator turns it into an error response, and the frontend
        falls back and flags the week as an estimate) rather than reporting a
        confident `is_off_season: True`.
        """
        now = datetime(2024, 11, 20, 18, 0, tzinfo=timezone.utc)
        stub = espn({}, now, raise_for_years=[2024])

        with pytest.raises(RuntimeError):
            helper.get_nfl_current_week()

        # It failed on the first candidate and did not quietly retry past it.
        assert stub.requested_years == [2024]


class TestOffSeasonIndicatorIsTheFlag:
    def test_off_season_is_distinguishable_without_inspecting_null_fields(
        self, helper, espn
    ):
        """Requirements 5.4, 5.5: branch on the flag, never on field presence.

        Both payloads expose the identical key set with the same `is_off_season`
        type, so a caller distinguishes the two states from that one field
        without probing which week fields happen to be null.
        """
        espn({2024: NOVEMBER_2024}, datetime(2024, 11, 20, tzinfo=timezone.utc))
        in_season = helper.get_nfl_current_week()

        espn({2024: NOVEMBER_2024}, datetime(2025, 7, 15, tzinfo=timezone.utc))
        off_season = helper.get_nfl_current_week()

        assert set(off_season) == set(in_season)
        # Real bools, not merely truthy/falsy - the flag is the contract.
        assert in_season["is_off_season"] is False
        assert off_season["is_off_season"] is True
        # Season_Year survives off-season, so the flag is not a bare null payload.
        assert off_season["season_year"] == 2024
