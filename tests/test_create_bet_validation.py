"""Tests for create_bet's up-front odds_snapshot validation.

A bet whose odds_snapshot is missing the line its type needs (a null-odds
snapshot, e.g. from an odds-less slate) must be rejected with a clean 400
before any ESPN work — not surface as a 500.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api.endpoints.bet import create_bet as create_bet_mod


def _request():
    return SimpleNamespace(state=SimpleNamespace(request_id="test", user_token="u1"))


def _bet_request(bet_type, odds_snapshot, total_value=None, spread_value=None):
    game_bet = SimpleNamespace(
        game_id="g1",
        bet_type=bet_type,
        team_choice="home" if bet_type == "spread" else None,
        spread_value=spread_value,
        over_under_choice="over" if bet_type == "over_under" else None,
        total_value=total_value,
        points_wagered=2,
    )
    return SimpleNamespace(
        room_id="r1",
        season_type=2,
        week=4,
        event_datetime=1_800_000_000,
        game_id="g1",
        sport="football",
        league="nfl",
        game_bet=game_bet,
        odds_snapshot=odds_snapshot,
        dict=lambda: {"game_id": "g1", "bet_type": bet_type},
    )


def _body(resp):
    return json.loads(resp.body.decode())


def test_over_under_with_null_total_returns_400():
    # Null-odds snapshot (what the odds-less slate produced). The endpoint
    # is wrapped by exceptions_decorator, so the raised InvalidBetTypeException
    # comes back as a 400 JSON response.
    br = _bet_request("over_under", {"overUnder": None}, total_value=None)
    resp = create_bet_mod.create_bet(_request(), br)
    assert resp.status_code == 400
    assert "total_value" in _body(resp)["message"]


def test_spread_with_null_spread_returns_400():
    br = _bet_request("spread", {"spread": None}, spread_value=None)
    resp = create_bet_mod.create_bet(_request(), br)
    assert resp.status_code == 400
    assert "spread_value" in _body(resp)["message"]


def test_over_under_with_valid_total_passes_validation():
    """A populated snapshot should get past the up-front check (and then hit the
    mocked membership path, proving the early guard did not fire)."""
    br = _bet_request("over_under", {"overUnder": 46.5}, total_value=None)

    fake_membership = MagicMock()
    # Not a member -> 403, which proves we got PAST the odds guard.
    fake_membership.get_membership.return_value = None

    with patch.object(create_bet_mod, "MembershipHelper", return_value=fake_membership):
        resp = create_bet_mod.create_bet(_request(), br)

    assert resp.status_code == 403  # reached membership check, guard passed
