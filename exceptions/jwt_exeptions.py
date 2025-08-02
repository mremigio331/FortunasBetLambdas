class JWTException(Exception):
    """Base exception for JWT errors."""

    pass


class InvalidJWTException(JWTException):
    """Raised when the JWT is invalid or cannot be decoded."""

    pass


class ExpiredJWTException(JWTException):
    """Raised when the JWT is expired."""

    pass


class MissingJWTException(JWTException):
    """Raised when the JWT is missing from the request."""

    pass


class JWTSignatureException(JWTException):
    """Raised when the JWT signature is invalid."""

    pass
