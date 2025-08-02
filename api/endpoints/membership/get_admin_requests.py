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


@router.get("/get_admin_requests", response_model=dict)
@jwt_required()
@exceptions_decorator
def get_admin_requests(request: Request):
    """
    Get all membership requests for rooms where the authenticated user has admin privileges.
    Returns a list of membership requests that the user can approve/deny as an admin.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info("Getting all admin membership requests for user")

    user_id = request.state.user_id
    logger.info(f"user_id from JWT: {user_id}")

    try:
        membership_helper = MembershipHelper(request_id=request.state.request_id)

        admin_room_ids = membership_helper.get_admin_room_ids_for_user(user_id)
        logger.info(f"User {user_id} is admin for {len(admin_room_ids)} rooms")

        if admin_room_ids:
            admin_requests = membership_helper.get_membership_requests_for_rooms(
                admin_room_ids
            )
        else:
            admin_requests = []
            logger.info(f"User {user_id} is not admin for any rooms")

        requests_dict = jsonable_encoder(admin_requests)
        logger.info(
            f"Successfully retrieved {len(admin_requests)} admin membership requests for user {user_id}"
        )

        return JSONResponse(
            status_code=200,
            content={
                "message": "Admin membership requests retrieved successfully",
                "admin_requests": requests_dict,
                "admin_room_ids": admin_room_ids,
                "count": len(admin_requests),
            },
        )

    except Exception as e:
        logger.error(
            f"Error retrieving admin membership requests for user {user_id}: {e}"
        )
        raise
