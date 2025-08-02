from pydantic import BaseModel, EmailStr, validator
from typing import Optional
from boto3.dynamodb.types import TypeDeserializer


class UserProfileModel(BaseModel):
    # pk USER#{user_uuid}
    # sk USER_PROFILE
    user_id: str
    email: EmailStr
    name: str
    created_at: int  # Epoch timestamp
    public_profile: Optional[bool] = False
