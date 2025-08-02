from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from typing import List

from api.decorators.exceptions_decorator import exceptions_decorator
from common.helpers.jwt import decode_jwt, update_cognito_user_attributes
from exceptions.user_exceptions import InvalidUserIdException
import os
from common.helpers.room_helper import RoomHelper
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/", response_model=dict)
@exceptions_decorator
def get_all_rooms(request: Request):
    """
    Get all rooms with basic information (room_id, room_name, description).
    Returns a list of room summaries.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info("Getting all rooms")

    # Get user_id from the JWT token (optional for this endpoint)
    user_id = getattr(request.state, "user_token", None)
    logger.info(f"user_id from request.state.user_token: {user_id}")

    try:
        room_helper = RoomHelper(request_id=request.state.request_id)

        # Get all rooms
        rooms = room_helper.get_all_rooms()

        # Convert to JSON-serializable format
        rooms_dict = jsonable_encoder(rooms)
        logger.info(f"Successfully retrieved {len(rooms)} rooms")

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
