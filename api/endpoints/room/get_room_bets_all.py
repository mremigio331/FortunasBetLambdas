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
from common.helpers.bet_privacy import is_game_started, redact_hidden_bet
from common.constants.services import API_SERVICE
from clients.espn_client import ESPNClient

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


@router.get("/{room_id}/bets/all")
@jwt_required()
@exceptions_decorator
def get_room_bets_all(
    request: Request,
    room_id: str = Path(..., description="The room ID to get bets for"),
):
    """
    Returns all bets for a room with privacy controls applied.
    Own bets are always fully visible. Other users' bets are redacted
    if the associated game has not yet started.
    """
    logger.append_keys(request_id=request.state.request_id)
    user_id = request.state.user_id
    request_id = request.state.request_id
    logger.info(f"Getting all bets for room {room_id}, requested by user {user_id}")

    # Validate room existence and membership
    validate_room_membership(room_id, user_id, request_id)

    # Get active member IDs
    active_member_ids = get_active_member_ids(room_id, request_id)
    active_member_set = set(active_member_ids)

    # Get all bets for the room
    bet_helper = BetHelper(request_id=request_id)
    all_bets = bet_helper.get_all_bets_for_room(room_id)

    # Filter bets to only those from active members
    member_bets = [b for b in all_bets if b.get("user_id") in active_member_set]

    if not member_bets:
        return JSONResponse(
            status_code=200,
            content={
                "message": f"Retrieved bets for room {room_id} successfully",
                "data": {"bets": [], "users": {}, "count": 0, "room_id": room_id},
            },
        )

    # Initialize ESPN client for game status checking
    espn_client = ESPNClient(request_id=request_id)

    # Apply privacy logic to each bet
    processed_bets = []
    for bet in member_bets:
        bet_copy = dict(bet)

        if bet_copy.get("user_id") == user_id:
            # Own bet — always fully visible
            processed_bets.append(bet_copy)
        else:
            # Another user's bet — check game status
            sport = bet_copy.get("sport", "")
            league = bet_copy.get("league", "")
            game_id = bet_copy.get("game_id", "")

            if is_game_started(espn_client, sport, league, game_id):
                # Game started/completed — fully visible
                processed_bets.append(bet_copy)
            else:
                # Game not started or ESPN unavailable — redact
                processed_bets.append(redact_hidden_bet(bet_copy))

    # Get unique user IDs from processed bets for profile lookup
    unique_user_ids = list(
        set(b.get("user_id") for b in processed_bets if b.get("user_id"))
    )

    # Fetch user profiles
    user_profile_helper = UserProfileHelper(request_id=request_id)
    user_profiles = user_profile_helper.get_multiple_user_profiles(unique_user_ids)

    # Convert Decimal values to float/int for JSON serialization
    serializable_bets = convert_decimals_to_floats(processed_bets)

    logger.info(f"Retrieved {len(serializable_bets)} bets for room {room_id}")

    return JSONResponse(
        status_code=200,
        content={
            "message": f"Retrieved bets for room {room_id} successfully",
            "data": {
                "bets": serializable_bets,
                "users": user_profiles,
                "count": len(serializable_bets),
                "room_id": room_id,
            },
        },
    )
