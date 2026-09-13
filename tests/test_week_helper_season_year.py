"""Unit tests for WeekHelper.get_nfl_season_year.

Requirements: 5.1, 5.2
"""

from datetime import datetime, timezone

import pytest

from common.helpers.week_helper import WeekHelper


@pytest.fixture
def helper():
    return WeekHelper(request_id="season-year-test")


@pytest.mark.parametrize("month", [8, 9, 10, 11, 12])
def test_august_through_december_use_the_current_calendar_year(helper, month):
    now = datetime(2024, month, 15, 12, 0, tzinfo=timezone.utc)

    assert helper.get_nfl_season_year(now) == 2024


@pytest.mark.parametrize("month", [1, 2, 3, 4, 5, 6, 7])
def test_january_through_july_use_the_prior_calendar_year(helper, month):
    now = datetime(2025, month, 15, 12, 0, tzinfo=timezone.utc)

    assert helper.get_nfl_season_year(now) == 2024


def test_january_playoff_window_resolves_to_prior_season_year(helper):
    """A January playoff date must request the prior year's schedule (Req 5.2)."""
    now = datetime(2025, 1, 12, 21, 30, tzinfo=timezone.utc)

    assert helper.get_nfl_season_year(now) == 2024


def test_boundary_between_july_and_august(helper):
    assert helper.get_nfl_season_year(datetime(2024, 7, 31, 23, 59)) == 2023
    assert helper.get_nfl_season_year(datetime(2024, 8, 1, 0, 0)) == 2024


def test_naive_datetimes_are_accepted(helper):
    assert helper.get_nfl_season_year(datetime(2024, 9, 8)) == 2024
    assert helper.get_nfl_season_year(datetime(2024, 2, 9)) == 2023
