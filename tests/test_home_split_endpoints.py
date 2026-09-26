"""Tests for the split home-page endpoints.

/home/rooms returns just the user's approved active rooms (fast, no bets/week),
and /home/rooms/{id}/current-bets returns one room's current-week bets. Together
they replace the single blocking /home/get_home_data for progressive loading.

The endpoints are wrapped by @jwt_required() (async) + @exceptions_decorator, so
tests await the coroutine and drive auth via a Bearer header with a mocked JWT
decode that yields a `sub`.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from api.endpoints.home import get_home_rooms, get_room_current_bets


class _FakeRequest:
    """Minimal stand-in for a Starlette Request that jwt_required understands."""

    def __init__(self, token="t", request_id="test"):
        self.headers = {"authorization": f"Bearer {token}"}
        self.state = SimpleNamespace(request_id=request_id)


def _call(coro_fn, *args, **kwargs):
    """Await an async-decorated endpoint and JSON-decode its response body."""
    resp = asyncio.run(coro_fn(*args, **kwargs))
    return json.loads(resp.body.decode())


# jwt_required decodes the token to get `sub`; make that deterministic.
_JWT = {"sub": "user-1"}


def test_home_rooms_returns_only_approved_active_rooms():
    memberships = [
        {"PK": "ROOM#r1", "status": "approved"},
        {"PK": "ROOM#r2", "status": "approved"},
        {"PK": "ROOM#r3", "status": "pending"},  # excluded: not approved
        {"PK": "ROOM#r4", "status": "approved"},  # excluded: Completed below
    ]
    rooms_by_id = {
        "r1": {"room_name": "Alpha", "sport": "NFL", "status": "Active"},
        "r2": {"room_name": "Bravo", "sport": "MLB", "status": "Active"},
        "r4": {"room_name": "Delta", "sport": "NFL", "status": "Completed"},
    }

    fake_membership = MagicMock()
    fake_membership.get_all_membership_requests_for_user.return_value = memberships
    fake_room = MagicMock()
    fake_room.get_room.side_effect = lambda rid: rooms_by_id.get(rid)

    with patch("common.helpers.jwt.decode_jwt", return_value=_JWT), patch(
        "api.decorators.jwt_decorator.decode_jwt", return_value=_JWT
    ), patch.object(
        get_home_rooms, "MembershipHelper", return_value=fake_membership
    ), patch.object(
        get_home_rooms, "RoomHelper", return_value=fake_room
    ):
        body = _call(get_home_rooms.get_home_rooms, _FakeRequest())

    assert body["room_count"] == 2
    names = {r["room_name"] for r in body["rooms"]}
    assert names == {"Alpha", "Bravo"}
    assert all("bets" not in r for r in body["rooms"])


def test_home_rooms_empty_when_no_approved_memberships():
    fake_membership = MagicMock()
    fake_membership.get_all_membership_requests_for_user.return_value = [
        {"PK": "ROOM#r1", "status": "pending"}
    ]
    with patch(
        "api.decorators.jwt_decorator.decode_jwt", return_value=_JWT
    ), patch.object(
        get_home_rooms, "MembershipHelper", return_value=fake_membership
    ), patch.object(
        get_home_rooms, "RoomHelper", return_value=MagicMock()
    ):
        body = _call(get_home_rooms.get_home_rooms, _FakeRequest())

    assert body["room_count"] == 0
    assert body["rooms"] == []


def test_room_current_bets_nfl_buckets_by_week():
    room = {"sport": "NFL"}
    active_bets = [{"event_datetime": 1_700_000_000, "points_wagered": 1}]

    fake_room = MagicMock()
    fake_room.get_room.return_value = room
    fake_bet = MagicMock()
    fake_bet.get_user_bets_for_room.return_value = active_bets
    fake_week = MagicMock()
    fake_week.get_nfl_current_week.return_value = {
        "week_start": "2000-01-01T00:00:00+00:00",
        "week_end": "2100-01-01T00:00:00+00:00",
    }

    with patch(
        "api.decorators.jwt_decorator.decode_jwt", return_value=_JWT
    ), patch.object(
        get_room_current_bets, "RoomHelper", return_value=fake_room
    ), patch.object(
        get_room_current_bets, "BetHelper", return_value=fake_bet
    ), patch.object(
        get_room_current_bets, "WeekHelper", return_value=fake_week
    ):
        body = _call(
            get_room_current_bets.get_room_current_bets, _FakeRequest(), room_id="r1"
        )

    assert body["room_sport"] == "NFL"
    assert body["bets"]["sport"] == "NFL"
    assert body["bets"]["one_point"] == active_bets[0]


def test_room_current_bets_missing_room_returns_empty():
    fake_room = MagicMock()
    fake_room.get_room.return_value = None
    with patch(
        "api.decorators.jwt_decorator.decode_jwt", return_value=_JWT
    ), patch.object(
        get_room_current_bets, "RoomHelper", return_value=fake_room
    ), patch.object(
        get_room_current_bets, "BetHelper", return_value=MagicMock()
    ):
        body = _call(
            get_room_current_bets.get_room_current_bets, _FakeRequest(), room_id="ghost"
        )

    assert body["bets"] == {}
    assert body["room_id"] == "ghost"
