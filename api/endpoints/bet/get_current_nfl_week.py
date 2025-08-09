from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger
from typing import List, Dict, Any
from datetime import datetime, timezone
from dateutil.parser import isoparse

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from clients.espn_client import ESPNClient
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
    espn_client = ESPNClient(request_id=request.state.request_id)

    now = datetime.now(timezone.utc)
    full_schedule = espn_client.get_nfl_schedule(now.year)
    schedule = full_schedule["leagues"][0]["calendar"]

    current_week_info = {
        "season_type_label": None,
        "season_type_value": None,
        "week_label": None,
        "week_value": None,
        "week_start": None,
        "week_end": None,
    }

    for season in schedule:
        for week in season.get("entries", []):
            start = isoparse(week["startDate"])
            end = isoparse(week["endDate"])
            if start <= now <= end:
                current_week_info = {
                    "season_type_label": season["label"],
                    "season_type_value": season["value"],
                    "week_label": week["label"],
                    "week_value": week["value"],
                    "week_start": week["startDate"],
                    "week_end": week["endDate"],
                }

    return JSONResponse(
        status_code=200,
        content={
            "message": f"Retrieved current NFL week information successfully: {now}.",
            "data": current_week_info,
        },
    )
