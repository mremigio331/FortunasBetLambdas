from pydantic import BaseModel, EmailStr, validator
from datetime import datetime
from typing import Optional
from boto3.dynamodb.types import TypeDeserializer


class BetModel(BaseModel):
    # pk ROOM#{room_uuid}#WEEK#{week_number}
    # sk USER#{user_uuid}

    bet: dict
    locked: bool
    submitted_at: datetime
    ods: dict
