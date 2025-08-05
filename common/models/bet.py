from pydantic import BaseModel, EmailStr, validator
from datetime import datetime
from typing import Optional, Literal, Dict, Any
from boto3.dynamodb.types import TypeDeserializer


class GameBet(BaseModel):
    """Individual game bet within a weekly bet submission."""

    game_id: str
    bet_type: Literal["spread", "over_under"]

    # For spread bets
    team_choice: Optional[Literal["home", "away"]] = (
        None  # Which team to cover the spread
    )
    spread_value: Optional[float] = None  # The spread at time of bet

    # For over/under bets
    over_under_choice: Optional[Literal["over", "under"]] = (
        None  # Over or under the total
    )
    total_value: Optional[float] = None  # The total at time of bet

    # Points wagered (1, 2, or 3 points)
    points_wagered: int

    # Bet result (calculated after game completion)
    result: Optional[Literal["win", "loss", "push"]] = None
    points_earned: Optional[int] = None

    @validator("points_wagered")
    def validate_points_wagered(cls, v):
        if v not in [1, 2, 3]:
            raise ValueError("Points wagered must be 1, 2, or 3")
        return v

    @validator("team_choice")
    def validate_spread_bet(cls, v, values):
        if values.get("bet_type") == "spread" and v is None:
            raise ValueError("team_choice is required for spread bets")
        return v

    @validator("over_under_choice")
    def validate_over_under_bet(cls, v, values):
        if values.get("bet_type") == "over_under" and v is None:
            raise ValueError("over_under_choice is required for over/under bets")
        return v


class BetModel(BaseModel):
    """Single point-value bet submission for a user in a room."""

    # pk: ROOM#{room_id}
    # sk: POINT#{points_wagered}#USER#{user_id}#EVENT#{event_datetime}

    # Week/Room info
    room_id: str
    season_type: int  # 1=preseason, 2=regular, 3=postseason
    event_datetime: (
        int  # Epoch timestamp of the event/game week (used in SK for uniqueness)
    )
    game_id: str  # Identifier for the specific game/week
    sport: str  # Sport (e.g., 'football', 'basketball')
    league: str  # League (e.g., 'nfl', 'nba')

    # User info
    user_id: str

    # Bet details - now a single game bet instead of multiple
    game_bet: GameBet  # Single game bet
    points_wagered: int  # 1, 2, or 3 points (now redundant with game_bet.points_wagered but kept for clarity)
    total_points_earned: Optional[int] = None

    # Submission info
    locked: bool
    submitted_at: int  # Epoch timestamp
    updated_at: Optional[int] = None  # Last update timestamp

    # Original odds data at time of bet (for reference)
    odds_snapshot: Dict[str, Any]  # Single game odds data

    @validator("points_wagered")
    def validate_points_consistency(cls, v, values):
        game_bet = values.get("game_bet")
        if game_bet and v != game_bet.points_wagered:
            raise ValueError("points_wagered must match game_bet.points_wagered")
        return v

    @validator("game_bet")
    def validate_game_bet_required(cls, v):
        if not v:
            raise ValueError("game_bet is required")
        return v
