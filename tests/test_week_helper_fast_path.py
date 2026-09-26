"""Tests for the fast NFL current-week resolution path.

The fast path resolves the current week from a single lightweight scoreboard
call (get_nfl_calendar) instead of fetching full-year schedules for up to three
candidate years. On a miss/failure it must fall back to the full-schedule loop.
"""

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from common.helpers.week_helper import WeekHelper


def _calendar_payload(start_iso, end_iso):
    """Minimal plain-scoreboard shape carrying leagues[0].calendar."""
    return {
        "leagues": [
            {
                "calendar": [
                    {
                        "label": "Regular Season",
                        "value": "2",
                        "entries": [
                            {
                                "label": "Week 3",
                                "value": "3",
                                "startDate": start_iso,
                                "endDate": end_iso,
                            }
                        ],
                    }
                ]
            }
        ]
    }


def test_fast_path_resolves_from_single_calendar_call():
    """A containing week from get_nfl_calendar resolves without the schedule loop."""
    helper = WeekHelper(request_id="test")

    # A wide window guaranteed to contain "now".
    payload = _calendar_payload("2000-01-01T00:00Z", "2100-01-01T00:00Z")

    fake_client = MagicMock()
    fake_client.get_nfl_calendar.return_value = payload

    with patch("common.helpers.week_helper.ESPNClient", return_value=fake_client):
        result = helper.get_nfl_current_week()

    # Fast path used; heavy per-year schedule NOT called.
    fake_client.get_nfl_calendar.assert_called_once()
    fake_client.get_nfl_schedule.assert_not_called()

    assert result["is_off_season"] is False
    assert result["season_type_value"] == 2
    assert result["week_value"] == 3
    assert result["week_label"] == "Week 3"


def test_falls_back_to_schedule_when_fast_path_has_no_containing_week():
    """A fast-path miss falls through to the full-schedule candidate-year loop."""
    helper = WeekHelper(request_id="test")

    # Fast path returns a calendar whose only week is far in the past -> miss.
    stale = _calendar_payload("2000-01-01T00:00Z", "2000-01-08T00:00Z")
    # Fallback schedule returns a week that contains "now".
    live = _calendar_payload("2000-01-01T00:00Z", "2100-01-01T00:00Z")

    fake_client = MagicMock()
    fake_client.get_nfl_calendar.return_value = stale
    fake_client.get_nfl_schedule.return_value = live

    with patch("common.helpers.week_helper.ESPNClient", return_value=fake_client):
        result = helper.get_nfl_current_week()

    fake_client.get_nfl_calendar.assert_called_once()
    # Fallback engaged.
    assert fake_client.get_nfl_schedule.called
    assert result["is_off_season"] is False
    assert result["week_value"] == 3


def test_falls_back_when_fast_path_raises():
    """An exception in the fast path must not break resolution."""
    helper = WeekHelper(request_id="test")

    live = _calendar_payload("2000-01-01T00:00Z", "2100-01-01T00:00Z")

    fake_client = MagicMock()
    fake_client.get_nfl_calendar.side_effect = RuntimeError("boom")
    fake_client.get_nfl_schedule.return_value = live

    with patch("common.helpers.week_helper.ESPNClient", return_value=fake_client):
        result = helper.get_nfl_current_week()

    assert fake_client.get_nfl_schedule.called
    assert result["week_value"] == 3
