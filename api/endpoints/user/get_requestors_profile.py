from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger
from exceptions.user_exceptions import (
    InvalidUserIdException,
    UserNotFound,
    ProfileNotPublicOrDoesNotExist,
)
from api.decorators.exceptions_decorator import exceptions_decorator
from common.helpers.jwt import decode_jwt
from common.helpers.user_profile_helper import UserProfileHelper
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get(
    "/profile", summary="Get a user profile", response_description="The user's profile"
)
@exceptions_decorator
def get_requestors_profile(request: Request):
    """
    Get User Profile Endpoint
    Returns:
        A JSON response containing the user's profile information.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info("Getting request for user profile.")

    token_user_id = getattr(request.state, "user_token", None)

    if not token_user_id:
        logger.warning("Token User ID could not be extracted from JWT.")
        raise InvalidUserIdException("Token User ID is required.")

    # Use the helper directly
    user_helper = UserProfileHelper(request_id=request.state.request_id)
    user_profile_data = user_helper.get_user_profile(user_id=token_user_id)
    if not user_profile_data:
        logger.warning(f"User profile not found for user_id: {token_user_id}")
        raise UserNotFound(f"User with ID {token_user_id} not found.")

    # Interact with the returned dict
    public_profile = user_profile_data.get("public_profile")
    db_user_id = user_profile_data.get("user_id")

    logger.info(f"Public profile flag: {public_profile}")

    # If the user_id from the table matches the token user_id, return the profile
    if db_user_id == token_user_id:
        logger.info("Access granted: user is profile owner.")
        return JSONResponse(
            content={"user_profile": user_profile_data}, status_code=200
        )

    # Otherwise, access denied
    logger.info("Access denied: profile is not public and requester is not owner.")
    raise ProfileNotPublicOrDoesNotExist(
        "Access denied: profile is not public or does not exist."
    )
