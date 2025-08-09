from pydantic import BaseModel, validator
from typing import Optional


class NotificationModel(BaseModel):

    # pk: USER#{user_id}
    # sk: NOTIFICATION#{notification_id}
    view: bool = False
    message: str
    timestamp: int  # Epoch timestamp

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
