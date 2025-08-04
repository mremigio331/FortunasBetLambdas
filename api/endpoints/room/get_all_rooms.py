from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from typing import List

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.jwt import decode_jwt, update_cognito_user_attributes
from exceptions.user_exceptions import InvalidUserIdException
import os
from common.helpers.room_helper import RoomHelper
from common.helpers.membership_helper import MembershipHelper
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/get_all_rooms", response_model=dict)
@jwt_required()
@exceptions_decorator
def get_all_rooms(request: Request):
    """
    Get all rooms with basic information and user's membership status for each room.
    Returns a list of room summaries with membership_status field.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info("Getting all rooms with membership status")

    user_id = request.state.user_id
    logger.info(f"user_id from JWT: {user_id}")

    try:
        room_helper = RoomHelper(request_id=request.state.request_id)
        membership_helper = MembershipHelper(request_id=request.state.request_id)

        # Get all rooms
        rooms = room_helper.get_all_rooms()

        # Get all user's membership requests
        user_memberships = membership_helper.get_all_membership_requests_for_user(
            user_id
        )

        # Create a map of room_id to membership status
        membership_status_map = {}
        for membership in user_memberships:
            # Extract room_id from PK field (format: "ROOM#<room_id>")
            if membership.get("PK") and membership["PK"].startswith("ROOM#"):
                room_id = membership["PK"].replace("ROOM#", "")
                membership_status_map[room_id] = membership.get("status")

        # Add membership status to each room
        rooms_with_membership = []
        for room in rooms:
            room_dict = dict(room)
            room_id = str(room_dict.get("room_id"))

            # Determine membership status
            if room_dict.get("owner_id") == user_id:
                membership_status = "admin"
            elif room_dict.get("admins") and user_id in room_dict.get("admins", []):
                membership_status = "admin"
            elif room_id in membership_status_map:
                status = membership_status_map[room_id]
                if status == "approved":
                    membership_status = "member"
                elif status in ["pending", "denied"]:
                    membership_status = status
                else:
                    membership_status = "none"
            else:
                membership_status = "none"

            room_dict["membership_status"] = membership_status
            rooms_with_membership.append(room_dict)

        rooms_dict = jsonable_encoder(rooms_with_membership)
        logger.info(f"Successfully retrieved {len(rooms)} rooms with membership status")

        return JSONResponse(
            status_code=200,
            content={
                "message": f"Retrieved {len(rooms)} rooms successfully",
                "rooms": rooms_dict,
                "count": len(rooms),
            },
        )

    except Exception as e:
        logger.error(f"Error retrieving all rooms: {e}")
        raise
