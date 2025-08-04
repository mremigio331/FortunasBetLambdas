from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from typing import List, Dict, Any
from decimal import Decimal

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.membership_helper import MembershipHelper
from common.helpers.room_helper import RoomHelper
from common.helpers.user_profile_helper import UserProfileHelper
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


@router.get("/get_room_members/{room_id}", response_model=dict)
@jwt_required()
@exceptions_decorator
def get_room_members(request: Request, room_id: str):
    """
    Get all members and membership requests for a specific room.
    Only admins of the room can access this endpoint.
    Returns both pending requests and current members.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info(f"Getting all members for room {room_id}")

    user_id = request.state.user_id
    logger.info(f"user_id from JWT: {user_id}")

    try:
        room_helper = RoomHelper(request_id=request.state.request_id)
        membership_helper = MembershipHelper(request_id=request.state.request_id)
        user_profile_helper = UserProfileHelper(request_id=request.state.request_id)

        # Check if the user is admin of this room
        room = room_helper.get_room(room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")

        # Check both possible field names for backward compatibility
        admin_ids = room.get("admin_user_ids", []) or room.get("admins", [])
        if user_id not in admin_ids:
            raise HTTPException(
                status_code=403, detail="Only room admins can access member information"
            )

        # Get all membership records for the room (all statuses and types)
        all_memberships = []

        # Get all membership statuses
        for status in MembershipStatus:
            for membership_type in MembershipType:
                memberships = membership_helper.get_room_memberships_by_status_and_type(
                    room_id, status, membership_type
                )
                all_memberships.extend(memberships)

        # Process and organize the data
        processed_members = []
        user_ids_to_fetch = []

        for membership in all_memberships:
            # Convert all Decimal objects in the membership record
            membership_converted = convert_decimals_in_dict(membership)

            # Extract user_id from SK (format: MEMBERSHIP#USER_ID)
            sk = membership_converted.get("SK", "")
            if sk.startswith("MEMBERSHIP#"):
                member_user_id = sk.replace("MEMBERSHIP#", "")
                user_ids_to_fetch.append(member_user_id)

                processed_member = {
                    "user_id": member_user_id,
                    "status": membership_converted.get("status"),
                    "membership_type": membership_converted.get("membership_type"),
                    "join_date": membership_converted.get("join_date"),
                    "created_at": membership_converted.get("created_at"),
                    "admin_id": membership_converted.get("admin_id"),
                    "is_current_user": member_user_id == user_id,
                }
                processed_members.append(processed_member)

        # Fetch user profiles for all member user IDs
        user_profiles = user_profile_helper.get_multiple_user_profiles(
            user_ids_to_fetch
        )

        # Add user names and colors to processed members
        for member in processed_members:
            user_profile = user_profiles.get(member["user_id"], {})
            member["user_name"] = user_profile.get("name", member["user_id"])
            member["user_color"] = user_profile.get("color", "black")

        # Sort by status priority (admin first, then member, then pending, then denied)
        status_priority = {
            MembershipStatus.APPROVED.value: 1,
            MembershipStatus.PENDING.value: 2,
            MembershipStatus.DENIED.value: 3,
        }

        type_priority = {MembershipType.ADMIN.value: 1, MembershipType.MEMBER.value: 2}

        processed_members.sort(
            key=lambda x: (
                status_priority.get(x["status"], 99),
                type_priority.get(x["membership_type"], 99),
                x["user_id"],
            )
        )

        logger.info(
            f"Successfully retrieved {len(processed_members)} members for room {room_id}"
        )

        return JSONResponse(
            status_code=200,
            content={
                "message": "Room members retrieved successfully",
                "room_id": room_id,
                "members": processed_members,
                "count": len(processed_members),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving members for room {room_id}: {e}")
        raise
