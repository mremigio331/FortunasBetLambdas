class InvalidLeagueException(Exception):
    """Exception raised when an invalid league is provided."""

    def __init__(self, league: str = None, allowed_leagues: list = None):
        if league and allowed_leagues:
            message = f'League "{league}" is not allowed. Allowed leagues are: {", ".join(allowed_leagues)}'
        elif league:
            message = f'League "{league}" is not allowed.'
        else:
            message = "Invalid league provided."

        self.league = league
        self.allowed_leagues = allowed_leagues
        self.message = message
        super().__init__(self.message)


class EmptyLeagueListException(Exception):
    """Exception raised when no leagues are provided."""

    def __init__(self, message="At least one league must be specified"):
        self.message = message
        super().__init__(self.message)


class RoomNotFoundException(Exception):
    """Exception raised when a room is not found."""

    def __init__(self, room_id: str = None):
        if room_id:
            message = f"Room with ID '{room_id}' not found."
        else:
            message = "Room not found."

        self.room_id = room_id
        self.message = message
        super().__init__(self.message)


class UnauthorizedRoomAccessException(Exception):
    """Exception raised when a user tries to access or modify a room they don't have permission for."""

    def __init__(self, user_id: str = None, room_id: str = None, action: str = None):
        if user_id and room_id and action:
            message = (
                f"User '{user_id}' is not authorized to {action} room '{room_id}'."
            )
        elif action:
            message = f"User is not authorized to {action} this room."
        else:
            message = "Unauthorized room access."

        self.user_id = user_id
        self.room_id = room_id
        self.action = action
        self.message = message
        super().__init__(self.message)


class MembershipAlreadyExistsException(Exception):
    """Exception raised when trying to create a membership that already exists."""

    def __init__(self, user_id: str = None, room_id: str = None):
        if user_id and room_id:
            message = (
                f"Membership already exists for user '{user_id}' in room '{room_id}'."
            )
        else:
            message = "Membership already exists."

        self.user_id = user_id
        self.room_id = room_id
        self.message = message
        super().__init__(self.message)


class MembershipNotFoundException(Exception):
    """Exception raised when a membership is not found."""

    def __init__(self, user_id: str = None, room_id: str = None):
        if user_id and room_id:
            message = f"Membership not found for user '{user_id}' in room '{room_id}'."
        else:
            message = "Membership not found."

        self.user_id = user_id
        self.room_id = room_id
        self.message = message
        super().__init__(self.message)


class InvalidMembershipStatusException(Exception):
    """Exception raised when trying to perform an invalid membership status transition."""

    def __init__(self, current_status: str = None, requested_status: str = None):
        if current_status and requested_status:
            message = f"Cannot change membership status from '{current_status}' to '{requested_status}'."
        else:
            message = "Invalid membership status transition."

        self.current_status = current_status
        self.requested_status = requested_status
        self.message = message
        super().__init__(self.message)
