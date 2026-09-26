"""Tests for the per-user standings endpoints.

/room/{id}/standings/members returns active members with profiles (fast, no
bets). /room/{id}/bets/user/{target} returns one user's bets via the display
read path (grade-if-needed once, no live ESPN enhancement) with a cheap
event_datetime privacy gate for other users' not-yet-started games.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from api.endpoints.room import get_room_standings_members, get_room_user_bets


class _FakeRequest:
    def __init__(self, token="t", request_id="test"):
        self.headers = {"authorization": f"Bearer {token}"}
        self.state = SimpleNamespace(request_id=request_id)


def _call(coro_fn, *args, **kwargs):
    resp = asyncio.run(coro_fn(*args, **kwargs))
    return json.loads(resp.body.decode())


_JWT = {"sub": "viewer-1"}


def test_standings_members_returns_active_members_with_profiles():
    with patch(
        "api.decorators.jwt_decorator.decode_jwt", return_value=_JWT
    ), patch.object(
        get_room_standings_members, "validate_room_membership"
    ), patch.object(
        get_room_standings_members,
        "get_active_member_ids",
        return_value=["viewer-1", "u2"],
    ), patch.object(
        get_room_standings_members, "UserProfileHelper"
    ) as MockProfiles:
        MockProfiles.return_value.get_multiple_user_profiles.return_value = {
            "viewer-1": {"name": "Me", "color": "green"},
            "u2": {"name": "Bob", "color": "blue"},
        }
        body = _call(
            get_room_standings_members.get_room_standings_members,
            _FakeRequest(),
            room_id="r1",
        )

    assert body["count"] == 2
    me = next(m for m in body["members"] if m["user_id"] == "viewer-1")
    assert me["is_current_user"] is True
    assert me["user_name"] == "Me"


def test_user_bets_own_bets_are_not_redacted():
    own_bets = [
        {
            "user_id": "viewer-1",
            "game_id": "g1",
            "event_datetime": 1,  # long past -> started anyway
            "game_bet": {"result": "win", "points_earned": 3},
            "points_wagered": 3,
        }
    ]
    fake_bet = MagicMock()
    fake_bet.get_user_bets_for_room_for_display.return_value = own_bets

    with patch(
        "api.decorators.jwt_decorator.decode_jwt", return_value=_JWT
    ), patch.object(get_room_user_bets, "validate_room_membership"), patch.object(
        get_room_user_bets, "BetHelper", return_value=fake_bet
    ):
        body = _call(
            get_room_user_bets.get_room_user_bets,
            _FakeRequest(),
            room_id="r1",
            target_user_id="viewer-1",
        )

    assert body["count"] == 1
    assert body["bets"][0]["game_bet"]["result"] == "win"


def test_user_bets_other_users_future_games_are_redacted():
    future = 9_999_999_999  # far in the future -> not started
    other_bets = [
        {
            "user_id": "u2",
            "game_id": "g2",
            "event_datetime": future,
            "game_bet": {"team_choice": "home"},
            "odds_snapshot": {"spread": -3},
            "total_points_earned": None,
            "points_wagered": 2,
        }
    ]
    fake_bet = MagicMock()
    fake_bet.get_user_bets_for_room_for_display.return_value = other_bets

    with patch(
        "api.decorators.jwt_decorator.decode_jwt", return_value=_JWT
    ), patch.object(get_room_user_bets, "validate_room_membership"), patch.object(
        get_room_user_bets, "BetHelper", return_value=fake_bet
    ):
        body = _call(
            get_room_user_bets.get_room_user_bets,
            _FakeRequest(),
            room_id="r1",
            target_user_id="u2",
        )

    # Redacted: game_bet cleared, odds_snapshot emptied, points nulled.
    assert body["bets"][0]["game_bet"] is None
    assert body["bets"][0]["odds_snapshot"] == {}


def test_user_bets_other_users_started_games_are_visible():
    past = 1  # started
    other_bets = [
        {
            "user_id": "u2",
            "game_id": "g3",
            "event_datetime": past,
            "game_bet": {"result": "loss", "points_earned": 0},
            "points_wagered": 1,
        }
    ]
    fake_bet = MagicMock()
    fake_bet.get_user_bets_for_room_for_display.return_value = other_bets

    with patch(
        "api.decorators.jwt_decorator.decode_jwt", return_value=_JWT
    ), patch.object(get_room_user_bets, "validate_room_membership"), patch.object(
        get_room_user_bets, "BetHelper", return_value=fake_bet
    ):
        body = _call(
            get_room_user_bets.get_room_user_bets,
            _FakeRequest(),
            room_id="r1",
            target_user_id="u2",
        )

    assert body["bets"][0]["game_bet"]["result"] == "loss"
