from fastapi import APIRouter, Request, Path
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


class EditRoomRequest(BaseModel):
    room_id: str = Field(..., description="The ID of the room to edit")
    room_name: Optional[str] = Field(None, description="The name of the room")
    leagues: Optional[List[str]] = Field(
        None, description="List of leagues for this room"
    )
    admins: Optional[List[str]] = Field(
        None, description="List of admin user IDs for this room"
    )
    start_date: Optional[int] = Field(
        None, description="Start date of the room/season as epoch timestamp"
    )
    end_date: Optional[int] = Field(
        None, description="End date of the room/season as epoch timestamp"
    )


@router.put("/edit_room", response_model=dict)
@exceptions_decorator
def edit_room(request: Request, room_data: EditRoomRequest):
    """
    Edit an existing room. Only room admins can edit rooms.
    Only the specified fields (room_name, leagues, admins, start_date, end_date) can be updated.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info(
        f"Editing room {room_data.room_id} with data: {room_data.dict() if room_data else {}}"
    )

    # Get user_id from the JWT token
    user_id = getattr(request.state, "user_token", None)
    logger.info(f"user_id from request.state.user_token: {user_id}")

    if not user_id:
        logger.warning("User ID not found in request state.")
        raise InvalidUserIdException("User ID not found in request.")

    # If no data provided, return an error
    if not room_data:
        return JSONResponse(
            status_code=400,
            content={"message": "No data provided for room update"},
        )

    # Check if at least one field is provided for update
    update_fields = room_data.dict(exclude_unset=True)
    if not update_fields:
        return JSONResponse(
            status_code=400,
            content={"message": "No fields provided for room update"},
        )

    try:
        room_helper = RoomHelper(request_id=request.state.request_id)

        # Update the room
        updated_room = room_helper.update_room(
            room_id=room_data.room_id,
            user_id=user_id,
            room_name=room_data.room_name,
            leagues=room_data.leagues,
            admins=room_data.admins,
            start_date=room_data.start_date,
            end_date=room_data.end_date,
        )

        # Convert to JSON-serializable format
        room_dict = jsonable_encoder(updated_room)
        logger.info(
            f"Successfully updated room {room_data.room_id} by user_id {user_id}: {room_dict}"
        )

        return JSONResponse(
            status_code=200,
            content={"message": "Room updated successfully", "room": room_dict},
        )

    except Exception as e:
        logger.error(
            f"Error updating room {room_data.room_id} for user_id {user_id}: {e}"
        )
        raise
