from fastapi import APIRouter, Request, Path
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger
from typing import List, Dict, Any

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.bet_helper import BetHelper
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get(
    "/room/{room_id}/removed_bets",
    response_model=List[Dict[str, Any]],
)
@jwt_required()
@exceptions_decorator
def get_removed_bets(
    request: Request,
    room_id: str = Path(..., description="The room ID to get removed bets for"),
):
    """
    Get all removed bets for the current user in a specific room.
    Returns bets that were soft-deleted (SK prefixed with REMOVED#) with a
    'status' field set to 'removed'.
    """
    logger.append_keys(request_id=request.state.request_id)
    user_id = request.state.user_id
    logger.info(f"Getting removed bets for user {user_id} in room {room_id}")

    try:
        bet_helper = BetHelper(request_id=request.state.request_id)
        removed_bets = bet_helper.get_removed_bets_for_user(room_id, user_id)

        logger.info(
            f"Retrieved {len(removed_bets)} removed bets for user {user_id} in room {room_id}"
        )

        return JSONResponse(
            status_code=200,
            content={
                "message": f"Retrieved removed bets for room {room_id}",
                "data": {
                    "removed_bets": removed_bets,
                    "count": len(removed_bets),
                    "room_id": room_id,
                },
            },
        )

    except Exception as e:
        logger.error(
            f"Error getting removed bets for user {user_id} in room {room_id}: {str(e)}"
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "message": "Failed to retrieve removed bets",
            },
        )
