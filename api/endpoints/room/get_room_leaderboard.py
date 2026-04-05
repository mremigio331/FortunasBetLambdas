from fastapi import APIRouter, Request, Path
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger
from decimal import Decimal

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.bet_helper import BetHelper
from common.helpers.user_profile_helper import UserProfileHelper
from common.helpers.room_membership_validator import (
    validate_room_membership,
    get_active_member_ids,
)
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


def convert_decimals_to_floats(obj):
    """Recursively convert Decimal values to float for JSON serialization."""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {key: convert_decimals_to_floats(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals_to_floats(item) for item in obj]
    return obj


@router.get("/{room_id}/leaderboard")
@jwt_required()
@exceptions_decorator
def get_room_leaderboard(
    request: Request,
    room_id: str = Path(..., description="The room ID to get leaderboard for"),
):
    """
    Returns server-computed leaderboard for all active room members.
    Aggregates graded bets per member and sorts by total_points_earned descending.
    """
    logger.append_keys(request_id=request.state.request_id)
    user_id = request.state.user_id
    request_id = request.state.request_id
    logger.info(f"Getting leaderboard for room {room_id}, requested by user {user_id}")

    validate_room_membership(room_id, user_id, request_id)

    active_member_ids = get_active_member_ids(room_id, request_id)

    bet_helper = BetHelper(request_id=request_id)
    all_bets = bet_helper.get_all_bets_for_room(room_id)

    # Filter bets to only those from active members
    active_member_set = set(active_member_ids)
    member_bets = [b for b in all_bets if b.get("user_id") in active_member_set]

    # Aggregate stats per active member
    stats = {}
    for member_id in active_member_ids:
        stats[member_id] = {
            "total_points_earned": 0.0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "total_bets": 0,
        }

    for bet in member_bets:
        uid = bet.get("user_id")
        if uid not in stats:
            continue
        stats[uid]["total_bets"] += 1

        game_bet = bet.get("game_bet")
        if not game_bet:
            continue
        # game_bet can be a dict (from DynamoDB) or already parsed
        result = (
            game_bet.get("result")
            if isinstance(game_bet, dict)
            else getattr(game_bet, "result", None)
        )
        if result is None:
            continue

        points_earned = (
            game_bet.get("points_earned")
            if isinstance(game_bet, dict)
            else getattr(game_bet, "points_earned", None)
        )
        points_earned = float(points_earned) if points_earned is not None else 0.0

        stats[uid]["total_points_earned"] += points_earned

        if result == "win":
            stats[uid]["wins"] += 1
        elif result == "loss":
            stats[uid]["losses"] += 1
        elif result == "push":
            stats[uid]["pushes"] += 1

    # Get user profiles
    user_profile_helper = UserProfileHelper(request_id=request_id)
    profiles = user_profile_helper.get_multiple_user_profiles(active_member_ids)

    # Build leaderboard entries
    leaderboard = []
    for member_id in active_member_ids:
        s = stats[member_id]
        wins = s["wins"]
        losses = s["losses"]
        win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.0

        profile = profiles.get(member_id, {})
        leaderboard.append(
            {
                "user_id": member_id,
                "user_name": profile.get("name", member_id),
                "user_color": profile.get("color", "black"),
                "total_points_earned": s["total_points_earned"],
                "wins": wins,
                "losses": losses,
                "pushes": s["pushes"],
                "total_bets": s["total_bets"],
                "win_rate": round(win_rate, 3),
            }
        )

    # Sort by total_points_earned descending
    leaderboard.sort(key=lambda x: x["total_points_earned"], reverse=True)

    # Convert any remaining Decimal values
    leaderboard = convert_decimals_to_floats(leaderboard)

    logger.info(f"Leaderboard for room {room_id}: {len(leaderboard)} entries")

    return JSONResponse(
        status_code=200,
        content={
            "message": "Leaderboard retrieved successfully",
            "room_id": room_id,
            "leaderboard": leaderboard,
            "count": len(leaderboard),
        },
    )
