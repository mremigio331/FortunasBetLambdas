from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger
from typing import Optional
from pydantic import BaseModel, Field

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.week_helper import WeekHelper
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


class CurrentNflWeek(BaseModel):
    """The authoritative current NFL week resolved from the ESPN schedule."""

    is_off_season: bool = Field(
        ...,
        description=(
            "True when the present moment falls outside every week of the "
            "schedule. An explicit indicator so callers do not have to infer "
            "off-season from null week fields."
        ),
    )
    season_year: Optional[int] = Field(
        None,
        description=(
            "NFL Season_Year the week belongs to. The season is keyed on the "
            "year it started in, so January/February playoff weeks report the "
            "prior calendar year."
        ),
    )
    season_type_label: Optional[str] = Field(
        None, description="Season type label (e.g. 'Regular Season')"
    )
    season_type_value: Optional[int] = Field(
        None, description="Numeric season type (1=preseason, 2=regular, 3=postseason)"
    )
    week_label: Optional[str] = Field(
        None, description="Week label (e.g. 'Week 12', 'Wild Card')"
    )
    week_value: Optional[int] = Field(
        None, description="Numeric week number within the season type"
    )
    week_start: Optional[str] = Field(
        None, description="Week start as an ISO 8601 timestamp with offset"
    )
    week_end: Optional[str] = Field(
        None, description="Week end as an ISO 8601 timestamp with offset"
    )


class CurrentNflWeekResponse(BaseModel):
    """Envelope returned by /bet/get_current_nfl_week."""

    message: str
    data: CurrentNflWeek


@router.get("/get_current_nfl_week", response_model=CurrentNflWeekResponse)
@jwt_required()
@exceptions_decorator
def get_current_nfl_week(request: Request) -> JSONResponse:
    """
    Fetch the current NFL week information from the authoritative week source.
    """
    week_helper = WeekHelper(request_id=request.state.request_id)

    current_week_info = week_helper.get_nfl_current_week()

    return JSONResponse(
        status_code=200,
        content={
            "message": "Retrieved current NFL week information successfully.",
            "data": current_week_info,
        },
    )
