from functools import wraps
from fastapi import Request
from aws_lambda_powertools import Logger
from common.helpers.jwt import decode_jwt
from exceptions.jwt_exeptions import MissingJWTException, InvalidJWTException
from exceptions.user_exceptions import InvalidUserIdException
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)


def jwt_required(optional: bool = False):
    """
    Decorator to ensure JWT authentication is present and extract user_id.

    Args:
        optional (bool): If True, allows endpoints to work without JWT (for public endpoints)
                        If False, requires valid JWT token

    Usage:
        @jwt_required()  # Required JWT
        def protected_endpoint(request: Request):
            user_id = request.state.user_id  # Guaranteed to exist

        @jwt_required(optional=True)  # Optional JWT
        def public_endpoint(request: Request):
            user_id = getattr(request.state, 'user_id', None)  # May be None
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            try:
                # Try to get the Authorization header
                auth_header = request.headers.get("authorization")

                if not auth_header:
                    if optional:
                        # For optional endpoints, set user_id to None and continue
                        request.state.user_id = None
                        request.state.user_token = None
                        logger.info("No JWT token provided for optional endpoint")
                        return await func(request, *args, **kwargs)
                    else:
                        logger.warning("Missing Authorization header")
                        raise MissingJWTException("Authorization header is required")

                # Extract token from "Bearer <token>"
                if not auth_header.startswith("Bearer "):
                    if optional:
                        request.state.user_id = None
                        request.state.user_token = None
                        logger.info(
                            "Invalid Authorization header format for optional endpoint"
                        )
                        return await func(request, *args, **kwargs)
                    else:
                        logger.warning("Invalid Authorization header format")
                        raise InvalidJWTException(
                            "Authorization header must start with 'Bearer '"
                        )

                token = auth_header.split(" ", 1)[1]

                # Decode the JWT token
                claims = decode_jwt(token)

                # Extract user_id from token claims
                # Common claim names: 'sub', 'user_id', 'username', 'cognito:username'
                user_id = (
                    claims.get("sub")
                    or claims.get("user_id")
                    or claims.get("username")
                    or claims.get("cognito:username")
                )

                if not user_id:
                    if optional:
                        request.state.user_id = None
                        request.state.user_token = None
                        logger.info(
                            "No user_id found in JWT claims for optional endpoint"
                        )
                        return await func(request, *args, **kwargs)
                    else:
                        logger.warning(f"No user_id found in JWT claims: {claims}")
                        raise InvalidUserIdException("User ID not found in JWT token")

                # Store user information in request state
                request.state.user_id = user_id
                request.state.user_token = user_id  # For backward compatibility
                request.state.jwt_claims = claims

                logger.info(f"Authenticated user: {user_id}")
                return await func(request, *args, **kwargs)

            except (MissingJWTException, InvalidJWTException, InvalidUserIdException):
                # Re-raise these specific exceptions
                raise
            except Exception as e:
                if optional:
                    request.state.user_id = None
                    request.state.user_token = None
                    logger.warning(f"JWT processing error for optional endpoint: {e}")
                    return await func(request, *args, **kwargs)
                else:
                    logger.error(f"Unexpected error processing JWT: {e}")
                    raise InvalidJWTException(f"Error processing JWT: {e}")

        return wrapper

    return decorator


def jwt_optional():
    """
    Convenience decorator for optional JWT authentication.
    Equivalent to @jwt_required(optional=True)
    """
    return jwt_required(optional=True)
