from fastapi import APIRouter, Request, Path, Query, Depends
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from typing import List, Dict, Any, Optional
from datetime import datetime
from decimal import Decimal

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.bet_helper import BetHelper
from common.helpers.room_helper import RoomHelper
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


def _process_bets(request, room_bets, room_id, week_label):
    """
    Shared logic for processing room bets: user profile lookup, game-start
    visibility filtering, grading, and response building.
    """
    user_id = request.state.user_id

    if not room_bets:
        logger.info(f"No bets found for room {room_id} in {week_label}")
        return JSONResponse(
            status_code=200,
            content={
                "message": f"No bets found for room {room_id} in {week_label}",
                "data": {"bets": [], "users": {}, "count": 0, "room_id": room_id},
            },
        )

    espn_client = ESPNClient(request_id=request.state.request_id)
    user_helper = UserProfileHelper(request_id=request.state.request_id)

    unique_user_ids = list(
        set(bet.get("user_id") for bet in room_bets if bet.get("user_id"))
    )

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
            bet = BetModel(**bet_item)

            if bet.user_id == user_id:
                processed_bets.append(bet.dict())
                continue

            event_data = espn_client.get_event(bet.sport, bet.league, bet.game_id)

            if not event_data:
                logger.warning(f"Could not retrieve event data for game {bet.game_id}")
                bet.game_bet = None
                bet.total_points_earned = None
                bet.odds_snapshot = {}
                processed_bets.append(bet.dict())
                continue

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
                processed_bets.append(bet.dict())
            else:
                bet.game_bet = None
                bet.total_points_earned = None
                bet.game_id = None
                bet.odds_snapshot = {}
                processed_bets.append(bet.dict())

        except Exception as e:
            logger.warning(f"Error processing bet item: {e}")
            continue

    logger.info(f"Successfully retrieved {len(processed_bets)} bets for room {room_id}")

    serializable_bets = convert_decimals_to_floats(processed_bets)

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


@router.get(
    "/room/{room_id}/bets/season_type/{season_type}/week/{week}",
    response_model=List[Dict[str, Any]],
)
@jwt_required()
@exceptions_decorator
def get_bets_for_room_by_week(
    request: Request,
    room_id: str = Path(..., description="The room ID to get bets for"),
    season_type: int = Path(..., description="The season type to get bets for"),
    week: int = Path(..., description="The week number to get bets for"),
):
    """
    Get all bets for a specific room filtered by NFL-style season_type and week number.
    Used for NFL rooms where ESPN provides week/season_type metadata.
    """
    logger.append_keys(request_id=request.state.request_id)
    user_id = request.state.user_id
    logger.info(
        f"Getting bets for room {room_id}, week {week}, season_type {season_type}"
    )

    try:
        bet_helper = BetHelper(request_id=request.state.request_id)
        room_bets = bet_helper.get_all_bets_for_room_by_week(room_id, week, season_type)
        return _process_bets(request, room_bets, room_id, f"week {week}")

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


@router.get(
    "/room/{room_id}/bets/week_start/{week_start}/week_end/{week_end}",
    response_model=List[Dict[str, Any]],
)
@jwt_required()
@exceptions_decorator
def get_bets_for_room_by_date_range(
    request: Request,
    room_id: str = Path(..., description="The room ID to get bets for"),
    week_start: int = Path(..., description="Week start epoch timestamp (inclusive)"),
    week_end: int = Path(..., description="Week end epoch timestamp (inclusive)"),
):
    """
    Get all bets for a specific room filtered by date range (epoch boundaries).
    Used for MLB rooms where weeks are Monday 00:00:00 EST to Sunday 23:59:59 EST.
    """
    logger.append_keys(request_id=request.state.request_id)
    user_id = request.state.user_id
    logger.info(f"Getting bets for room {room_id}, date range {week_start}-{week_end}")

    try:
        bet_helper = BetHelper(request_id=request.state.request_id)
        room_bets = bet_helper.get_all_bets_for_room_by_date_range(
            room_id, week_start, week_end
        )
        return _process_bets(
            request, room_bets, room_id, f"range {week_start}-{week_end}"
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
