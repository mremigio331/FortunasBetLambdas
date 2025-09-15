# OddsSnapshotMismatch exception for invalid odds
class OddsSnapshotMismatch(Exception):
    """Raised when event_data odds_snapshot does not match the passed odds_snapshot."""

    pass


class BetException(Exception):
    """Base exception for bet-related errors."""

    pass


class DuplicateBetException(BetException):
    """Raised when attempting to create a bet that already exists."""

    def __init__(self, room_id: str, user_id: str, points_wagered: int):
        self.room_id = room_id
        self.user_id = user_id
        self.points_wagered = points_wagered
        super().__init__(
            f"User {user_id} already has a {points_wagered}-point bet in room {room_id}"
        )


class BetNotFound(BetException):
    """Raised when attempting to access a bet that doesn't exist."""

    def __init__(self, room_id: str, user_id: str, points_wagered: int):
        self.room_id = room_id
        self.user_id = user_id
        self.points_wagered = points_wagered
        super().__init__(
            f"No {points_wagered}-point bet found for user {user_id} in room {room_id}"
        )


class InvalidGameStatusException(BetException):
    """Raised when attempting to modify a bet with invalid game status."""

    def __init__(self, current_status: str, required_status: str = "STATUS_SCHEDULED"):
        self.current_status = current_status
        self.required_status = required_status
        super().__init__(
            f"Cannot update bet: game status is {current_status}, must be {required_status}"
        )


class InvalidPointsWageredException(BetException):
    """Raised when points wagered is not 1, 2, or 3."""

    def __init__(self, points_wagered: int):
        self.points_wagered = points_wagered
        super().__init__(
            f"Invalid points wagered: {points_wagered}. Must be 1, 2, or 3"
        )


class BetLockedException(BetException):
    """Raised when attempting to modify a locked bet."""

    def __init__(self, room_id: str, user_id: str, points_wagered: int):
        self.room_id = room_id
        self.user_id = user_id
        self.points_wagered = points_wagered
        super().__init__(
            f"Cannot modify locked {points_wagered}-point bet for user {user_id} in room {room_id}"
        )


class InvalidBetTypeException(BetException):
    """Raised when bet type is invalid or missing required fields."""

    def __init__(self, bet_type: str, missing_field: str = None):
        self.bet_type = bet_type
        self.missing_field = missing_field
        if missing_field:
            super().__init__(
                f"Invalid {bet_type} bet: missing required field '{missing_field}'"
            )
        else:
            super().__init__(f"Invalid bet type: {bet_type}")


class UserProfileNotFoundException(BetException):
    """Raised when a user profile cannot be found or retrieved."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"User profile not found for user {user_id}")


class GameDataNotFoundException(BetException):
    """Raised when game data cannot be retrieved from ESPN API."""

    def __init__(self, game_id: str, sport: str = None, league: str = None):
        self.game_id = game_id
        self.sport = sport
        self.league = league
        if sport and league:
            super().__init__(
                f"Unable to retrieve game data for {sport}/{league} game {game_id}"
            )
        else:
            super().__init__(f"Unable to retrieve game data for game {game_id}")


class DuplicateGameException(BetException):
    """Raised when attempting to place a bet on a game that already has a bet."""

    def __init__(self, game_id: str):
        self.game_id = game_id
        super().__init__(f"A bet already exists for game {game_id}")
