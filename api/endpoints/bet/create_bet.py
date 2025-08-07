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
from common.models.bet import BetModel, GameBet
from clients.espn_client import ESPNClient
from exceptions.bet_exceptions import (
    DuplicateBetException,
    BetNotFound,
    InvalidGameStatusException,
    BetLockedException,
    InvalidPointsWageredException,
    InvalidBetTypeException,
    GameDataNotFoundException,
)
from common.constants.services import API_SERVICE


logger = Logger(service=API_SERVICE)
router = APIRouter()


class CreateGameBetRequest(BaseModel):
    """Request model for creating a game bet."""

    game_id: str = Field(..., description="The ESPN game ID")
    bet_type: Literal["spread", "over_under"] = Field(..., description="Type of bet")

    # For spread bets
    team_choice: Optional[Literal["home", "away"]] = Field(
        None, description="Team choice for spread bets"
    )
    spread_value: Optional[float] = Field(
        None, description="The spread value at time of bet"
    )

    # For over/under bets
    over_under_choice: Optional[Literal["over", "under"]] = Field(
        None, description="Over or under choice"
    )
    total_value: Optional[float] = Field(
        None, description="The total value at time of bet"
    )

    # Points wagered
    points_wagered: int = Field(..., description="Points to wager (1, 2, or 3)")

    @validator("points_wagered")
    def validate_points_wagered(cls, v):
        if v not in [1, 2, 3]:
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


class CreateBetRequest(BaseModel):
    """Request model for creating a bet."""

    room_id: str = Field(..., description="The room ID where the bet is placed")
    season_type: int = Field(
        ..., description="Season type (1=preseason, 2=regular, 3=postseason)"
    )
    week: int = Field(..., description="Week number within the season (from ESPN API)")
    event_datetime: int = Field(
        ..., description="Epoch timestamp of the event/game week"
    )
    game_id: str = Field(..., description="Identifier for the specific game/week")
    sport: str = Field(..., description="Sport (e.g., 'football', 'basketball')")
    league: str = Field(..., description="League (e.g., 'nfl', 'nba')")
    game_bet: CreateGameBetRequest = Field(..., description="The game bet details")
    odds_snapshot: dict = Field(..., description="Snapshot of odds data at time of bet")


class CreateBetResponse(BaseModel):
    """Response model for created bet."""

    message: str
    bet_id: str
    room_id: str
    user_id: str
    points_wagered: int
    game_id: str
    created_at: int


@router.post("/create", response_model=CreateBetResponse)
@exceptions_decorator
def create_bet(request: Request, bet_request: CreateBetRequest):
    """
    Create a new bet for a user in a room.

    Each user can only make one bet per point value (1, 2, 3) in each room.
    Validates that the bet doesn't already exist and that the game allows betting.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info(f"Create bet request: {bet_request.dict()}")

    # Get user ID from request state (set by authentication middleware)
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
    if room_membership.get("status") != "active":
        logger.warning(
            f"User {user_id} has inactive membership in room {bet_request.room_id}"
        )
        return JSONResponse(
            status_code=403,
            content={"error": "User membership is not active"},
        )

    # Initialize ESPN client to validate game status
    espn_client = ESPNClient(request_id=request.state.request_id)

    # Get current game status from ESPN API using sport and league from request
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

    # Validate game status allows betting (game hasn't started)
    allowed_statuses = ["STATUS_SCHEDULED", "SCHEDULED", "PRE"]
    if current_status not in allowed_statuses:
        raise InvalidGameStatusException(current_status, "STATUS_SCHEDULED")

    # Create GameBet object
    game_bet = GameBet(
        game_id=bet_request.game_bet.game_id,
        bet_type=bet_request.game_bet.bet_type,
        team_choice=bet_request.game_bet.team_choice,
        spread_value=bet_request.game_bet.spread_value,
        over_under_choice=bet_request.game_bet.over_under_choice,
        total_value=bet_request.game_bet.total_value,
        points_wagered=bet_request.game_bet.points_wagered,
    )

    # Create BetModel
    bet = BetModel(
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
        locked=False,  # New bets start unlocked
        submitted_at=int(datetime.utcnow().timestamp()),
        odds_snapshot=bet_request.odds_snapshot,
    )

    # Create bet using helper
    bet_helper = BetHelper(request_id=request.state.request_id)
    created_bet = bet_helper.create_bet(bet)

    logger.info(
        f"Successfully created {bet.points_wagered}-point bet for user {user_id} in room {bet_request.room_id}"
    )

    # Generate bet ID for response
    bet_id = f"{bet_request.room_id}#{bet.points_wagered}#{user_id}"

    response = CreateBetResponse(
        message=f"Successfully created {bet.points_wagered}-point bet",
        bet_id=bet_id,
        room_id=bet_request.room_id,
        user_id=user_id,
        points_wagered=bet.points_wagered,
        game_id=bet_request.game_id,
        created_at=bet.submitted_at,
    )

    return JSONResponse(status_code=201, content=jsonable_encoder(response.dict()))
