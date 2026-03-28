from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger
from typing import List, Dict, Any
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.mlb_helper import MLBHelper
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()

EST = ZoneInfo("America/New_York")


@router.get("/get_current_mlb_week", response_model=List[Dict[str, Any]])
@jwt_required()
@exceptions_decorator
def get_current_mlb_week(request: Request):
    """
    Get the current MLB week boundaries.
    MLB weeks run Monday 00:00:00 EST through Sunday 23:59:59 EST.
    """
    logger.append_keys(request_id=request.state.request_id)

    mlb_helper = MLBHelper(request_id=request.state.request_id)
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    week_start, week_end = mlb_helper.get_mlb_week_boundary(now_epoch)

    start_dt = datetime.fromtimestamp(week_start, tz=EST)
    end_dt = datetime.fromtimestamp(week_end, tz=EST)

    current_week_info = {
        "sport": "MLB",
        "week_start": start_dt.isoformat(),
        "week_end": end_dt.isoformat(),
        "week_start_epoch": week_start,
        "week_end_epoch": week_end,
        "week_label": f"{start_dt.strftime('%b %d')} - {end_dt.strftime('%b %d')}",
    }

    return JSONResponse(
        status_code=200,
        content={
            "message": "Retrieved current MLB week information successfully.",
            "data": current_week_info,
        },
    )
