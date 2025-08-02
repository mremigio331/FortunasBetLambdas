from aws_lambda_powertools import Logger
import boto3
from botocore.exceptions import ClientError
from common.models.membership import MembershipModel, MembershipType, MembershipStatus
from datetime import datetime
from common.helpers.audit_actions_helper import AuditActions, AuditActionHelper
from exceptions.room_exceptions import (
    RoomNotFoundException,
    UnauthorizedRoomAccessException,
    MembershipAlreadyExistsException,
    MembershipNotFoundException,
    InvalidMembershipStatusException,
)
import os
from typing import List, Optional


class MembershipHelper:
    """
    A class to interact with DynamoDB for Membership operations in the FortunasBet application.
    """

    def __init__(self, request_id: str = None):
        self.dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        table_name = os.getenv("TABLE_NAME")
        self.table = self.dynamodb.Table(table_name)
        self.logger = Logger()
        if request_id:
            self.logger.append_keys(request_id=request_id)
        self.room_sk = "ROOM"
        self.membership_sk_prefix = "MEMBERSHIP#"
        self.membership_audit_sk = "MEMBERSHIP_AUDIT"
        self.audit_action_helper = AuditActionHelper(request_id=request_id)

    def create_membership(
        self,
        room_id: str,
        requestor_id: str,
        room_name: str,
        membership_type: MembershipType,
        status: MembershipStatus = MembershipStatus.PENDING,
        admin_id: Optional[str] = None,
        invited_user_id: Optional[str] = None,
        join_date: Optional[int] = None,
    ) -> dict:
        """
        Create a new membership record.
        Used for both owner memberships (when creating room) and user requests/invitations.
        """
        current_time = int(datetime.utcnow().timestamp())

        # Create membership model
        membership = MembershipModel(
            admin_id=admin_id,
            requestor=requestor_id,
            invited_user=invited_user_id,
            room_name=room_name,
            membership_type=membership_type,
            status=status,
            join_date=join_date,
            created_at=current_time,
        )

        # Create membership item - use by_alias and exclude_unset to get clean dict
        membership_item = membership.dict(by_alias=True, exclude_unset=True)
        membership_item["PK"] = f"ROOM#{room_id}"
        # Handle both enum and string values for comparison
        is_invitation = (
            membership_type == MembershipType.INVITATION
            or (
                hasattr(membership_type, "value")
                and membership_type.value == MembershipType.INVITATION.value
            )
            or membership_type == MembershipType.INVITATION.value
        )
        target_user = invited_user_id if is_invitation else requestor_id
        membership_item["SK"] = f"{self.membership_sk_prefix}{target_user}"

        # Convert enum values to strings for DynamoDB (handle both enum and string inputs)
        membership_item["membership_type"] = (
            membership_type.value
            if hasattr(membership_type, "value")
            else membership_type
        )
        membership_item["status"] = status.value if hasattr(status, "value") else status

        try:
            self.table.put_item(Item=membership_item)

            self.logger.info(
                f"Created {membership_type.value if hasattr(membership_type, 'value') else membership_type} membership for user {target_user} in room {room_id}"
            )

            # Create audit record
            # Create a clean membership dict for audit without enum objects
            audit_membership = membership.dict(by_alias=True, exclude_unset=True)
            audit_membership["membership_type"] = (
                membership_type.value
                if hasattr(membership_type, "value")
                else membership_type
            )
            audit_membership["status"] = (
                status.value if hasattr(status, "value") else status
            )

            self.audit_action_helper.create_audit_record(
                pk=f"ROOM#{room_id}",
                entity_type="Membership",
                action=AuditActions.CREATE.value,
                user_id=requestor_id,
                sk=self.membership_audit_sk,
                before=None,
                after=audit_membership,  # Use dict instead of model
            )

            result = membership.dict()
            # Ensure enums are converted to strings in the result
            result["membership_type"] = (
                membership_type.value
                if hasattr(membership_type, "value")
                else membership_type
            )
            result["status"] = status.value if hasattr(status, "value") else status
            result["room_id"] = room_id
            return result

        except ClientError as e:
            self.logger.error(f"Error creating membership: {e}")
            raise

    def get_membership(self, room_id: str, user_id: str) -> dict | None:
        """
        Get a specific membership record.
        """
        try:
            response = self.table.get_item(
                Key={
                    "PK": f"ROOM#{room_id}",
                    "SK": f"{self.membership_sk_prefix}{user_id}",
                }
            )
            return response.get("Item")
        except ClientError as e:
            self.logger.error(f"Error getting membership: {e}")
            raise

    def get_user_memberships_by_status(
        self,
        user_id: str,
        status: MembershipStatus,
        membership_type: MembershipType = None,
    ) -> List[dict]:
        """
        Get all memberships for a user filtered by status and optionally by membership type.
        """
        try:
            # Build filter expression based on parameters
            filter_expr = "begins_with(SK, :sk_prefix) AND ((:user_id = admin_id OR :user_id = requestor OR :user_id = invited_user) AND #status = :status)"
            expr_attr_values = {
                ":sk_prefix": self.membership_sk_prefix,
                ":user_id": user_id,
                ":status": status.value,
            }
            expr_attr_names = {
                "#status": "status",  # 'status' might be a reserved word
            }

            # Add membership type filter if specified
            if membership_type:
                filter_expr += " AND membership_type = :membership_type"
                expr_attr_values[":membership_type"] = membership_type.value

            response = self.table.scan(
                FilterExpression=filter_expr,
                ExpressionAttributeValues=expr_attr_values,
                ExpressionAttributeNames=expr_attr_names,
            )

            memberships = response.get("Items", [])
            status_desc = f"{status.value}" + (
                f" {membership_type.value}" if membership_type else ""
            )
            self.logger.info(
                f"Found {len(memberships)} {status_desc} memberships for user {user_id}"
            )
            return memberships

        except ClientError as e:
            self.logger.error(f"Error fetching memberships for user {user_id}: {e}")
            raise

    def get_room_memberships_by_status_and_type(
        self, room_id: str, status: MembershipStatus, membership_type: MembershipType
    ) -> List[dict]:
        """
        Get memberships for a room by status and type.
        """
        try:
            response = self.table.scan(
                FilterExpression="PK = :pk AND begins_with(SK, :sk_prefix) AND #status = :status AND membership_type = :type",
                ExpressionAttributeValues={
                    ":pk": f"ROOM#{room_id}",
                    ":sk_prefix": self.membership_sk_prefix,
                    ":status": status.value,
                    ":type": membership_type.value,
                },
                ExpressionAttributeNames={"#status": "status"},
            )

            return response.get("Items", [])

        except ClientError as e:
            self.logger.error(f"Error getting room memberships: {e}")
            raise

    def invite_user_to_room(
        self, room_id: str, room_name: str, admin_id: str, invited_user_id: str
    ) -> dict:
        """
        Admin invites a user to join a room.
        Creates a pending invitation that the user can accept or decline.
        """
        try:
            # Check if membership already exists
            existing_membership = self.get_membership(room_id, invited_user_id)
            if existing_membership:
                raise MembershipAlreadyExistsException(
                    user_id=invited_user_id, room_id=room_id
                )

            # Create invitation
            return self.create_membership(
                room_id=room_id,
                requestor_id=admin_id,  # Admin is the requestor for invitations
                room_name=room_name,
                membership_type=MembershipType.INVITATION,
                status=MembershipStatus.PENDING,
                admin_id=admin_id,
                invited_user_id=invited_user_id,
            )

        except ClientError as e:
            self.logger.error(f"Error creating invitation: {e}")
            raise

    def request_to_join_room(self, room_id: str, room_name: str, user_id: str) -> dict:
        """
        User requests to join a room.
        Creates a pending request that room admins can approve or deny.
        """
        try:
            # Check if membership already exists
            existing_membership = self.get_membership(room_id, user_id)
            if existing_membership:
                raise MembershipAlreadyExistsException(user_id=user_id, room_id=room_id)

            # Create request - no admin_id set since it's a user request
            return self.create_membership(
                room_id=room_id,
                requestor_id=user_id,
                room_name=room_name,
                membership_type=MembershipType.REQUEST,
                status=MembershipStatus.PENDING,
                admin_id=None,  # No specific admin assigned
            )

        except ClientError as e:
            self.logger.error(f"Error creating room request: {e}")
            raise

    def respond_to_membership(
        self, room_id: str, target_user_id: str, responding_user_id: str, approve: bool
    ) -> dict:
        """
        Respond to a membership request or invitation.
        - For requests: Any room admin can approve/deny user's request
        - For invitations: User accepts/declines admin's invitation
        Note: Room admin validation should be done by the calling code (RoomHelper)
        """
        try:
            # Get the membership
            membership = self.get_membership(room_id, target_user_id)
            if not membership:
                raise MembershipNotFoundException(
                    user_id=target_user_id, room_id=room_id
                )

            # Validate current status
            if membership["status"] != MembershipStatus.PENDING.value:
                raise InvalidMembershipStatusException(
                    current_status=membership["status"],
                    requested_status="approved" if approve else "denied",
                )

            # Validate permissions
            membership_type = membership.get("membership_type")
            if membership_type == MembershipType.REQUEST.value:
                # For requests: Admin validation should be done by calling code
                # We can't validate admin status here without room details
                pass
            elif membership_type == MembershipType.INVITATION.value:
                # Only invited user can respond to invitations
                invited_user = membership.get("invited_user")
                if invited_user != responding_user_id:
                    raise UnauthorizedRoomAccessException(
                        user_id=responding_user_id,
                        room_id=room_id,
                        action="respond to invitations for",
                    )

            # Update membership
            new_status = (
                MembershipStatus.APPROVED if approve else MembershipStatus.DENIED
            )
            current_time = int(datetime.utcnow().timestamp())

            update_expr = "SET #status = :status"
            expr_attr_names = {"#status": "status"}
            expr_attr_values = {":status": new_status.value}

            if approve:
                update_expr += ", join_date = :join_date"
                expr_attr_values[":join_date"] = current_time

            response = self.table.update_item(
                Key={
                    "PK": f"ROOM#{room_id}",
                    "SK": f"{self.membership_sk_prefix}{target_user_id}",
                },
                UpdateExpression=update_expr,
                ExpressionAttributeNames=expr_attr_names,
                ExpressionAttributeValues=expr_attr_values,
                ReturnValues="ALL_NEW",
            )

            self.logger.info(
                f"User {responding_user_id} {'approved' if approve else 'denied'} "
                f"membership for user {target_user_id} in room {room_id}"
            )

            # Create audit record
            # Convert models to clean dicts without enum objects for audit
            before_dict = dict(membership)
            if "membership_type" in before_dict and hasattr(
                before_dict["membership_type"], "value"
            ):
                before_dict["membership_type"] = before_dict["membership_type"].value
            if "status" in before_dict and hasattr(before_dict["status"], "value"):
                before_dict["status"] = before_dict["status"].value

            after_dict = dict(response["Attributes"])
            # response["Attributes"] should already have string values from DynamoDB

            self.audit_action_helper.create_audit_record(
                pk=f"ROOM#{room_id}",
                entity_type="Membership",
                action=AuditActions.UPDATE.value,
                user_id=responding_user_id,
                sk=self.membership_audit_sk,
                before=before_dict,
                after=after_dict,
            )

            result = response["Attributes"]
            result["room_id"] = room_id
            return result

        except ClientError as e:
            self.logger.error(f"Error responding to membership: {e}")
            raise

    def get_pending_invitations(self, user_id: str) -> List[dict]:
        """
        Get all pending invitations for a user.
        """
        return self.get_user_memberships_by_status(
            user_id, MembershipStatus.PENDING, MembershipType.INVITATION
        )

    def get_pending_requests_for_room(self, room_id: str) -> List[dict]:
        """
        Get all pending requests for a room.
        Note: Admin authorization should be validated by the calling code (RoomHelper)
        """
        try:
            return self.get_room_memberships_by_status_and_type(
                room_id, MembershipStatus.PENDING, MembershipType.REQUEST
            )

        except ClientError as e:
            self.logger.error(f"Error getting pending requests: {e}")
            raise

    def delete_all_room_memberships(self, room_id: str) -> int:
        """
        Delete all memberships for a room.
        Returns the number of memberships deleted.
        """
        try:
            # Get all memberships for this room
            memberships_to_delete = []
            last_evaluated_key = None

            while True:
                scan_kwargs = {
                    "FilterExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
                    "ExpressionAttributeValues": {
                        ":pk": f"ROOM#{room_id}",
                        ":sk_prefix": self.membership_sk_prefix,
                    },
                }

                if last_evaluated_key:
                    scan_kwargs["ExclusiveStartKey"] = last_evaluated_key

                response = self.table.scan(**scan_kwargs)
                memberships = response.get("Items", [])

                for membership in memberships:
                    memberships_to_delete.append(
                        {"PK": membership["PK"], "SK": membership["SK"]}
                    )

                last_evaluated_key = response.get("LastEvaluatedKey")
                if not last_evaluated_key:
                    break

            # Delete all memberships
            for membership_key in memberships_to_delete:
                self.table.delete_item(Key=membership_key)

            self.logger.info(
                f"Deleted {len(memberships_to_delete)} memberships for room {room_id}"
            )

            return len(memberships_to_delete)

        except ClientError as e:
            self.logger.error(f"Error deleting memberships for room {room_id}: {e}")
            raise
