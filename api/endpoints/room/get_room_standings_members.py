from fastapi import APIRouter, Request, Path
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.user_profile_helper import UserProfileHelper
from common.helpers.room_membership_validator import (
    validate_room_membership,
    get_active_member_ids,
)
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/{room_id}/standings/members")
@jwt_required()
@exceptions_decorator
def get_room_standings_members(
    request: Request,
    room_id: str = Path(..., description="The room ID to get standings members for"),
):
    """
    Fast standings header: the room's active members with profiles, no bets.

    Lets the standings table render its user rows immediately; each row then
    loads that user's bets lazily via GET /room/{room_id}/bets/user/{user_id}.
    """
    logger.append_keys(request_id=request.state.request_id)
    user_id = request.state.user_id
    request_id = request.state.request_id

    validate_room_membership(room_id, user_id, request_id)

    active_member_ids = get_active_member_ids(room_id, request_id)

    user_profile_helper = UserProfileHelper(request_id=request_id)
    profiles = user_profile_helper.get_multiple_user_profiles(active_member_ids)

    members = [
        {
            "user_id": member_id,
            "user_name": profiles.get(member_id, {}).get("name", member_id),
            "user_color": profiles.get(member_id, {}).get("color", "black"),
            "is_current_user": member_id == user_id,
        }
        for member_id in active_member_ids
    ]

    logger.info(f"Retrieved {len(members)} standings members for room {room_id}")
    return JSONResponse(
        status_code=200,
        content={
            "message": "Standings members retrieved successfully",
            "room_id": room_id,
            "members": members,
            "count": len(members),
        },
    )
