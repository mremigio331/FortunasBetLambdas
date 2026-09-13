"""Property-based test for NFL Season_Year derivation.

Feature: current-week-selection-fix, Property 7: Season_Year drives schedule
selection - For any date, the Season_Year used by the Authoritative_Week_Source
to request the schedule SHALL be the current calendar year for August-December
and the prior calendar year for January-July, so that January/February playoff
dates request the prior year's schedule.

Validates: Requirements 5.1, 5.2
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from common.helpers.week_helper import WeekHelper

# Naive and timezone-aware moments alike: the Season_Year depends only on the
# calendar month/year of the value handed to the helper.
moments = st.datetimes(
    min_value=datetime(1920, 1, 1),
    max_value=datetime(2100, 12, 31, 23, 59, 59),
    timezones=st.one_of(st.none(), st.timezones()),
)


@pytest.fixture(scope="module")
def helper():
    return WeekHelper(request_id="property-7-season-year")


# Feature: current-week-selection-fix, Property 7: Season_Year drives schedule
# selection - the Season_Year is the current calendar year for August-December
# and the prior calendar year for January-July, so January/February playoff
# dates request the prior year's schedule.
# Validates: Requirements 5.1, 5.2
@settings(max_examples=100)
@given(now=moments)
# Explicit January playoff moment: the 2024 season's wild-card round (Req 8.3).
@example(now=datetime(2025, 1, 12, 21, 30, tzinfo=ZoneInfo("America/New_York")))
# Explicit February playoff moment: Super Bowl LIX still belongs to 2024.
@example(now=datetime(2025, 2, 9, 23, 30, tzinfo=ZoneInfo("America/New_York")))
def test_season_year_is_current_year_for_aug_dec_and_prior_year_for_jan_jul(
    helper, now
):
    season_year = helper.get_nfl_season_year(now)

    expected = now.year if now.month >= 8 else now.year - 1
    assert season_year == expected

    # The season a date belongs to either started in its own calendar year or
    # in the one before it - never any other year.
    assert season_year in (now.year, now.year - 1)

    if now.month in (1, 2):
        # January/February playoff dates must request the prior year's schedule.
        assert season_year == now.year - 1
