from exceptions.bet_exceptions import OddsSnapshotMismatch
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
            # Extract 'teamChoice' from the dictionary
            team_choice = v.get("teamChoice")
            if team_choice not in ["home", "away"]:
                raise ValueError("Input should be 'home' or 'away'")
            return team_choice
        elif v not in ["home", "away", None]:
            raise ValueError("Input should be 'home' or 'away'")
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

    Validates sport-specific rules (point values, weekly limits) based on the room's sport.
    NFL rooms: 3 bets per week, one each at 1, 2, 3 points.
    MLB rooms: up to 5 bets per week, max 4 at 1pt, max 1 at 6pt.
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

    # Fail fast with a clear 400 if the odds_snapshot is missing the line the
    # bet type needs. Without this, a null-odds snapshot slips through to
    # validate_odds_snapshot / grading and can surface as an opaque 500.
    odds_snapshot = bet_request.odds_snapshot or {}
    bet_type = bet_request.game_bet.bet_type
    if bet_type == "over_under":
        total = odds_snapshot.get("overUnder")
        if total is None and bet_request.game_bet.total_value is None:
            logger.warning(
                f"Over/under bet for game {bet_request.game_id} is missing a "
                "total line in odds_snapshot"
            )
            raise InvalidBetTypeException("over_under", "total_value")
    elif bet_type == "spread":
        spread = odds_snapshot.get("spread")
        if spread is None and bet_request.game_bet.spread_value is None:
            logger.warning(
                f"Spread bet for game {bet_request.game_id} is missing a spread "
                "line in odds_snapshot"
            )
            raise InvalidBetTypeException("spread", "spread_value")

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

    # Look up room to get sport for sport-specific validation
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

    # Validate point value against sport-specific rules
    bet_validator = BetValidator(
        sport_key=room_sport, request_id=request.state.request_id
    )
    bet_validator.validate_point_value(bet_request.game_bet.points_wagered)

    # Get week boundaries for this event to check weekly limits
    week_helper = WeekHelper(request_id=request.state.request_id)
    week_boundary = week_helper.get_week_boundary(
        bet_request.sport,
        bet_request.league,
        bet_request.event_datetime,
        bet_request.game_id,
    )

    if week_boundary:
        week_start, week_end = week_boundary
        # Query existing bets for this user in this room within the week
        bet_helper = BetHelper(request_id=request.state.request_id)
        existing_bets = bet_helper.get_user_bets_for_room(
            room_id=bet_request.room_id, user_id=user_id
        )
        # Filter to bets within the current week boundary
        week_bets = [
            b
            for b in existing_bets
            if week_start <= b.get("event_datetime", 0) <= week_end
        ]
        bet_validator.validate_weekly_limits(
            week_bets, bet_request.game_bet.points_wagered
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

    # Validate spread is set for spread bets (0.0 means not yet available)
    if bet_request.game_bet.bet_type == "spread":
        odds_spread = bet_request.odds_snapshot.get("spread")
        if odds_spread is not None and float(odds_spread) == 0.0:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Spread not set",
                    "message": "The spread for this game has not been set yet. Try a total bet or wait for the spread to be published.",
                },
            )

    # Validate odds using BetHelper
    bet_helper = BetHelper(request_id=request.state.request_id)
    if not bet_helper.validate_odds_snapshot(
        bet_request.odds_snapshot, event_data, bet_request.game_bet.bet_type
    ):
        raise OddsSnapshotMismatch(
            "Home/Away team odds do not match between request and event data."
        )

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
