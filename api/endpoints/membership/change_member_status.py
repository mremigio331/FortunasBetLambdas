from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from decimal import Decimal

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.membership_helper import MembershipHelper
from common.helpers.room_helper import RoomHelper
from common.models.membership import MembershipStatus, MembershipType
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


def convert_decimal(obj):
    """Convert Decimal objects to int or float for JSON serialization"""
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        else:
            return float(obj)
    return obj


def convert_decimals_in_dict(data):
    """Recursively convert Decimal objects in a dictionary"""
    if isinstance(data, dict):
        return {key: convert_decimals_in_dict(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [convert_decimals_in_dict(item) for item in data]
    elif isinstance(data, Decimal):
        return convert_decimal(data)
    return data


class ChangeMemberStatusModel(BaseModel):
    room_id: str
    target_user_id: str
    new_status: str  # "approved", "denied", "pending"
    new_membership_type: Optional[str] = (
        None  # "admin", "member" - optional for status changes
    )


@router.put("/change_member_status", response_model=dict)
@jwt_required()
@exceptions_decorator
def change_member_status(request: Request, change_request: ChangeMemberStatusModel):
    """
    Change the status or membership type of an existing member.
    Only admins of the room can change member status.
    Admins cannot change their own status.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info(
        f"Changing status for user {change_request.target_user_id} in room {change_request.room_id}"
    )

    admin_user_id = request.state.user_id
    logger.info(f"admin_user_id from JWT: {admin_user_id}")

    # Prevent admins from changing their own status
    if admin_user_id == change_request.target_user_id:
        raise HTTPException(
            status_code=400, detail="Admins cannot change their own membership status"
        )

    try:
        room_helper = RoomHelper(request_id=request.state.request_id)
        membership_helper = MembershipHelper(request_id=request.state.request_id)

        # Check if the user is admin of this room
        room = room_helper.get_room(change_request.room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")

        # Check both possible field names for backward compatibility
        admin_ids = room.get("admin_user_ids", []) or room.get("admins", [])
        if admin_user_id not in admin_ids:
            raise HTTPException(
                status_code=403, detail="Only room admins can change member status"
            )

        # Get the existing membership
        existing_membership = membership_helper.get_membership(
            change_request.room_id, change_request.target_user_id
        )

        if not existing_membership:
            raise HTTPException(status_code=404, detail="Membership not found")

        # Validate new status
        try:
            new_status = MembershipStatus(change_request.new_status.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid status value")

        # Validate new membership type if provided
        new_membership_type = None
        if change_request.new_membership_type:
            try:
                new_membership_type = MembershipType(
                    change_request.new_membership_type.upper()
                )
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid membership type")

        # If approving a request without specifying membership type, default to MEMBER
        if (
            new_status == MembershipStatus.APPROVED
            and existing_membership.get("membership_type") in ["request", "invitation"]
            and not new_membership_type
        ):
            new_membership_type = MembershipType.MEMBER

        # Update the membership
        current_time = int(datetime.utcnow().timestamp())

        update_expression = (
            "SET #status = :status, updated_at = :updated_at, admin_id = :admin_id"
        )
        expression_attribute_values = {
            ":status": new_status.value,
            ":updated_at": current_time,
            ":admin_id": admin_user_id,
        }
        expression_attribute_names = {"#status": "status"}

        # Add membership type to update if provided or if auto-setting to MEMBER
        if new_membership_type:
            update_expression += ", membership_type = :membership_type"
            expression_attribute_values[":membership_type"] = new_membership_type.value

        # If approving a pending request, set join_date
        if (
            existing_membership.get("status") == MembershipStatus.PENDING.value
            and new_status == MembershipStatus.APPROVED
        ):
            update_expression += ", join_date = :join_date"
            expression_attribute_values[":join_date"] = current_time

        # Update the membership record
        response = membership_helper.table.update_item(
            Key={
                "PK": f"ROOM#{change_request.room_id}",
                "SK": f"MEMBERSHIP#{change_request.target_user_id}",
            },
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_attribute_values,
            ExpressionAttributeNames=expression_attribute_names,
            ReturnValues="ALL_NEW",
        )

        updated_membership = response.get("Attributes", {})
        # Convert Decimal objects before JSON encoding
        updated_membership_converted = convert_decimals_in_dict(updated_membership)
        membership_dict = jsonable_encoder(updated_membership_converted)

        action = f"Changed status to {new_status.value}"
        if new_membership_type:
            action += f" and type to {new_membership_type.value}"

        logger.info(
            f"Admin {admin_user_id} changed membership for user {change_request.target_user_id} in room {change_request.room_id}: {action}"
        )

        return JSONResponse(
            status_code=200,
            content={
                "message": f"Member status updated successfully",
                "membership": membership_dict,
                "action": action,
                "admin_id": admin_user_id,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error changing member status for user {change_request.target_user_id} in room {change_request.room_id}: {e}"
        )
        raise
