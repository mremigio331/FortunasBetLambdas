"""Comprehensive unit tests for BetHelper.

BetHelper mixes DynamoDB access with pure grading/validation logic. Tests mock
the boto3 table (self.table) and ESPN client so we exercise the real code paths
without network or AWS. Grouped by concern: decimal conversions, bet grading
(spread + over/under), result persistence, odds-snapshot validation, the
DynamoDB query/filter helpers, and create_bet's duplicate detection.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from common.helpers.bet_helper import BetHelper


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_helper():
    """A BetHelper with boto3 stubbed out and a MagicMock table."""
    with patch("common.helpers.bet_helper.boto3"):
        helper = BetHelper(request_id="test", table_name="TestTable")
    helper.table = MagicMock()
    return helper


def query_returning(items):
    """Configure a helper's table.query to return the given items."""

    def _query(**kwargs):
        return {"Items": items}

    return _query


def spread_bet(team_choice="home", spread=-3.0, favored="home", points=2):
    return {
        "game_id": "g1",
        "sport": "football",
        "league": "nfl",
        "points_wagered": points,
        "game_bet": {"bet_type": "spread", "team_choice": team_choice},
        "odds_snapshot": {"spread": spread, "favoredTeam": favored},
    }


def total_bet(choice="over", total_value=45.5, points=1):
    return {
        "game_id": "g1",
        "sport": "football",
        "league": "nfl",
        "points_wagered": points,
        "game_bet": {
            "bet_type": "over_under",
            "over_under_choice": choice,
            "total_value": total_value,
        },
    }


def game(home_score, away_score):
    return {
        "status": {"name": "STATUS_FINAL", "state": "post", "completed": True},
        "competitors": [
            {"homeAway": "home", "score": home_score, "name": "Home"},
            {"homeAway": "away", "score": away_score, "name": "Away"},
        ],
    }


# ---------------------------------------------------------------------------
# Decimal <-> float conversion
# ---------------------------------------------------------------------------


class TestDecimalConversion:
    def test_floats_to_decimals_nested(self):
        h = make_helper()
        out = h._convert_floats_to_decimals(
            {"a": 1.5, "b": [2.5, {"c": 3.0}], "d": "x", "e": 4}
        )
        assert out["a"] == Decimal("1.5")
        assert out["b"][0] == Decimal("2.5")
        assert out["b"][1]["c"] == Decimal("3.0")
        assert out["d"] == "x"
        assert out["e"] == 4  # ints untouched

    def test_decimals_to_floats_nested(self):
        h = make_helper()
        out = h._convert_decimals_to_floats(
            {"a": Decimal("1.5"), "b": [Decimal("2.5")], "c": "x"}
        )
        assert out["a"] == 1.5
        assert isinstance(out["a"], float)
        assert out["b"][0] == 2.5
        assert out["c"] == "x"

    def test_round_trip_preserves_values(self):
        h = make_helper()
        original = {"score": 7.0, "nested": {"pts": 2.5}}
        assert (
            h._convert_decimals_to_floats(h._convert_floats_to_decimals(original))
            == original
        )


# ---------------------------------------------------------------------------
# Spread grading
# ---------------------------------------------------------------------------


class TestGradeSpreadBet:
    def test_favored_home_covers_win(self):
        h = make_helper()
        # Home favored by 3, home wins by 10 -> covers -> win.
        pts, result = h._grade_spread_bet(
            spread_bet("home", -3.0, "home", 2), game(24, 14)
        )
        assert result == "win"
        assert pts == 2.0

    def test_favored_home_fails_to_cover_loss(self):
        h = make_helper()
        # Home favored by 3, wins by only 2 -> does not cover -> loss.
        pts, result = h._grade_spread_bet(
            spread_bet("home", -3.0, "home", 2), game(16, 14)
        )
        assert result == "loss"
        assert pts == 0.0

    def test_exact_cover_is_push(self):
        h = make_helper()
        # Home favored by 3, wins by exactly 3 -> push.
        pts, result = h._grade_spread_bet(
            spread_bet("home", -3.0, "home", 2), game(17, 14)
        )
        assert result == "push"
        assert pts == 1.0  # half of points_wagered

    def test_underdog_covers_win(self):
        h = make_helper()
        # Away is the underdog (+3); loses by 2 -> underdog covers -> win.
        pts, result = h._grade_spread_bet(
            spread_bet("away", -3.0, "home", 3), game(16, 14)
        )
        assert result == "win"
        assert pts == 3.0

    def test_spread_details_fallback_when_no_spread(self):
        h = make_helper()
        bet = {
            "game_id": "g1",
            "points_wagered": 1,
            "game_bet": {"bet_type": "spread", "team_choice": "home"},
            "odds_snapshot": {"spreadDetails": "HOME -7"},  # no numeric spread
        }
        # Home favored by 7, wins by 10 -> covers.
        pts, result = h._grade_spread_bet(bet, game(30, 20))
        assert result == "win"

    def test_invalid_team_choice_returns_none(self):
        h = make_helper()
        bet = spread_bet(team_choice="sideways")
        assert h._grade_spread_bet(bet, game(10, 7)) is None

    def test_missing_spread_returns_none(self):
        h = make_helper()
        bet = {
            "game_id": "g1",
            "points_wagered": 1,
            "game_bet": {"bet_type": "spread", "team_choice": "home"},
            "odds_snapshot": {},  # no spread, no details
        }
        assert h._grade_spread_bet(bet, game(10, 7)) is None

    def test_missing_competitor_scores_returns_none(self):
        h = make_helper()
        assert h._grade_spread_bet(spread_bet(), {"competitors": []}) is None


# ---------------------------------------------------------------------------
# Over/Under grading
# ---------------------------------------------------------------------------


class TestGradeOverUnderBet:
    def test_over_hits_win(self):
        h = make_helper()
        # total 50 > 45.5 line, choice over -> win.
        pts, result = h._grade_over_under_bet(total_bet("over", 45.5, 1), game(30, 20))
        assert result == "win"
        assert pts == 1.0

    def test_over_misses_loss(self):
        h = make_helper()
        pts, result = h._grade_over_under_bet(total_bet("over", 45.5, 1), game(20, 20))
        assert result == "loss"
        assert pts == 0.0

    def test_under_hits_win(self):
        h = make_helper()
        pts, result = h._grade_over_under_bet(total_bet("under", 45.5, 2), game(20, 20))
        assert result == "win"
        assert pts == 2.0

    def test_exact_total_is_push(self):
        h = make_helper()
        # total exactly 44 == line -> push.
        pts, result = h._grade_over_under_bet(total_bet("over", 44.0, 2), game(24, 20))
        assert result == "push"
        assert pts == 1.0

    def test_no_competitors_returns_none(self):
        h = make_helper()
        assert h._grade_over_under_bet(total_bet(), {"competitors": []}) is None


# ---------------------------------------------------------------------------
# validate_odds_snapshot
# ---------------------------------------------------------------------------


class TestValidateOddsSnapshot:
    def _event(self, provider="Draft Kings", spread=-3.0, ou=45.5):
        return {
            "pickcenter": [
                {
                    "provider": {"name": provider},
                    "spread": spread,
                    "overUnder": ou,
                    "homeTeamOdds": {"moneyLine": -150, "spreadOdds": -110},
                    "awayTeamOdds": {"moneyLine": 130, "spreadOdds": -110},
                }
            ]
        }

    def test_matching_snapshot_passes(self):
        h = make_helper()
        snap = {
            "spread": -3.0,
            "overUnder": 45.5,
            "homeTeamOdds": {"moneyLine": -150, "spreadOdds": -110},
            "awayTeamOdds": {"moneyLine": 130, "spreadOdds": -110},
        }
        assert h.validate_odds_snapshot(snap, self._event()) is True

    def test_mismatched_spread_fails(self):
        h = make_helper()
        snap = {"spread": -7.0, "overUnder": 45.5}
        assert h.validate_odds_snapshot(snap, self._event()) is False

    def test_none_moneyline_is_wildcard(self):
        h = make_helper()
        # None in request should match any provider value.
        snap = {
            "spread": -3.0,
            "overUnder": 45.5,
            "homeTeamOdds": {"moneyLine": None, "spreadOdds": None},
            "awayTeamOdds": {"moneyLine": None, "spreadOdds": None},
        }
        assert h.validate_odds_snapshot(snap, self._event()) is True

    def test_no_pickcenter_fails(self):
        h = make_helper()
        assert h.validate_odds_snapshot({"spread": -3.0}, {"pickcenter": []}) is False

    def test_falls_back_to_first_provider(self):
        h = make_helper()
        snap = {
            "spread": -3.0,
            "overUnder": 45.5,
            "homeTeamOdds": {"moneyLine": -150, "spreadOdds": -110},
            "awayTeamOdds": {"moneyLine": 130, "spreadOdds": -110},
        }
        # No Draft Kings -> uses the only provider present.
        assert h.validate_odds_snapshot(snap, self._event(provider="FanDuel")) is True


# ---------------------------------------------------------------------------
# Query/filter helpers (removed exclusion, user filtering)
# ---------------------------------------------------------------------------


class TestQueryHelpers:
    def test_get_user_game_ids_excludes_removed_and_other_users(self):
        h = make_helper()
        h.table.query = query_returning(
            [
                {"SK": "POINT#1#USER#u1#EVENT#1", "game_id": "gA"},
                {"SK": "POINT#2#USER#u1#EVENT#2", "game_id": "gB"},
                {"SK": "REMOVED#POINT#1#USER#u1#EVENT#3", "game_id": "gC"},
                {"SK": "POINT#1#USER#u2#EVENT#4", "game_id": "gD"},
            ]
        )
        ids = h.get_user_game_ids_for_room("r1", "u1")
        assert set(ids) == {"gA", "gB"}  # gC removed, gD other user

    def test_find_user_bet_by_game_id_active_only(self):
        h = make_helper()
        h.table.query = query_returning(
            [
                {"SK": "REMOVED#POINT#1#USER#u1#EVENT#1", "game_id": "gX"},
                {"SK": "POINT#1#USER#u1#EVENT#2", "game_id": "gX", "week": 3},
            ]
        )
        found = h.find_user_bet_by_game_id("r1", "u1", "gX")
        assert found is not None
        assert found["week"] == 3

    def test_find_user_bet_by_game_id_not_found(self):
        h = make_helper()
        h.table.query = query_returning(
            [{"SK": "POINT#1#USER#u2#EVENT#1", "game_id": "gX"}]
        )
        assert h.find_user_bet_by_game_id("r1", "u1", "gX") is None

    def test_removed_bets_tagged_and_filtered(self):
        h = make_helper()
        h.table.query = query_returning(
            [
                {"SK": "REMOVED#POINT#1#USER#u1#EVENT#1", "game_id": "gA"},
                {"SK": "REMOVED#POINT#1#USER#u2#EVENT#2", "game_id": "gB"},
            ]
        )
        removed = h.get_removed_bets_for_user("r1", "u1")
        assert len(removed) == 1
        assert removed[0]["status"] == "removed"


# ---------------------------------------------------------------------------
# create_bet duplicate detection
# ---------------------------------------------------------------------------


class TestCreateBet:
    def _bet_model(self):
        m = MagicMock()
        m.room_id = "r1"
        m.user_id = "u1"
        m.points_wagered = 1
        m.event_datetime = 100
        m.sport = "football"
        m.league = "nfl"
        m.game_id = "gA"
        m.dict.return_value = {
            "room_id": "r1",
            "user_id": "u1",
            "points_wagered": 1,
            "event_datetime": 100,
            "game_id": "gA",
        }
        return m

    def test_duplicate_exact_bet_raises(self):
        from exceptions.bet_exceptions import DuplicateBetException

        h = make_helper()
        with patch.object(h, "get_bet", return_value={"SK": "existing"}):
            with pytest.raises(DuplicateBetException):
                h.create_bet(self._bet_model())

    def test_duplicate_game_raises(self):
        from exceptions.bet_exceptions import DuplicateGameException

        h = make_helper()
        with patch.object(h, "get_bet", return_value=None), patch.object(
            h, "validate_week_boundary_bet", return_value=True
        ), patch.object(h, "get_user_game_ids_for_room", return_value=["gA"]):
            with pytest.raises(DuplicateGameException):
                h.create_bet(self._bet_model())

    def test_successful_create_puts_item(self):
        h = make_helper()
        with patch.object(h, "get_bet", return_value=None), patch.object(
            h, "validate_week_boundary_bet", return_value=True
        ), patch.object(h, "get_user_game_ids_for_room", return_value=[]), patch.object(
            h, "_get_removed_game_ids_for_user", return_value=[]
        ):
            result = h.create_bet(self._bet_model())
        assert h.table.put_item.called
        assert result["PK"] == "ROOM#r1"
        assert "POINT#1#USER#u1#EVENT#100" in result["SK"]


# ---------------------------------------------------------------------------
# Room/user read methods (route through grade+enhance)
# ---------------------------------------------------------------------------


class TestReadMethods:
    def test_get_all_bets_for_room_excludes_removed(self):
        h = make_helper()
        h.table.query = query_returning(
            [
                {
                    "SK": "POINT#1#USER#u1#EVENT#1",
                    "game_id": "gA",
                    "total_points_earned": 1.0,
                },
                {"SK": "REMOVED#POINT#1#USER#u1#EVENT#2", "game_id": "gB"},
            ]
        )
        # Both are graded/removed so no ESPN call is needed.
        with patch("common.helpers.bet_helper.ESPNClient") as MockClient:
            bets = h.get_all_bets_for_room("r1")
        MockClient.assert_not_called()
        assert len(bets) == 1
        assert bets[0]["game_id"] == "gA"

    def test_get_user_bets_for_room_filters_user_and_removed(self):
        h = make_helper()
        h.table.query = query_returning(
            [
                {
                    "SK": "POINT#1#USER#u1#EVENT#1",
                    "game_id": "gA",
                    "total_points_earned": 0.0,
                },
                {
                    "SK": "POINT#2#USER#u2#EVENT#2",
                    "game_id": "gB",
                    "total_points_earned": 0.0,
                },
                {"SK": "REMOVED#POINT#1#USER#u1#EVENT#3", "game_id": "gC"},
            ]
        )
        with patch("common.helpers.bet_helper.ESPNClient") as MockClient:
            bets = h.get_user_bets_for_room("r1", "u1")
        MockClient.assert_not_called()
        assert [b["game_id"] for b in bets] == ["gA"]

    def test_display_path_grades_without_enhancement(self):
        h = make_helper()
        h.table.query = query_returning(
            [
                {
                    "SK": "POINT#1#USER#u1#EVENT#1",
                    "game_id": "gA",
                    "total_points_earned": 3.0,
                },
            ]
        )
        # Graded bet -> no ESPN, no game_status enhancement added.
        with patch("common.helpers.bet_helper.ESPNClient") as MockClient:
            bets = h.get_user_bets_for_room_for_display("r1", "u1")
        MockClient.assert_not_called()
        assert len(bets) == 1
        assert "game_status" not in bets[0]

    def test_get_bets_by_point_value_returns_items(self):
        h = make_helper()
        h.table.query = query_returning(
            [
                {
                    "SK": "POINT#2#USER#u1#EVENT#1",
                    "game_id": "gA",
                    "total_points_earned": 2.0,
                },
            ]
        )
        with patch("common.helpers.bet_helper.ESPNClient"):
            bets = h.get_bets_by_point_value("r1", 2)
        assert len(bets) == 1


# ---------------------------------------------------------------------------
# _update_bet_result
# ---------------------------------------------------------------------------


class TestUpdateBetResult:
    def test_persists_and_returns_updated_bet(self):
        h = make_helper()
        bet = {
            "PK": "ROOM#r1",
            "SK": "POINT#1#USER#u1#EVENT#1",
            "game_id": "gA",
            "user_id": "u1",
            "room_id": "r1",
            "game_bet": {"bet_type": "spread", "team_choice": "home"},
        }
        updated = h._update_bet_result(bet, 2.0, "win")
        assert h.table.put_item.called
        assert updated["total_points_earned"] == 2.0
        assert updated["game_bet"]["result"] == "win"
        assert updated["game_bet"]["points_earned"] == 2.0


# ---------------------------------------------------------------------------
# validate_week_boundary_bet
# ---------------------------------------------------------------------------


class TestValidateWeekBoundaryBet:
    def test_duplicate_in_week_raises(self):
        from exceptions.bet_exceptions import DuplicateBetException

        h = make_helper()
        h.table.query = query_returning(
            [{"SK": "POINT#1#USER#u1#EVENT#5", "event_datetime": 5}]
        )
        with patch("common.helpers.week_helper.WeekHelper") as MockWeek:
            MockWeek.return_value.get_week_boundary.return_value = (1, 10)
            with pytest.raises(DuplicateBetException):
                h.validate_week_boundary_bet(
                    room_id="r1",
                    user_id="u1",
                    points_wagered=1,
                    sport="football",
                    league="nfl",
                    event_datetime=5,
                    game_id="gA",
                )

    def test_no_conflict_passes(self):
        h = make_helper()
        h.table.query = query_returning([])
        with patch("common.helpers.week_helper.WeekHelper") as MockWeek:
            MockWeek.return_value.get_week_boundary.return_value = (1, 10)
            assert (
                h.validate_week_boundary_bet(
                    room_id="r1",
                    user_id="u1",
                    points_wagered=1,
                    sport="football",
                    league="nfl",
                    event_datetime=5,
                    game_id="gA",
                )
                is True
            )

    def test_no_week_boundary_allows_bet(self):
        h = make_helper()
        with patch("common.helpers.week_helper.WeekHelper") as MockWeek:
            MockWeek.return_value.get_week_boundary.return_value = None
            assert (
                h.validate_week_boundary_bet(
                    room_id="r1",
                    user_id="u1",
                    points_wagered=1,
                    sport="football",
                    league="nfl",
                    event_datetime=5,
                    game_id="gA",
                )
                is True
            )
