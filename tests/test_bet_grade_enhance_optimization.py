"""Tests for the optimized bet grade+enhance path.

_grade_and_enhance_bet should:
  - skip ESPN entirely for an already-graded bet (fast exit),
  - skip ESPN for a not-yet-started game (fast exit),
  - fetch the game exactly ONCE for an ungraded, started bet and reuse that
    payload for both grading and enhancement (no duplicate get_event).
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from common.helpers.bet_helper import BetHelper


def _helper():
    with patch("common.helpers.bet_helper.boto3"):
        h = BetHelper(request_id="test")
    # Avoid real DynamoDB in any path that might persist.
    h.table = MagicMock()
    return h


def test_already_graded_bet_makes_no_espn_call():
    h = _helper()
    bet = {
        "game_id": "g1",
        "sport": "football",
        "league": "nfl",
        "total_points_earned": 3.0,  # already graded
        "event_datetime": 1,
    }
    with patch("common.helpers.bet_helper.ESPNClient") as MockClient:
        result = h._grade_and_enhance_bet(bet)
    MockClient.assert_not_called()
    assert result is bet


def test_not_started_game_makes_no_espn_call():
    h = _helper()
    future = int(datetime.now(timezone.utc).timestamp()) + 86_400
    bet = {
        "game_id": "g2",
        "sport": "football",
        "league": "nfl",
        "total_points_earned": None,  # ungraded
        "event_datetime": future,  # hasn't started
    }
    with patch("common.helpers.bet_helper.ESPNClient") as MockClient:
        result = h._grade_and_enhance_bet(bet)
    MockClient.assert_not_called()
    assert result is bet


def test_started_ungraded_bet_fetches_game_once():
    h = _helper()
    past = int(datetime.now(timezone.utc).timestamp()) - 86_400
    bet = {
        "game_id": "g3",
        "sport": "football",
        "league": "nfl",
        "total_points_earned": None,
        "event_datetime": past,
        "game_bet": {"bet_type": "spread"},
        "odds_snapshot": {},
        "PK": "ROOM#r1",
        "SK": "POINT#1#USER#u1#EVENT#1",
    }

    # An in-progress (not final) game: grading bails after status check, and
    # enhancement runs from the same payload — still only ONE get_event.
    game_data = {
        "status": {"name": "STATUS_IN_PROGRESS", "state": "in", "completed": False},
        "competitors": [
            {"homeAway": "home", "score": 7, "name": "Home", "abbreviation": "HOM"},
            {"homeAway": "away", "score": 3, "name": "Away", "abbreviation": "AWY"},
        ],
        "startDate": "2025-01-01T00:00Z",
    }

    mock_client = MagicMock()
    mock_client.get_event.return_value = game_data
    with patch("common.helpers.bet_helper.ESPNClient", return_value=mock_client):
        result = h._grade_and_enhance_bet(bet)

    # Exactly one ESPN fetch for the whole grade+enhance of this bet.
    assert mock_client.get_event.call_count == 1
    # Enhancement applied from that payload.
    assert result.get("game_status", {}).get("home_team", {}).get("score") == 7
