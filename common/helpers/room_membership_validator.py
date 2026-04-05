from aws_lambda_powertools import Logger

from common.helpers.room_helper import RoomHelper
from common.helpers.membership_helper import MembershipHelper
from common.models.membership import MembershipStatus, MembershipType
from common.constants.services import API_SERVICE
from exceptions.room_exceptions import (
    RoomNotFoundException,
    UnauthorizedRoomAccessException,
)

logger = Logger(service=API_SERVICE)


def validate_room_membership(room_id: str, user_id: str, request_id: str) -> dict:
    """
    Validates that a room exists and the user has an approved membership.
    Returns the room dict on success.
    Raises RoomNotFoundException (404) or UnauthorizedRoomAccessException (403).
    """
    room_helper = RoomHelper(request_id=request_id)
    room = room_helper.get_room(room_id)

    if not room:
        raise RoomNotFoundException(room_id=room_id)

    membership_helper = MembershipHelper(request_id=request_id)
    membership = membership_helper.get_membership(room_id, user_id)

    if not membership or membership.get("status") != MembershipStatus.APPROVED.value:
        raise UnauthorizedRoomAccessException(
            user_id=user_id, room_id=room_id, action="access"
        )

    return room


def get_active_member_ids(room_id: str, request_id: str) -> list:
    """
    Returns a deduplicated list of user_ids with approved membership in the room.
    Queries all membership types with APPROVED status, since membership_type
    is not changed on approval (it stays as 'request', 'invitation', etc.).
    """
    membership_helper = MembershipHelper(request_id=request_id)

    all_memberships = []
    for membership_type in MembershipType:
        memberships = membership_helper.get_room_memberships_by_status_and_type(
            room_id, MembershipStatus.APPROVED, membership_type
        )
        all_memberships.extend(memberships)

    user_ids = set()
    for membership in all_memberships:
        sk = membership.get("SK", "")
        # SK format: MEMBERSHIP#{user_id}
        if sk.startswith("MEMBERSHIP#"):
            user_id = sk.replace("MEMBERSHIP#", "", 1)
            user_ids.add(user_id)

    logger.info(f"Found {len(user_ids)} active members for room {room_id}")
    return list(user_ids)
