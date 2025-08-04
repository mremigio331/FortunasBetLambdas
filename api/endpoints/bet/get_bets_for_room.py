from fastapi import APIRouter, Request, Path, Depends
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from typing import List, Dict, Any, Optional
from datetime import datetime
from decimal import Decimal

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.bet_helper import BetHelper
from common.helpers.user_profile_helper import UserProfileHelper
from common.models.bet import BetModel
from common.constants.services import API_SERVICE
from clients.espn_client import ESPNClient
from exceptions.bet_exceptions import BetNotFound, UserProfileNotFoundException

logger = Logger(service=API_SERVICE)
router = APIRouter()


def convert_decimals_to_floats(obj: Any) -> Any:
    """
    Recursively convert Decimal values back to float values for JSON serialization.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {key: convert_decimals_to_floats(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals_to_floats(item) for item in obj]
    else:
        return obj


class GetBetsForRoomResponse(BetModel):
    """Response model for room bets - extends BetModel for full structure."""

    pass


@router.get("/room/{room_id}/bets", response_model=List[Dict[str, Any]])
@jwt_required()
@exceptions_decorator
def get_bets_for_room(
    request: Request,
    room_id: str = Path(..., description="The room ID to get bets for"),
):
    """
    Get all bets for a specific room.

    Returns full bet details for the requesting user, and partial details
    (user_id, points_wagered, nulled other fields) for other users when
    their games haven't started yet.

    Parameters:
    - room_id: The room ID to retrieve bets for
    """
    logger.append_keys(request_id=request.state.request_id)
    user_id = request.state.user_id
    logger.info(f"Getting bets for room {room_id}, requested by user {user_id}")

    try:
        # Get all bets for the room
        bet_helper = BetHelper(request_id=request.state.request_id)
        room_bets = bet_helper.get_all_bets_for_room(room_id)

        if not room_bets:
            logger.info(f"No bets found for room {room_id}")
            return JSONResponse(
                status_code=200,
                content={
                    "message": f"No bets found for room {room_id}",
                    "data": {"bets": [], "users": {}, "count": 0, "room_id": room_id},
                },
            )

        # Initialize ESPN client for game status checking
        espn_client = ESPNClient(request_id=request.state.request_id)

        # Initialize UserProfileHelper for getting user names
        user_helper = UserProfileHelper(request_id=request.state.request_id)

        # Get unique user IDs from bets
        unique_user_ids = list(
            set(bet.get("user_id") for bet in room_bets if bet.get("user_id"))
        )

        # Fetch user profiles in batch
        user_profiles = {}
        for user_id_item in unique_user_ids:
            profile = user_helper.get_user_profile(user_id_item)
            if not profile or not profile.get("name"):
                raise UserProfileNotFoundException(user_id_item)
            user_profiles[user_id_item] = {
                "name": profile.get("name"),
                "color": profile.get("color", "black"),
            }

        processed_bets = []

        for bet_item in room_bets:
            try:
                # Convert DynamoDB item to BetModel
                bet = BetModel(**bet_item)

                # If this is the requesting user's bet, always return full details
                if bet.user_id == user_id:
                    processed_bets.append(bet.dict())
                    continue

                # For other users' bets, check if game has started
                event_data = espn_client.get_event(bet.sport, bet.league, bet.game_id)

                if not event_data:
                    logger.warning(
                        f"Could not retrieve event data for game {bet.game_id}"
                    )
                    # If we can't get game data, assume game hasn't started and hide details
                    bet.game_bet = None
                    bet.total_points_earned = None
                    bet.odds_snapshot = {}
                    processed_bets.append(bet.dict())
                    continue

                # Check game status
                current_status = event_data.get("status", {}).get("name", "").upper()
                game_started_statuses = [
                    "STATUS_IN_PROGRESS",
                    "IN_PROGRESS",
                    "LIVE",
                    "STATUS_FINAL",
                    "FINAL",
                    "COMPLETED",
                ]

                if current_status in game_started_statuses:
                    # Game has started, return full bet details
                    processed_bets.append(bet.dict())
                else:
                    # Game hasn't started, return partial details only
                    bet.game_bet = None
                    bet.total_points_earned = None
                    bet.odds_snapshot = {}
                    processed_bets.append(bet.dict())

            except Exception as e:
                logger.warning(f"Error processing bet item: {e}")
                continue

        logger.info(
            f"Successfully retrieved {len(processed_bets)} bets for room {room_id}"
        )

        # Convert any remaining Decimal values to floats for JSON serialization
        serializable_bets = convert_decimals_to_floats(processed_bets)

        return JSONResponse(
            status_code=200,
            content={
                "message": f"Retrieved bets for room {room_id} successfully",
                "data": {
                    "bets": serializable_bets,
                    "users": user_profiles,  # Include user profiles separately
                    "count": len(serializable_bets),
                    "room_id": room_id,
                },
            },
        )

    except BetNotFound:
        logger.info(f"No bets found for room {room_id}")
        return JSONResponse(
            status_code=200,
            content={
                "message": f"No bets found for room {room_id}",
                "data": {"bets": [], "users": {}, "count": 0, "room_id": room_id},
            },
        )

    except Exception as e:
        logger.error(f"Unexpected error getting bets for room {room_id}: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "message": "Failed to retrieve bets for room",
            },
        )
