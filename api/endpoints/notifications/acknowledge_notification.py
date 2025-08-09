from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger
from api.decorators.jwt_decorator import jwt_required
from api.decorators.exceptions_decorator import exceptions_decorator
from common.helpers.notification_helper import NotificationHelper
from common.constants.services import API_SERVICE
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field


logger = Logger(service=API_SERVICE)
router = APIRouter()


class AcknowledgeNotificationRequest(BaseModel):
    notification_id: str = Field(
        ..., description="The ID of the notification to acknowledge"
    )


@router.put("/acknowledge_notification", response_model=dict)
@jwt_required()
@exceptions_decorator
def acknowledge_notification(request: Request, body: AcknowledgeNotificationRequest):
    """
    Acknowledge a notification for the authenticated user.
    """
    logger.append_keys(request_id=request.state.request_id)
    user_id = getattr(request.state, "user_id", None)

    notification_helper = NotificationHelper(request_id=request.state.request_id)
    notification_helper.acknowledge_notification(user_id, body.notification_id)

    logger.info(f"Acknowledged notification {body.notification_id} for user {user_id}.")
    return JSONResponse(
        status_code=200,
        content={
            "message": "Notification acknowledged successfully.",
        },
    )
