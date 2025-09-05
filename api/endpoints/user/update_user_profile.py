from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from exceptions.user_exceptions import (
    InvalidUserIdException,
    UserNotFound,
    ProfileNotPublicOrDoesNotExist,
)
from pydantic import BaseModel, Field
from typing import Optional

from api.decorators.exceptions_decorator import exceptions_decorator
from common.helpers.jwt import decode_jwt, update_cognito_user_attributes
import os
from common.helpers.user_profile_helper import UserProfileHelper
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


class UpdateUserProfileRequest(BaseModel):
    email: Optional[str] = Field(None, description="The user's email address")
    name: Optional[str] = Field(None, description="The user's name")
    color: Optional[str] = Field(
        None,
        description="The user's avatar color (black, white, red, blue, green, yellow, orange, purple, pink, brown, gray, cyan)",
    )
    dark_mode: Optional[bool] = Field(None, description="User's dark mode preference")


@router.put("/profile", response_model=UpdateUserProfileRequest)
@exceptions_decorator
def update_user_profile(request: Request, user_profile: UpdateUserProfileRequest):
    """
    Update the user's profile information.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info(f"Request body: {user_profile.dict()}")
    user_id = getattr(request.state, "user_token", None)
    logger.info(f"user_id from request.state.user_token: {user_id}")
    if not user_id:
        logger.warning("User ID not found in request state.")
        raise InvalidUserIdException("User ID not found in request.")

    try:
        user_profile_helper = UserProfileHelper(request_id=request.state.request_id)
        updated_profile = user_profile_helper.update_user_profile_fields(
            user_id=user_id,
            name=user_profile.name,
            email=user_profile.email,
            color=user_profile.color,
            dark_mode=user_profile.dark_mode,
        )
        if updated_profile:
            try:
                profile_dict = updated_profile.dict()
            except AttributeError:
                profile_dict = dict(updated_profile.__dict__)
            profile_dict = jsonable_encoder(profile_dict)
            logger.info(f"DynamoDB update result for user_id {user_id}: {profile_dict}")
        else:
            logger.warning(f"User with ID {user_id} not found in DynamoDB.")
            raise UserNotFound(f"User with ID {user_id} not found.")

        # Update Cognito user attributes (name and email)
        user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
        logger.info(
            f"Updating Cognito user attributes for user_id {user_id} in user_pool_id {user_pool_id}"
        )
        update_cognito_user_attributes(
            user_pool_id=user_pool_id,
            user_id=user_id,
            name=user_profile.name,
            email=user_profile.email,
        )
        logger.info(
            f"Successfully updated Cognito user attributes for user_id {user_id}"
        )

        return JSONResponse(status_code=200, content=profile_dict)

    except UserNotFound as e:
        logger.error(f"User not found: {e}")
        raise ProfileNotPublicOrDoesNotExist("Profile does not exist or is not public.")
