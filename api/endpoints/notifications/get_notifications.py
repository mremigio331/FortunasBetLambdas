from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger
from api.decorators.jwt_decorator import jwt_required
from api.decorators.exceptions_decorator import exceptions_decorator
from common.helpers.notification_helper import NotificationHelper
from common.constants.services import API_SERVICE
from fastapi.encoders import jsonable_encoder

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/get_notifications", response_model=dict)
@jwt_required()
@exceptions_decorator
def get_notifications(request: Request):
    """
    Get all notifications for the authenticated user.
    """
    logger.append_keys(request_id=getattr(request.state, "request_id", None))
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        logger.warning("No user_id found in request state.")
        return JSONResponse(status_code=401, content={"message": "Unauthorized"})

    notification_helper = NotificationHelper(
        request_id=getattr(request.state, "request_id", None)
    )
    notifications = notification_helper.get_notifications(user_id)
    logger.info(f"Retrieved {len(notifications)} notifications for user {user_id}.")
    return JSONResponse(
        status_code=200,
        content={
            "message": "Notifications retrieved successfully.",
            "notifications": jsonable_encoder(notifications),
        },
    )
