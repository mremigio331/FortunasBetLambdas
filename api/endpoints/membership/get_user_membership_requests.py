from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from typing import List, Dict, Any

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.membership_helper import MembershipHelper
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/user_membership_requests", response_model=List[Dict[str, Any]])
@jwt_required()
@exceptions_decorator
def get_user_membership_requests(request: Request):
    """
    Get all membership requests for the authenticated user.
    Returns all membership requests where the user is the requestor.
    """
    logger.append_keys(request_id=request.state.request_id)

    user_id = request.state.user_id
    logger.info(f"Getting membership requests for user {user_id}")

    try:
        membership_helper = MembershipHelper(request_id=request.state.request_id)

        # Get all membership requests for the user
        membership_requests = membership_helper.get_all_membership_requests_for_user(
            user_id
        )

        # Transform the data to include room_id and remove PK/SK
        transformed_requests = []
        for request in membership_requests:
            # Extract room_id from PK field (format: "ROOM#<room_id>")
            room_id = None
            if request.get("PK"):
                pk_match = (
                    request["PK"].replace("ROOM#", "")
                    if request["PK"].startswith("ROOM#")
                    else None
                )
                if pk_match:
                    room_id = pk_match

            # Create cleaned request object
            cleaned_request = {
                "room_id": room_id,
                "status": request.get("status"),
                "created_at": request.get("created_at"),
                "requestor": request.get("requestor"),
                "room_name": request.get("room_name"),
                "membership_type": request.get("membership_type"),
                "join_date": request.get("join_date"),
                "admin_id": request.get("admin_id"),
                "invited_user": request.get("invited_user"),
            }

            # Only include if we successfully extracted room_id
            if room_id:
                transformed_requests.append(cleaned_request)

        # Convert to JSON-serializable format (handles Decimal objects)
        serializable_requests = jsonable_encoder(transformed_requests)

        logger.info(
            f"Successfully retrieved {len(serializable_requests)} membership requests for user {user_id}"
        )

        return JSONResponse(
            status_code=200,
            content={
                "message": f"Retrieved membership requests for user {user_id}",
                "data": {
                    "membership_requests": serializable_requests,
                    "count": len(serializable_requests),
                },
            },
        )

    except Exception as e:
        logger.error(
            f"Error retrieving membership requests for user {user_id}: {str(e)}"
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "message": f"Failed to retrieve membership requests for user {user_id}",
            },
        )
