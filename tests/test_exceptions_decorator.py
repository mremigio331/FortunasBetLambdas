"""Tests for exceptions_decorator error mapping.

Confirms known exceptions map to their intended 4xx/5xx, and — critically —
that any unhandled exception is caught and returned as a JSON 500 with a
message rather than propagating to FastAPI as an opaque empty-body 500.
"""

import json
from unittest.mock import MagicMock

from api.decorators.exceptions_decorator import exceptions_decorator
from exceptions.bet_exceptions import (
    OddsSnapshotMismatch,
    InvalidBetTypeException,
    DuplicateBetException,
)


def _body(resp):
    return json.loads(resp.body.decode())


def test_odds_snapshot_mismatch_maps_to_400():
    @exceptions_decorator
    def endpoint(request):
        raise OddsSnapshotMismatch("odds do not match")

    resp = endpoint(MagicMock())
    assert resp.status_code == 400


def test_invalid_bet_type_maps_to_400():
    @exceptions_decorator
    def endpoint(request):
        raise InvalidBetTypeException("over_under", "total_value")

    resp = endpoint(MagicMock())
    assert resp.status_code == 400


def test_duplicate_bet_maps_to_409():
    @exceptions_decorator
    def endpoint(request):
        raise DuplicateBetException("r1", "u1", 2)

    resp = endpoint(MagicMock())
    assert resp.status_code == 409


def test_unhandled_exception_returns_json_500_not_opaque():
    """An exception not in the known list must be caught as a JSON 500 with a
    message — this is the fix for the opaque empty-body 500 on /bet/create."""

    @exceptions_decorator
    def endpoint(request):
        return float(None)  # raises TypeError, previously uncaught

    resp = endpoint(MagicMock())
    assert resp.status_code == 500
    body = _body(resp)
    assert body.get("message")  # non-empty message, not a silent 500


def test_typeerror_message_surfaces():
    @exceptions_decorator
    def endpoint(request):
        raise ValueError("something specific went wrong")

    resp = endpoint(MagicMock())
    assert resp.status_code == 500
    assert "something specific" in _body(resp)["message"]
