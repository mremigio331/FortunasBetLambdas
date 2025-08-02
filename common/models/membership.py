from pydantic import BaseModel, EmailStr, validator
from datetime import datetime
from typing import Optional
from boto3.dynamodb.types import TypeDeserializer
from enum import Enum


class MembershipType(Enum):
    REQUEST = "request"  # User requested to join
    INVITATION = "invitation"  # Owner invited user


class MembershipStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class MembershipModel(BaseModel):
    # pk ROOM#{room_uuid}
    # sk MEMBERSHIP#{user_uuid}
    admin_id: Optional[str] = None  # Admin who can approve/deny or who sent invitation
    requestor: (
        str  # For requests: the user requesting. For invitations: the admin inviting
    )
    invited_user: Optional[str] = None  # For invitations: the user being invited
    room_name: str
    membership_type: MembershipType
    status: MembershipStatus
    join_date: Optional[int] = None  # Epoch timestamp, set when approved
    created_at: int  # Epoch timestamp, when request/invitation was created

    @validator("invited_user")
    def validate_invitation_fields(cls, v, values):
        membership_type = values.get("membership_type")
        if membership_type == MembershipType.INVITATION and not v:
            raise ValueError("invited_user is required for invitations")
        if membership_type == MembershipType.REQUEST and v:
            raise ValueError("invited_user should not be set for requests")
        return v
