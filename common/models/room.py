from pydantic import BaseModel, EmailStr, validator
from datetime import datetime
from typing import Optional
from boto3.dynamodb.types import TypeDeserializer


class RoomModel(BaseModel):
    # pk ROOM#{room_uuid}
    # sk ROOM
    room_name: str
    sport: str
    created_at: datetime
    owner_id: str
    public: bool
    description: Optional[str] = None
