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
from common.models.membership import MembershipStatus
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


class EditMembershipRequestModel(BaseModel):
    room_id: str
    target_user_id: str
    approve: bool


@router.put("/edit_membership_request", response_model=dict)
@jwt_required()
@exceptions_decorator
def edit_membership_request(request: Request, edit_request: EditMembershipRequestModel):
    """
    Edit a membership request status (approve/deny).
    Only admins of the room can approve or deny membership requests.
    The admin_id field will be updated with the ID of the admin who made the decision.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info(
        f"Editing membership request for user {edit_request.target_user_id} in room {edit_request.room_id}"
    )

    admin_user_id = request.state.user_id
    logger.info(f"admin_user_id from JWT: {admin_user_id}")

    try:
        room_helper = RoomHelper(request_id=request.state.request_id)

        # Respond to membership request using room helper (it validates admin permissions)
        updated_membership = room_helper.respond_to_membership(
            room_id=edit_request.room_id,
            target_user_id=edit_request.target_user_id,
            responding_user_id=admin_user_id,
            approve=edit_request.approve,
        )

        # Convert to JSON-serializable format
        membership_dict = jsonable_encoder(updated_membership)
        action = "approved" if edit_request.approve else "denied"
        logger.info(
            f"Admin {admin_user_id} {action} membership request for user {edit_request.target_user_id} in room {edit_request.room_id}"
        )

        return JSONResponse(
            status_code=200,
            content={
                "message": f"Membership request {action} successfully",
                "membership_request": membership_dict,
                "action": action,
                "admin_id": admin_user_id,
            },
        )

    except Exception as e:
        logger.error(
            f"Error editing membership request for user {edit_request.target_user_id} in room {edit_request.room_id}: {e}"
        )
        raise
