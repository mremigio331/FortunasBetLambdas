from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from pydantic import BaseModel, Field, validator
from typing import Optional, Literal
from datetime import datetime

from api.decorators.exceptions_decorator import exceptions_decorator
from common.helpers.bet_helper import BetHelper
from common.helpers.membership_helper import MembershipHelper
from common.helpers.room_helper import RoomHelper
from common.helpers.week_helper import WeekHelper
from common.models.bet import BetModel, GameBet
from common.validators.bet_validator import BetValidator
from clients.espn_client import ESPNClient
from exceptions.bet_exceptions import (
    OddsSnapshotMismatch,
    InvalidGameStatusException,
    InvalidPointsWageredException,
    InvalidBetTypeException,
    GameDataNotFoundException,
    GameLockedException,
    BetNotFoundException,
)
from common.constants.services import API_SERVICE


logger = Logger(service=API_SERVICE)
router = APIRouter()


class UpdateGameBetRequest(BaseModel):
    """Request model for the game bet portion of an update."""

    game_id: str = Field(..., description="The ESPN game ID")
    bet_type: Literal["spread", "over_under"] = Field(..., description="Type of bet")

    # For spread bets
    team_choice: Optional[Literal["home", "away"]] = Field(
        None, description="Team choice for spread bets"
    )
    spread_value: Optional[float] = Field(
        None, description="The spread value at time of bet"
    )

    # For Total bets
    over_under_choice: Optional[Literal["over", "under"]] = Field(
        None, description="Over or under choice"
    )
    total_value: Optional[float] = Field(
        None, description="The total value at time of bet"
    )

    # Points wagered
    points_wagered: int = Field(..., description="Points to wager on this game")

    @validator("points_wagered")
    def validate_points_wagered(cls, v):
        if v not in [1, 2, 3, 6]:
            raise InvalidPointsWageredException(v)
        return v

    @validator("team_choice")
    def validate_spread_bet(cls, v, values):
        if values.get("bet_type") == "spread" and v is None:
            raise InvalidBetTypeException("spread", "team_choice")
        return v

    @validator("over_under_choice")
    def validate_over_under_bet(cls, v, values):
        if values.get("bet_type") == "over_under" and v is None:
            raise InvalidBetTypeException("over_under", "over_under_choice")
        return v

    @validator("team_choice", pre=True)
    def validate_team_choice(cls, v):
        if isinstance(v, dict):
            team_choice = v.get("teamChoice")
            if team_choice not in ["home", "away"]:
                raise ValueError("Input should be 'home' or 'away'")
            return team_choice
        elif v not in ["home", "away", None]:
            raise ValueError("Input should be 'home' or 'away'")
        return v


class UpdateBetRequest(BaseModel):
    """Request model for updating an existing bet."""

    room_id: str = Field(..., description="The room ID where the bet is placed")
    game_id: str = Field(..., description="The game ID of the existing bet to update")
    season_type: int = Field(
        ..., description="Season type (1=preseason, 2=regular, 3=postseason)"
    )
    week: int = Field(..., description="Week number within the season")
    event_datetime: int = Field(
        ..., description="Epoch timestamp of the event/game week"
    )
    sport: str = Field(..., description="Sport (e.g., 'football', 'baseball')")
    league: str = Field(..., description="League (e.g., 'nfl', 'mlb')")
    game_bet: UpdateGameBetRequest = Field(
        ..., description="The updated game bet details"
    )
    odds_snapshot: dict = Field(
        ..., description="Snapshot of odds data at time of update"
    )


class UpdateBetResponse(BaseModel):
    """Response model for an updated bet."""

    message: str
    bet_id: str
    room_id: str
    user_id: str
    points_wagered: int
    game_id: str
    updated_at: int


@router.put("/update", response_model=UpdateBetResponse)
@exceptions_decorator
def update_bet(request: Request, bet_request: UpdateBetRequest):
    """
    Update an existing bet for a user in a room.

    Verifies the game hasn't started, finds the existing bet by room_id + user_id + game_id,
    deletes the old DynamoDB item, and creates a new item with updated points/odds/timestamp.
    Validates the updated bet against sport-specific rules via BetValidator.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info(f"Update bet request: {bet_request.dict()}")

    # Get user ID from request state
    user_id = getattr(request.state, "user_token", None)
    if not user_id:
        logger.warning("User ID not found in request state.")
        return JSONResponse(
            status_code=401, content={"error": "User authentication required"}
        )

    # Check if user is a member of the room
    membership_helper = MembershipHelper(request_id=request.state.request_id)
    room_membership = membership_helper.get_membership(
        room_id=bet_request.room_id, user_id=user_id
    )
    if room_membership is None:
        logger.warning(f"User {user_id} is not a member of room {bet_request.room_id}")
        return JSONResponse(
            status_code=403,
            content={"error": "User is not a member of the room"},
        )

    if room_membership.get("status") != "approved":
        logger.warning(
            f"User {user_id} has inactive membership in room {bet_request.room_id}"
        )
        return JSONResponse(
            status_code=403,
            content={"error": "User membership is not approved"},
        )

    # Look up room to get sport
    room_helper = RoomHelper(request_id=request.state.request_id)
    room = room_helper.get_room(bet_request.room_id)
    if not room:
        logger.warning(f"Room {bet_request.room_id} not found")
        return JSONResponse(
            status_code=404,
            content={"error": f"Room {bet_request.room_id} not found"},
        )

    room_sport = room.get("sport", "NFL")
    logger.info(f"Room {bet_request.room_id} sport: {room_sport}")

    # Verify game hasn't started via ESPN API
    espn_client = ESPNClient(request_id=request.state.request_id)
    event_data = espn_client.get_event(
        bet_request.sport, bet_request.league, bet_request.game_id
    )

    if not event_data:
        logger.warning(f"Could not retrieve event data for game {bet_request.game_id}")
        raise GameDataNotFoundException(
            bet_request.game_id, bet_request.sport, bet_request.league
        )

    current_status = event_data.get("status", {}).get("name", "").upper()
    logger.info(f"Game {bet_request.game_id} current status: {current_status}")

    allowed_statuses = ["STATUS_SCHEDULED", "SCHEDULED", "PRE"]
    if current_status not in allowed_statuses:
        logger.info(
            f"Bet {bet_id} unable to update due to status {current_status} not in allowed_statuses."
        )
        raise GameLockedException(bet_request.game_id)

    # Find existing bet by room_id + user_id + game_id
    bet_helper = BetHelper(request_id=request.state.request_id)
    existing_bet = bet_helper.find_user_bet_by_game_id(
        room_id=bet_request.room_id, user_id=user_id, game_id=bet_request.game_id
    )

    if not existing_bet:
        raise BetNotFoundException(bet_request.room_id, user_id, bet_request.game_id)

    # Validate new point value against sport-specific rules
    bet_validator = BetValidator(
        sport_key=room_sport, request_id=request.state.request_id
    )
    bet_validator.validate_point_value(bet_request.game_bet.points_wagered)

    # Validate weekly limits, excluding the existing bet being updated
    week_helper = WeekHelper(request_id=request.state.request_id)
    week_boundary = week_helper.get_week_boundary(
        bet_request.sport,
        bet_request.league,
        bet_request.event_datetime,
        bet_request.game_id,
    )

    if week_boundary:
        week_start, week_end = week_boundary
        all_user_bets = bet_helper.get_user_bets_for_room(
            room_id=bet_request.room_id, user_id=user_id
        )
        week_bets = [
            b
            for b in all_user_bets
            if week_start <= b.get("event_datetime", 0) <= week_end
            and not b.get("SK", "").startswith("REMOVED#")
            and b.get("game_id") != bet_request.game_id  # Exclude the bet being updated
        ]
        bet_validator.validate_weekly_limits(
            week_bets, bet_request.game_bet.points_wagered
        )

    # Validate odds snapshot
    if not bet_helper.validate_odds_snapshot(bet_request.odds_snapshot, event_data):
        raise OddsSnapshotMismatch(
            "Home/Away team odds do not match between request and event data."
        )

    # Delete old DynamoDB item
    old_sk = existing_bet.get("SK")
    old_pk = existing_bet.get("PK", BetModel.create_pk(bet_request.room_id))
    logger.info(f"Deleting old bet item: PK={old_pk}, SK={old_sk}")
    bet_helper.table.delete_item(Key={"PK": old_pk, "SK": old_sk})

    # Create new GameBet object
    game_bet = GameBet(
        game_id=bet_request.game_bet.game_id,
        bet_type=bet_request.game_bet.bet_type,
        team_choice=bet_request.game_bet.team_choice,
        spread_value=bet_request.game_bet.spread_value,
        over_under_choice=bet_request.game_bet.over_under_choice,
        total_value=bet_request.game_bet.total_value,
        points_wagered=bet_request.game_bet.points_wagered,
    )

    # Create new BetModel with updated data
    updated_at = int(datetime.utcnow().timestamp())
    new_bet = BetModel(
        room_id=bet_request.room_id,
        season_type=bet_request.season_type,
        week=bet_request.week,
        event_datetime=bet_request.event_datetime,
        game_id=bet_request.game_id,
        sport=bet_request.sport,
        league=bet_request.league,
        user_id=user_id,
        game_bet=game_bet,
        points_wagered=bet_request.game_bet.points_wagered,
        locked=False,
        submitted_at=updated_at,
        odds_snapshot=bet_request.odds_snapshot,
    )

    # Write new item to DynamoDB directly (bypass create_bet's duplicate checks)
    item = new_bet.dict()
    item["PK"] = BetModel.create_pk(new_bet.room_id)
    item["SK"] = BetModel.create_sk(
        new_bet.points_wagered, new_bet.user_id, new_bet.event_datetime
    )
    item = bet_helper._convert_floats_to_decimals(item)

    bet_helper.table.put_item(Item=item)
    logger.info(
        f"Successfully updated bet for user {user_id} on game {bet_request.game_id} "
        f"in room {bet_request.room_id} with {new_bet.points_wagered} points"
    )

    bet_id = f"{bet_request.room_id}#{new_bet.points_wagered}#{user_id}"

    response = UpdateBetResponse(
        message=f"Successfully updated bet to {new_bet.points_wagered}-point bet",
        bet_id=bet_id,
        room_id=bet_request.room_id,
        user_id=user_id,
        points_wagered=new_bet.points_wagered,
        game_id=bet_request.game_id,
        updated_at=updated_at,
    )

    return JSONResponse(status_code=200, content=jsonable_encoder(response.dict()))
