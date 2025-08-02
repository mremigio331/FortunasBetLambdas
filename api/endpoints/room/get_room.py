from fastapi import APIRouter, Request, Path
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from pydantic import BaseModel, Field
from typing import Optional, List

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.jwt import decode_jwt, update_cognito_user_attributes
from exceptions.user_exceptions import InvalidUserIdException
from exceptions.room_exceptions import RoomNotFoundException
import os
from common.helpers.room_helper import RoomHelper
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/{room_id}", response_model=dict)
@jwt_required()
@exceptions_decorator
def get_room(
    request: Request,
    room_id: str = Path(..., description="The ID of the room to retrieve"),
):
    """
    Get a single room by ID.
    Returns room details if the room exists.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info(f"Getting room {room_id}")

    # User ID is now automatically extracted and validated by the JWT decorator
    user_id = request.state.user_id
    logger.info(f"user_id from JWT: {user_id}")

    try:
        room_helper = RoomHelper(request_id=request.state.request_id)

        # Get the room
        room = room_helper.get_room(room_id)

        if not room:
            raise RoomNotFoundException(room_id=room_id)

        # Convert to JSON-serializable format
        room_dict = jsonable_encoder(room)
        logger.info(f"Successfully retrieved room {room_id}")

        return JSONResponse(
            status_code=200,
            content={"message": "Room retrieved successfully", "room": room_dict},
        )

    except Exception as e:
        logger.error(f"Error retrieving room {room_id}: {e}")
        raise
