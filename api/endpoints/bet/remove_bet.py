from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from pydantic import BaseModel
from datetime import datetime

from api.decorators.exceptions_decorator import exceptions_decorator
from common.helpers.bet_helper import BetHelper
from common.helpers.membership_helper import MembershipHelper
from common.models.bet import BetModel
from clients.espn_client import ESPNClient
from exceptions.bet_exceptions import (
    GameLockedException,
    BetNotFoundException,
    GameDataNotFoundException,
)
from common.constants.services import API_SERVICE


logger = Logger(service=API_SERVICE)
router = APIRouter()


class RemoveBetResponse(BaseModel):
    """Response model for a removed bet."""

    message: str
    room_id: str
    user_id: str
    game_id: str
    removed_at: int


@router.delete("/remove", response_model=RemoveBetResponse)
@exceptions_decorator
def remove_bet(
    request: Request,
    room_id: str = Query(..., description="The room ID"),
    game_id: str = Query(..., description="The game ID of the bet to remove"),
    sport: str = Query(..., description="Sport (e.g., 'football', 'baseball')"),
    league: str = Query(..., description="League (e.g., 'nfl', 'mlb')"),
):
    """
    Remove (soft-delete) an existing bet for a user in a room.

    Verifies the game hasn't started, finds the existing bet, deletes the original
    DynamoDB item, and writes a new item with SK = REMOVED#<original_sk> and a
    removed_at timestamp to preserve the audit trail.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info(f"Remove bet request: room_id={room_id}, game_id={game_id}")

    # Get user ID from request state
    user_id = getattr(request.state, "user_token", None)
    if not user_id:
        logger.warning("User ID not found in request state.")
        return JSONResponse(
            status_code=401, content={"error": "User authentication required"}
        )

    # Check if user is a member of the room
    membership_helper = MembershipHelper(request_id=request.state.request_id)
    room_membership = membership_helper.get_membership(room_id=room_id, user_id=user_id)
    if room_membership is None:
        logger.warning(f"User {user_id} is not a member of room {room_id}")
        return JSONResponse(
            status_code=403,
            content={"error": "User is not a member of the room"},
        )

    if room_membership.get("status") != "approved":
        logger.warning(f"User {user_id} has inactive membership in room {room_id}")
        return JSONResponse(
            status_code=403,
            content={"error": "User membership is not approved"},
        )

    # Verify game hasn't started via ESPN API
    espn_client = ESPNClient(request_id=request.state.request_id)
    event_data = espn_client.get_event(sport, league, game_id)

    if not event_data:
        logger.warning(f"Could not retrieve event data for game {game_id}")
        raise GameDataNotFoundException(game_id, sport, league)

    current_status = event_data.get("status", {}).get("name", "").upper()
    logger.info(f"Game {game_id} current status: {current_status}")

    allowed_statuses = ["STATUS_SCHEDULED", "SCHEDULED", "PRE"]
    if current_status not in allowed_statuses:
        raise GameLockedException(game_id)

    # Find existing bet by room_id + user_id + game_id
    bet_helper = BetHelper(request_id=request.state.request_id)
    existing_bet = bet_helper.find_user_bet_by_game_id(
        room_id=room_id, user_id=user_id, game_id=game_id
    )

    if not existing_bet:
        raise BetNotFoundException(room_id, user_id, game_id)

    # Delete original DynamoDB item
    old_sk = existing_bet.get("SK")
    old_pk = existing_bet.get("PK", BetModel.create_pk(room_id))
    logger.info(f"Deleting original bet item: PK={old_pk}, SK={old_sk}")
    bet_helper.table.delete_item(Key={"PK": old_pk, "SK": old_sk})

    # Write new item with REMOVED# prefix on SK
    removed_at = int(datetime.utcnow().timestamp())
    removed_item = dict(existing_bet)
    removed_item["SK"] = f"REMOVED#{old_sk}"
    removed_item["removed_at"] = removed_at
    removed_item = bet_helper._convert_floats_to_decimals(removed_item)

    bet_helper.table.put_item(Item=removed_item)
    logger.info(
        f"Successfully removed bet for user {user_id} on game {game_id} "
        f"in room {room_id}. New SK: {removed_item['SK']}"
    )

    response = RemoveBetResponse(
        message="Bet successfully removed",
        room_id=room_id,
        user_id=user_id,
        game_id=game_id,
        removed_at=removed_at,
    )

    return JSONResponse(status_code=200, content=jsonable_encoder(response.dict()))
