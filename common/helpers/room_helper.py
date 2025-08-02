from aws_lambda_powertools import Logger
import boto3
from botocore.exceptions import ClientError
from common.models.room import RoomModel
from common.models.membership import MembershipType, MembershipStatus
from datetime import datetime
from common.helpers.audit_actions_helper import AuditActions, AuditActionHelper
from common.helpers.membership_helper import MembershipHelper
from exceptions.room_exceptions import (
    RoomNotFoundException,
    UnauthorizedRoomAccessException,
)
import os
import uuid
from typing import List, Optional


class RoomHelper:
    """
    A class to interact with DynamoDB for Room operations in the FortunasBet application.
    """

    def __init__(self, request_id: str = None):
        self.dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        table_name = os.getenv("TABLE_NAME")
        self.table = self.dynamodb.Table(table_name)
        self.logger = Logger()
        if request_id:
            self.logger.append_keys(request_id=request_id)
        self.room_sk = "ROOM"
        self.room_audit_sk = "ROOM_AUDIT"
        self.audit_action_helper = AuditActionHelper(request_id=request_id)
        self.membership_helper = MembershipHelper(request_id=request_id)

    def create_room(
        self,
        room_name: str,
        leagues: List[str],
        owner_id: str,
        public: bool = True,
        description: Optional[str] = None,
    ) -> dict:
        """
        Create a new room in DynamoDB and create a membership for the owner.
        Returns the created room data.
        """
        room_uuid = str(uuid.uuid4())
        current_time = int(datetime.utcnow().timestamp())

        # Create room model
        room = RoomModel(
            room_name=room_name,
            leagues=leagues,
            created_at=current_time,
            owner_id=owner_id,
            public=public,
            description=description,
        )

        # Create room item
        room_item = room.dict()
        room_item["PK"] = f"ROOM#{room_uuid}"
        room_item["SK"] = self.room_sk

        try:
            # Create room and membership
            self.table.put_item(Item=room_item)

            # Create membership for the owner using MembershipHelper
            self.membership_helper.create_membership(
                room_id=room_uuid,
                owner_id=owner_id,
                requestor_id=owner_id,
                room_name=room_name,
                membership_type=MembershipType.REQUEST.value,
                status=MembershipStatus.APPROVED.value,
                join_date=current_time,
            )

            self.logger.info(f"Created room {room_uuid} with owner {owner_id}")

            # Create audit record for room
            self.audit_action_helper.create_audit_record(
                pk=f"ROOM#{room_uuid}",
                entity_type="Room",
                action=AuditActions.CREATE.value,
                user_id=owner_id,
                sk=self.room_audit_sk,
                before=None,
                after=room,
            )

            # Return room data with room_id
            result = room.dict()
            result["room_id"] = room_uuid
            return result

        except ClientError as e:
            self.logger.error(f"Error creating room for owner {owner_id}: {e}")
            raise

    def get_room(self, room_id: str) -> dict | None:
        """
        Fetch a room from DynamoDB by room_id.
        Returns a dict with room details or None if not found.
        """
        try:
            response = self.table.get_item(
                Key={"PK": f"ROOM#{room_id}", "SK": self.room_sk}
            )

            if "Item" in response:
                item = response["Item"]
                result = {
                    "room_id": room_id,
                    "room_name": item.get("room_name"),
                    "leagues": item.get("leagues"),
                    "created_at": item.get("created_at"),
                    "owner_id": item.get("owner_id"),
                    "public": item.get("public", True),
                    "description": item.get("description"),
                }
                return result
            else:
                self.logger.info(f"No room found for room_id {room_id}")
                return None

        except ClientError as e:
            self.logger.error(f"Error fetching room {room_id}: {e}")
            raise

    def get_user_rooms(self, user_id: str) -> List[dict]:
        """
        Get all rooms that a user is an approved member of.
        Returns a list of room details.
        """
        return self._get_user_rooms_by_status(user_id, MembershipStatus.APPROVED)

    def get_user_pending_requests(self, user_id: str) -> List[dict]:
        """
        Get all rooms where the user has pending join requests.
        Returns a list of room details with request information.
        """
        return self._get_user_rooms_by_status(
            user_id, MembershipStatus.PENDING.value, MembershipType.REQUEST.value
        )

    def _get_user_rooms_by_status(
        self,
        user_id: str,
        status: MembershipStatus,
        membership_type: MembershipType = None,
    ) -> List[dict]:
        """
        Get rooms for a user filtered by membership status and optionally by membership type.
        Returns a list of room details with membership information.
        """
        try:
            # Get memberships from MembershipHelper
            memberships = self.membership_helper.get_user_memberships_by_status(
                user_id, status, membership_type
            )

            user_rooms = []
            # For each membership, get the room details and combine them
            for membership in memberships:
                pk_value = membership.get("PK", "")
                if pk_value.startswith("ROOM#"):
                    room_id = pk_value.replace("ROOM#", "")
                    room_details = self.get_room(room_id)
                    if room_details:
                        # Add membership info to room details
                        room_details["join_date"] = membership.get("join_date")
                        room_details["is_owner"] = membership.get("owner") == user_id
                        room_details["membership_status"] = membership.get("status")
                        room_details["membership_type"] = membership.get(
                            "membership_type"
                        )
                        room_details["created_at_membership"] = membership.get(
                            "created_at"
                        )
                        user_rooms.append(room_details)

            status_desc = f"{status.value}" + (
                f" {membership_type.value}" if membership_type else ""
            )
            self.logger.info(
                f"Found {len(user_rooms)} {status_desc} rooms for user {user_id}"
            )
            return user_rooms

        except ClientError as e:
            self.logger.error(f"Error fetching rooms for user {user_id}: {e}")
            raise

    def delete_room(self, room_id: str, user_id: str) -> bool:
        """
        Delete a room and all its memberships.
        Only the room owner can delete a room.
        Returns True if successful, False otherwise.
        """
        try:
            # First, verify the user is the owner
            room = self.get_room(room_id)
            if not room:
                self.logger.warning(f"Room {room_id} not found for deletion")
                return False

            if room["owner_id"] != user_id:
                self.logger.warning(
                    f"User {user_id} is not the owner of room {room_id}, cannot delete"
                )
                return False

            # Delete the room and all its memberships
            self.table.delete_item(Key={"PK": f"ROOM#{room_id}", "SK": self.room_sk})

            # Use MembershipHelper to delete all memberships
            deleted_count = self.membership_helper.delete_all_room_memberships(room_id)

            self.logger.info(f"Deleted room {room_id} and {deleted_count} memberships")

            # Create audit record for room deletion
            room_model = RoomModel(**room)
            self.audit_action_helper.create_audit_record(
                pk=f"ROOM#{room_id}",
                entity_type="Room",
                action=AuditActions.DELETE.value,
                user_id=user_id,
                sk=self.room_audit_sk,
                before=room_model,
                after=None,
            )

            return True

        except ClientError as e:
            self.logger.error(f"Error deleting room {room_id}: {e}")
            raise

    # Membership delegation methods - delegate to MembershipHelper
    def invite_user_to_room(
        self, room_id: str, owner_id: str, invited_user_id: str
    ) -> dict:
        """
        Owner invites a user to join a room.
        Delegates to MembershipHelper after validating room ownership.
        """
        try:
            # Verify the room exists and user is the owner
            room = self.get_room(room_id)
            if not room:
                raise RoomNotFoundException(room_id=room_id)

            if room["owner_id"] != owner_id:
                raise UnauthorizedRoomAccessException(
                    user_id=owner_id, room_id=room_id, action="invite users to"
                )

            return self.membership_helper.invite_user_to_room(
                room_id, room["room_name"], owner_id, invited_user_id
            )

        except ClientError as e:
            self.logger.error(f"Error creating invitation: {e}")
            raise

    def request_to_join_room(self, room_id: str, user_id: str) -> dict:
        """
        User requests to join a room.
        Delegates to MembershipHelper after validating room exists.
        """
        try:
            # Verify the room exists
            room = self.get_room(room_id)
            if not room:
                raise RoomNotFoundException(room_id=room_id)

            return self.membership_helper.request_to_join_room(
                room_id, room["room_name"], room["owner_id"], user_id
            )

        except ClientError as e:
            self.logger.error(f"Error creating room request: {e}")
            raise

    def respond_to_membership(
        self, room_id: str, target_user_id: str, responding_user_id: str, approve: bool
    ) -> dict:
        """
        Respond to a membership request or invitation.
        Delegates to MembershipHelper.
        """
        return self.membership_helper.respond_to_membership(
            room_id, target_user_id, responding_user_id, approve
        )

    def get_pending_invitations(self, user_id: str) -> List[dict]:
        """
        Get all pending invitations for a user.
        Delegates to MembershipHelper.
        """
        return self.membership_helper.get_pending_invitations(user_id)

    def get_pending_requests(self, room_id: str, owner_id: str) -> List[dict]:
        """
        Get all pending requests for a room (owner only).
        Validates ownership then delegates to MembershipHelper.
        """
        try:
            # Verify ownership
            room = self.get_room(room_id)
            if not room or room["owner_id"] != owner_id:
                raise UnauthorizedRoomAccessException(
                    user_id=owner_id, room_id=room_id, action="view requests for"
                )

            return self.membership_helper.get_pending_requests_for_room(
                room_id, owner_id
            )

        except ClientError as e:
            self.logger.error(f"Error getting pending requests: {e}")
            raise
