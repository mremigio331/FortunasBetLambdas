from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger
from typing import List, Dict, Any
from datetime import datetime, timezone
from dateutil.parser import isoparse

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.week_helper import WeekHelper
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/get_current_nfl_week", response_model=List[Dict[str, Any]])
@jwt_required()
@exceptions_decorator
def get_current_nfl_week(request: Request) -> List[int]:
    """
    Fetch the current NFL schedule weeks from the ESPN client.
    """
    week_helper = WeekHelper(request_id=request.state.request_id)

    current_week_info = week_helper.get_nfl_current_week()

    return JSONResponse(
        status_code=200,
        content={
            "message": f"Retrieved current NFL week information successfully.",
            "data": current_week_info,
        },
    )
