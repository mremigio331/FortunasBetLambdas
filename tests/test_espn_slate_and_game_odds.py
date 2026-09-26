"""Tests for the progressive-load ESPN client methods used by the /games
endpoints: get_slate (bulk, no odds) and get_game_odds (single game).

These back the fix for the API Lambda timeouts by replacing per-game summary
fan-out with one bulk scoreboard call plus lazy per-game odds.
"""

from unittest.mock import patch, MagicMock

from clients.espn_client import ESPNClient


def _nfl_scoreboard_fixture():
    """Minimal NFL scoreboard shape matching the live ESPN response."""
    return {
        "events": [
            {
                "id": "401872948",
                "name": "Atlanta Falcons at Green Bay Packers",
                "date": "2025-09-21T17:00Z",
                "competitions": [
                    {
                        "status": {
                            "type": {
                                "name": "STATUS_FINAL",
                                "state": "post",
                                "completed": True,
                                "detail": "Final",
                                "shortDetail": "Final",
                            }
                        },
                        "competitors": [
                            {
                                "homeAway": "home",
                                "score": "14",
                                "winner": False,
                                "team": {
                                    "id": "9",
                                    "displayName": "Green Bay Packers",
                                    "abbreviation": "GB",
                                },
                            },
                            {
                                "homeAway": "away",
                                "score": "35",
                                "winner": True,
                                "team": {
                                    "id": "1",
                                    "displayName": "Atlanta Falcons",
                                    "abbreviation": "ATL",
                                },
                            },
                        ],
                        "venue": {"fullName": "Lambeau Field", "address": {}},
                        "odds": [
                            {"spread": -3.0, "overUnder": 45.5, "details": "GB -3"}
                        ],
                    }
                ],
            },
            {
                "id": "401872953",
                "name": "Buffalo Bills at Miami Dolphins",
                "date": "2025-09-27T17:00Z",
                "competitions": [
                    {
                        "status": {
                            "type": {
                                "name": "STATUS_SCHEDULED",
                                "state": "pre",
                                "completed": False,
                                "detail": "Scheduled",
                                "shortDetail": "9/27 - 1:00 PM EDT",
                            }
                        },
                        "competitors": [
                            {
                                "homeAway": "home",
                                "score": "0",
                                "team": {
                                    "id": "15",
                                    "displayName": "Miami Dolphins",
                                    "abbreviation": "MIA",
                                },
                            },
                            {
                                "homeAway": "away",
                                "score": "0",
                                "team": {
                                    "id": "2",
                                    "displayName": "Buffalo Bills",
                                    "abbreviation": "BUF",
                                },
                            },
                        ],
                        "venue": {"fullName": "Hard Rock Stadium", "address": {}},
                    }
                ],
            },
        ]
    }


def test_get_slate_returns_all_games_without_odds():
    """Slate returns every game normalised, with null odds placeholders."""
    client = ESPNClient(request_id="test")
    with patch.object(
        client, "get_nfl_scoreboard", return_value=_nfl_scoreboard_fixture()
    ) as mock_sb:
        games = client.get_slate(
            sport="football", league="nfl", week=4, year=2025, season_type=2
        )

    mock_sb.assert_called_once_with(week=4, year=2025, season_type=2)
    assert len(games) == 2

    game_ids = {g["game_id"] for g in games}
    assert game_ids == {"401872948", "401872953"}

    # Slate must NOT populate odds even when the scoreboard event carries them.
    for g in games:
        assert g["spread"] is None
        assert g["overUnder"] is None
        assert g["homeTeamOdds"] is None

    # Status + scores must be present for the read/grading path.
    final = next(g for g in games if g["game_id"] == "401872948")
    assert final["status"]["completed"] is True
    assert final["teams"]["home"]["score"] == "14"
    assert final["teams"]["away"]["score"] == "35"


def test_get_slate_uses_mlb_scoreboard_for_mlb():
    """MLB slate routes to the date-based scoreboard call."""
    client = ESPNClient(request_id="test")
    with patch.object(
        client, "get_mlb_scoreboard", return_value={"events": []}
    ) as mock_mlb, patch.object(client, "get_nfl_scoreboard") as mock_nfl:
        games = client.get_slate(sport="baseball", league="mlb", date="20250920")

    mock_mlb.assert_called_once_with("20250920")
    mock_nfl.assert_not_called()
    assert games == []


def test_get_slate_skips_unparseable_events():
    """A malformed event is skipped, not fatal to the whole slate."""
    client = ESPNClient(request_id="test")
    bad = {"events": [{"id": "bad"}, *_nfl_scoreboard_fixture()["events"]]}
    with patch.object(client, "get_nfl_scoreboard", return_value=bad):
        games = client.get_slate(sport="football", league="nfl", week=4, year=2025)
    # 2 good events parse; the bad one (no competitions) is skipped.
    assert len(games) == 2


def test_get_game_odds_nfl_attaches_spread_and_total():
    """NFL single-game odds hit the core API and normalise via _attach_odds."""
    client = ESPNClient(request_id="test")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "items": [
            {
                "spread": -7.0,
                "overUnder": 50.5,
                "details": "BUF -7",
                "homeTeamOdds": {"moneyLine": 250, "spreadOdds": -110},
                "awayTeamOdds": {"moneyLine": -300, "spreadOdds": -110},
            }
        ]
    }
    mock_resp.raise_for_status.return_value = None

    with patch("clients.espn_client.requests.get", return_value=mock_resp) as mock_get:
        odds = client.get_game_odds(sport="football", league="nfl", game_id="401872953")

    assert mock_get.called
    called_url = mock_get.call_args[0][0]
    assert "events/401872953/competitions/401872953/odds" in called_url
    assert odds["game_id"] == "401872953"
    assert odds["spread"] == -7.0
    assert odds["overUnder"] == 50.5
    assert odds["favoredTeam"] == "home"  # negative spread -> home favored
    assert odds["homeTeamOdds"]["moneyLine"] == 250


def test_get_game_odds_mlb_uses_game_odds_items():
    """MLB single-game odds read from get_mlb_game_odds items."""
    client = ESPNClient(request_id="test")
    with patch.object(
        client,
        "get_mlb_game_odds",
        return_value={
            "items": [{"spread": 1.5, "overUnder": 8.5, "details": "NYY -1.5"}]
        },
    ) as mock_mlb:
        odds = client.get_game_odds(sport="baseball", league="mlb", game_id="12345")

    mock_mlb.assert_called_once_with("12345")
    assert odds["game_id"] == "12345"
    assert odds["overUnder"] == 8.5
    assert odds["favoredTeam"] == "away"  # positive spread -> away favored


def test_get_game_odds_returns_placeholders_when_no_odds():
    """No odds available yields null placeholders, not an error."""
    client = ESPNClient(request_id="test")
    with patch.object(client, "get_mlb_game_odds", return_value={"items": []}):
        odds = client.get_game_odds(sport="baseball", league="mlb", game_id="99999")
    assert odds["game_id"] == "99999"
    assert odds["spread"] is None
    assert odds["overUnder"] is None
