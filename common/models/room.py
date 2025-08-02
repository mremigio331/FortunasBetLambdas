from pydantic import BaseModel, EmailStr, validator
from datetime import datetime
from typing import Optional
from boto3.dynamodb.types import TypeDeserializer
from exceptions.room_exceptions import (
    InvalidLeagueException,
    EmptyLeagueListException,
    InvalidDateRangeException,
    EmptyAdminsListException,
)

allowed_leagues = ["MLB", "NFL"]


class RoomModel(BaseModel):
    # pk ROOM#{room_uuid}
    # sk ROOM
    room_name: str
    leagues: list[str]
    created_at: int  # Epoch timestamp
    owner_id: str
    public: bool = False
    description: Optional[str] = None
    admins: list[str] = (
        []
    )  # List of admin user IDs, defaults to empty but will be populated with owner
    start_date: int  # Epoch timestamp - when room/season starts
    end_date: int  # Epoch timestamp - when room/season ends

    @validator("leagues")
    def validate_leagues(cls, v):
        if not v:
            raise EmptyLeagueListException()

        for league in v:
            if league not in allowed_leagues:
                raise InvalidLeagueException(
                    league=league, allowed_leagues=allowed_leagues
                )

        return v

    @validator("admins")
    def validate_admins(cls, v, values):
        owner_id = values.get("owner_id")

        # If admins list is empty, add the owner
        if not v and owner_id:
            v = [owner_id]

        # Ensure the list is never empty
        if not v:
            raise EmptyAdminsListException()

        # Ensure owner is always in the admins list
        if owner_id and owner_id not in v:
            v.append(owner_id)

        # Remove duplicates while preserving order
        seen = set()
        v = [admin for admin in v if not (admin in seen or seen.add(admin))]

        return v

    @validator("end_date")
    def validate_end_date(cls, v, values):
        start_date = values.get("start_date")
        if start_date is not None and v <= start_date:
            raise InvalidDateRangeException(start_date=start_date, end_date=v)
        return v
