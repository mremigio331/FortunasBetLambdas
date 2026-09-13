"""Tests for the /bet/get_current_nfl_week response contract.

Requirements: 5.4 (Season_Year in the payload), 5.5 (explicit off-season
indicator), 6.1 (numeric week and season type values).
"""

import pytest
from pydantic import ValidationError

from api.endpoints.bet.get_current_nfl_week import (
    CurrentNflWeek,
    CurrentNflWeekResponse,
    router,
)


IN_SEASON_PAYLOAD = {
    "is_off_season": False,
    "season_year": 2024,
    "season_type_label": "Regular Season",
    "season_type_value": 2,
    "week_label": "Week 12",
    "week_value": 12,
    "week_start": "2024-11-19T08:00:00Z",
    "week_end": "2024-11-26T07:59:00Z",
}


def test_in_season_payload_is_accepted():
    week = CurrentNflWeek(**IN_SEASON_PAYLOAD)

    assert week.is_off_season is False
    assert week.season_year == 2024
    assert week.season_type_value == 2
    assert week.week_value == 12


def test_off_season_payload_keeps_indicator_with_null_week_fields():
    week = CurrentNflWeek(
        is_off_season=True,
        season_year=2024,
        season_type_label=None,
        season_type_value=None,
        week_label=None,
        week_value=None,
        week_start=None,
        week_end=None,
    )

    assert week.is_off_season is True
    assert week.week_value is None
    assert week.season_year == 2024


def test_off_season_indicator_is_required():
    """The payload cannot omit the explicit off-season indicator."""
    payload = {k: v for k, v in IN_SEASON_PAYLOAD.items() if k != "is_off_season"}

    with pytest.raises(ValidationError):
        CurrentNflWeek(**payload)


def test_string_week_values_are_coerced_to_numbers():
    """ESPN returns week/season type as strings; the model normalizes to int."""
    week = CurrentNflWeek(
        **{**IN_SEASON_PAYLOAD, "week_value": "12", "season_type_value": "2"}
    )

    assert week.week_value == 12
    assert week.season_type_value == 2
    assert isinstance(week.week_value, int)
    assert isinstance(week.season_type_value, int)


def test_envelope_wraps_a_single_object_not_a_list():
    response = CurrentNflWeekResponse(
        message="Retrieved current NFL week information successfully.",
        data=IN_SEASON_PAYLOAD,
    )

    assert isinstance(response.data, CurrentNflWeek)

    with pytest.raises(ValidationError):
        CurrentNflWeekResponse(message="nope", data=[IN_SEASON_PAYLOAD])


def test_route_declares_the_single_object_response_model():
    route = next(r for r in router.routes if r.path == "/get_current_nfl_week")

    assert route.response_model is CurrentNflWeekResponse
