class InvalidUserIdException(Exception):
    """Exception raised when no user ID is found in the request."""

    def __init__(self, message="No user ID found in the request."):
        self.message = message
        super().__init__(self.message)


class UserNotFound(Exception):
    """Exception raised when a user is not found in the database."""

    def __init__(self, message="User not found."):
        self.message = message
        super().__init__(self.message)


class ProfileNotPublicOrDoesNotExist(Exception):
    """Raised when a user profile is not public or does not exist."""

    pass
