from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from typing import List

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.membership_helper import MembershipHelper
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/get_membership_requests", response_model=dict)
@jwt_required()
@exceptions_decorator
def get_all_membership_requests(request: Request):
    """
    Get all membership requests for the authenticated user.
    Returns a list of membership requests where the user is the requestor.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info("Getting all membership requests for user")

    user_id = request.state.user_id
    logger.info(f"user_id from JWT: {user_id}")

    try:
        membership_helper = MembershipHelper(request_id=request.state.request_id)

        membership_requests = membership_helper.get_all_membership_requests_for_user(
            user_id
        )

        requests_dict = jsonable_encoder(membership_requests)
        logger.info(
            f"Successfully retrieved {len(membership_requests)} membership requests for user {user_id}"
        )

        return JSONResponse(
            status_code=200,
            content={
                "message": "Membership requests retrieved successfully",
                "membership_requests": requests_dict,
                "count": len(membership_requests),
            },
        )

    except Exception as e:
        logger.error(f"Error retrieving membership requests for user {user_id}: {e}")
        raise
