from pydantic import BaseModel, validator
from typing import Optional
from enum import Enum


class NotificationType(Enum):
    BET_WINNER = "Bet Winner"
    BET_LOSER = "Bet Loser"
    BET_PUSH = "Bet Push"
    MEMBERSHIP_REQUEST = "Membership Request"
    MEMBERSHIP_APPROVED = "Membership Approved"
    MEMBERSHIP_INVITE = "Membership Invite"


class NotificationModel(BaseModel):

    # pk: USER#{user_id}
    # sk: NOTIFICATION#{notification_id}
    view: bool = False
    message: str
    notification_type: NotificationType
    timestamp: int  # Epoch timestamp
    room_id: Optional[str] = None  # Optional, if the notification is related to a room

    @validator("message")
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError("Notification message cannot be empty.")
        return v

    @validator("timestamp")
    def validate_timestamp(cls, v):
        if not isinstance(v, int) or v <= 0:
            raise ValueError("Timestamp must be a positive epoch integer.")
        return v

    @staticmethod
    def create_pk(user_id: str) -> str:
        return f"USER#{user_id}"

    @staticmethod
    def create_sk(notification_id: str) -> str:
        return f"NOTIFICATION#{notification_id}"
