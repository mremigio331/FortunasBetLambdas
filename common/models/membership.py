from pydantic import BaseModel, EmailStr, validator
from datetime import datetime
from typing import Optional
from boto3.dynamodb.types import TypeDeserializer


class MembershipModel(BaseModel):
    # pk ROOM#{room_uuid}
    # sk USER#{user_uuid}
    owner: str
    room_name: str
    status: bool
    join_date: datetime
