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


class UserNameTooLong(Exception):
    """Exception raised when a user's name exceeds the maximum length."""

    def __init__(self, max_length):
        self.message = f"User name must be at most {max_length} characters."
        super().__init__(self.message)
