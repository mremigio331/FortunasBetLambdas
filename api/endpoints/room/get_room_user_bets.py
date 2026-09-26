from fastapi import APIRouter, Request, Path
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from decimal import Decimal

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.bet_helper import BetHelper
from common.helpers.room_membership_validator import validate_room_membership
from common.helpers.bet_privacy import redact_hidden_bet
from common.constants.services import API_SERVICE
from datetime import datetime, timezone

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


@router.get("/{room_id}/bets/user/{target_user_id}")
@jwt_required()
@exceptions_decorator
def get_room_user_bets(
    request: Request,
    room_id: str = Path(..., description="The room ID"),
    target_user_id: str = Path(..., description="The user whose bets to load"),
):
    """
    One user's bets for a room, for the standings/history display.

    Loaded lazily per member row so a slow lookup for one user never blocks the
    others. Uses the display read path (grade-if-needed once, no live ESPN
    enhancement). Privacy: another user's bets on games that have NOT started
    are redacted, matching /room/{id}/bets/all.
    """
    logger.append_keys(request_id=request.state.request_id)
    user_id = request.state.user_id
    request_id = request.state.request_id

    validate_room_membership(room_id, user_id, request_id)

    bet_helper = BetHelper(request_id=request_id)
    bets = bet_helper.get_user_bets_for_room_for_display(
        room_id=room_id, user_id=target_user_id
    )

    # Privacy: if viewing someone else's bets, redact any whose game has not
    # started yet. Own bets are always fully visible. We gate on the stored
    # event_datetime (kickoff epoch) instead of a per-bet ESPN call, so this
    # stays cheap; a game is "started" once its kickoff time has passed.
    if target_user_id != user_id:
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        processed = []
        for bet in bets:
            event_dt = bet.get("event_datetime")
            started = event_dt is not None and now_epoch >= int(event_dt)
            processed.append(bet if started else redact_hidden_bet(bet))
        bets = processed

    serializable_bets = convert_decimals_to_floats(bets)

    logger.info(
        f"Retrieved {len(serializable_bets)} bets for user {target_user_id} "
        f"in room {room_id}"
    )
    return JSONResponse(
        status_code=200,
        content={
            "message": "User bets retrieved successfully",
            "room_id": room_id,
            "user_id": target_user_id,
            "bets": serializable_bets,
            "count": len(serializable_bets),
        },
    )
