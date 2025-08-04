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
    color: str = "black"  # Default color for user profile avatar

    @validator("color")
    def validate_color(cls, v):
        """Validate that color is one of the allowed basic colors"""
        allowed_colors = [
            "black",
            "white",
            "red",
            "blue",
            "green",
            "yellow",
            "orange",
            "purple",
            "pink",
            "brown",
            "gray",
            "cyan",
        ]
        if v.lower() not in allowed_colors:
            raise ValueError(f'Color must be one of: {", ".join(allowed_colors)}')
        return v.lower()
