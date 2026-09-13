"""Smoke tests confirming the pytest + hypothesis tooling is wired correctly.

Requirements: 8.3, 8.4 (test tooling must be able to exercise WeekHelper).
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from common.helpers.week_helper import WeekHelper


def test_week_helper_is_importable_and_constructible():
    """The suite can import and instantiate the module under test."""
    helper = WeekHelper(request_id="smoke-test")

    assert isinstance(helper, WeekHelper)
    assert helper.request_id == "smoke-test"
    assert hasattr(helper, "get_nfl_current_week")


def test_calendar_week_boundary_returns_ordered_pair():
    """A pure WeekHelper code path executes end to end under pytest."""
    helper = WeekHelper(request_id="smoke-test")

    # 2024-09-08T17:00:00Z
    week_start, week_end = helper._get_calendar_week_boundary(1725814800)

    assert isinstance(week_start, int)
    assert isinstance(week_end, int)
    assert week_start <= 1725814800 <= week_end


@settings(max_examples=100)
@given(st.integers(min_value=0, max_value=2_000_000_000))
def test_hypothesis_is_wired(epoch_seconds):
    """Confirms hypothesis runs so later property tests have a working harness."""
    assert epoch_seconds >= 0
