from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from pydantic import BaseModel
from typing import Optional

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.membership_helper import MembershipHelper
from common.helpers.room_helper import RoomHelper
from common.constants.services import API_SERVICE
from common.helpers.notification_helper import NotificationType, NotificationHelper
from common.helpers.user_profile_helper import UserProfileHelper

logger = Logger(service=API_SERVICE)
router = APIRouter()


class CreateMembershipRequestModel(BaseModel):
    room_id: str


@router.post("/create_membership_request", response_model=dict)
@jwt_required()
@exceptions_decorator
def create_membership_request(
    request: Request, membership_request: CreateMembershipRequestModel
):
    """
    Create a membership request for a room.
    User requests to join a specific room.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info(f"Creating membership request for room {membership_request.room_id}")

    user_id = request.state.user_id
    logger.info(f"user_id from JWT: {user_id}")

    try:
        room_helper = RoomHelper(request_id=request.state.request_id)

        # Create the membership request using room helper (it handles business logic)
        membership = room_helper.request_to_join_room(
            room_id=membership_request.room_id,
            user_id=user_id,
        )

        # Convert to JSON-serializable format
        membership_dict = jsonable_encoder(membership)
        logger.info(
            f"Successfully created membership request for user {user_id} in room {membership_request.room_id}"
        )

    except Exception as e:
        logger.error(
            f"Error creating membership request for user {user_id} in room {membership_request.room_id}: {e}"
        )
        raise e

    room = room_helper.get_room(room_id=membership_request.room_id)
    logger.info(f"Room details: {room}")
    room_admins = room.get("admins", [])
    user_profile_helper = UserProfileHelper(request_id=request.state.request_id)
    user_profile = user_profile_helper.get_user_profile(user_id=user_id)

    try:
        for admin in room_admins:
            notification_helper = NotificationHelper(
                request_id=request.state.request_id
            )
            notification_helper.create_notification(
                user_id=admin,
                message=f"User {user_profile['name']} has requested to join your room: {room['room_name']}",
                notification_type=NotificationType.MEMBERSHIP_REQUEST,
            )
    except Exception as e:
        logger.error(f"Error creating notification for room admins: {e}")

    return JSONResponse(
        status_code=201,
        content={
            "message": "Membership request created successfully",
            "membership_request": membership_dict,
        },
    )
