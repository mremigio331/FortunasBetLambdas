from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from pydantic import BaseModel, Field
from typing import Optional, List

from api.decorators.exceptions_decorator import exceptions_decorator
from common.helpers.jwt import decode_jwt, update_cognito_user_attributes
from exceptions.user_exceptions import InvalidUserIdException
import os
from common.helpers.room_helper import RoomHelper
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


class CreateRoomRequest(BaseModel):
    room_name: str = Field(..., description="The name of the room")
    leagues: List[str] = Field(..., description="List of leagues for this room")
    start_date: int = Field(
        ..., description="Start date of the room/season as epoch timestamp"
    )
    end_date: int = Field(
        ..., description="End date of the room/season as epoch timestamp"
    )
    public: bool = Field(
        False, description="Whether the room is public or private (private by default)"
    )
    description: Optional[str] = Field(
        None, description="Optional description of the room"
    )


@router.post("/create_room", response_model=dict)
@exceptions_decorator
def create_room(request: Request, room_data: CreateRoomRequest):
    """
    Create a new room.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info(f"Request body: {room_data.dict()}")

    # Get user_id from the JWT token
    user_id = getattr(request.state, "user_token", None)
    logger.info(f"user_id from request.state.user_token: {user_id}")

    if not user_id:
        logger.warning("User ID not found in request state.")
        raise InvalidUserIdException("User ID not found in request.")

    try:
        room_helper = RoomHelper(request_id=request.state.request_id)

        # Create the room
        created_room = room_helper.create_room(
            room_name=room_data.room_name,
            leagues=room_data.leagues,
            owner_id=user_id,
            public=room_data.public,
            description=room_data.description,
            start_date=room_data.start_date,
            end_date=room_data.end_date,
        )

        # Convert to JSON-serializable format
        room_dict = jsonable_encoder(created_room)
        logger.info(f"Successfully created room for user_id {user_id}: {room_dict}")

        return JSONResponse(
            status_code=201,
            content={"message": "Room created successfully", "room": room_dict},
        )

    except Exception as e:
        logger.error(f"Error creating room for user_id {user_id}: {e}")
        raise
