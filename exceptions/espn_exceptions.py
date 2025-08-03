class ESPNException(Exception):
    """Base exception for ESPN API related errors."""

    def __init__(self, message="ESPN API error occurred."):
        self.message = message
        super().__init__(self.message)


class ESPNTimeoutException(ESPNException):
    """Exception raised when ESPN API request times out."""

    def __init__(self, message="ESPN API request timed out."):
        self.message = message
        super().__init__(self.message)


class ESPNRateLimitException(ESPNException):
    """Exception raised when ESPN API rate limit is exceeded."""

    def __init__(self, message="ESPN API rate limit exceeded."):
        self.message = message
        super().__init__(self.message)


class ESPNDataNotFoundException(ESPNException):
    """Exception raised when ESPN API returns no data for the requested resource."""

    def __init__(self, message="No data found for the requested ESPN resource."):
        self.message = message
        super().__init__(self.message)


class ESPNInvalidParametersException(ESPNException):
    """Exception raised when invalid parameters are provided to ESPN API."""

    def __init__(self, message="Invalid parameters provided for ESPN API request."):
        self.message = message
        super().__init__(self.message)
