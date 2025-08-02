from pydantic import BaseModel, EmailStr, validator
from datetime import datetime
from typing import Optional
from boto3.dynamodb.types import TypeDeserializer
from exceptions.room_exceptions import InvalidLeagueException, EmptyLeagueListException

allowed_leagues = ["MLB", "NFL"]


class RoomModel(BaseModel):
    # pk ROOM#{room_uuid}
    # sk ROOM
    room_name: str
    leagues: list[str]
    created_at: int  # Epoch timestamp
    owner_id: str
    public: bool
    description: Optional[str] = None

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
