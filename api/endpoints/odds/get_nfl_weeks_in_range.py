from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger
from aws_lambda_powertools.metrics import Metrics, MetricUnit
from common.helpers.nfl_helper import NFLHelper
from common.constants.services import API_SERVICE
from common.constants.metrics import (
    API_METRICS_NAMESPACE,
    GET_NFL_WEEKS_SUCCESS,
    GET_NFL_WEEKS_EXCEPTION,
    ENDPOINT,
)
from datetime import datetime

router = APIRouter()
logger = Logger(service=API_SERVICE)
metrics = Metrics(namespace=API_METRICS_NAMESPACE, service=API_SERVICE)


@router.get("/get_nfl_weeks_in_range")
async def get_nfl_weeks_in_range(
    request: Request,
    start_date: int = Query(..., description="Start date in epoch timestamp"),
    end_date: int = Query(..., description="End date in epoch timestamp"),
):
    """
    Get NFL weeks that fall within the specified date range.

    Parameters:
    - start_date: Start date in epoch timestamp
    - end_date: End date in epoch timestamp
    - request_id: Optional request ID for tracking

    Returns:
    - List of NFL weeks with season information that fall within the date range
    """

    logger.append_keys(request_id=request.state.request_id)

    metrics.add_dimension(name=ENDPOINT, value="/odds/get_nfl_weeks_in_range")

    try:
        # Validate input dates
        if start_date >= end_date:
            raise HTTPException(
                status_code=400, detail="Start date must be before end date"
            )

        # Validate that dates are reasonable (not too far in past/future)
        current_timestamp = datetime.now().timestamp()
        max_range = 365 * 24 * 60 * 60 * 5  # 5 years in seconds

        if (
            abs(start_date - current_timestamp) > max_range
            or abs(end_date - current_timestamp) > max_range
        ):
            raise HTTPException(
                status_code=400,
                detail="Date range too large or too far from current date (max 5 years)",
            )

        logger.info(f"Getting NFL weeks for range: {start_date} to {end_date}")

        # Initialize NFL helper
        nfl_helper = NFLHelper(request_id=request.state.request_id)

        # Find weeks in range
        weeks_in_range = nfl_helper.find_nfl_weeks_in_range(start_date, end_date)

        # Group by season for easier consumption
        seasons_summary = nfl_helper.group_weeks_by_season(weeks_in_range)

        response_data = {
            "start_date": start_date,
            "end_date": end_date,
            "start_date_iso": datetime.fromtimestamp(start_date).isoformat(),
            "end_date_iso": datetime.fromtimestamp(end_date).isoformat(),
            "total_weeks_found": len(weeks_in_range),
            "seasons_summary": seasons_summary,
            "detailed_weeks": weeks_in_range,
        }

        metrics.add_metric(name=GET_NFL_WEEKS_SUCCESS, unit=MetricUnit.Count, value=1)
        metrics.flush_metrics()

        logger.info(f"Found {len(weeks_in_range)} NFL weeks in specified range")

        return JSONResponse(status_code=200, content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        metrics.add_metric(name=GET_NFL_WEEKS_EXCEPTION, unit=MetricUnit.Count, value=1)
        metrics.flush_metrics()

        logger.error(f"Error getting NFL weeks in range: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
