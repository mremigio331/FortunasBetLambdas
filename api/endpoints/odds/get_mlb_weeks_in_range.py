from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger
from aws_lambda_powertools.metrics import Metrics, MetricUnit

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_optional
from common.helpers.mlb_helper import MLBHelper
from common.constants.services import API_SERVICE
from common.constants.metrics import API_METRICS_NAMESPACE, ENDPOINT
from datetime import datetime

router = APIRouter()
logger = Logger(service=API_SERVICE)
metrics = Metrics(namespace=API_METRICS_NAMESPACE, service=API_SERVICE)

GET_MLB_WEEKS_SUCCESS = "GetMLBWeeksSuccess"
GET_MLB_WEEKS_EXCEPTION = "GetMLBWeeksException"


@router.get("/get_mlb_weeks_in_range")
@jwt_optional()
@exceptions_decorator
def get_mlb_weeks_in_range(
    request: Request,
    start_date: int = Query(..., description="Start date in epoch timestamp"),
    end_date: int = Query(..., description="End date in epoch timestamp"),
):
    """
    Get MLB weeks (Monday-Sunday EST) that fall within the specified date range.

    Parameters:
    - start_date: Start date in epoch timestamp
    - end_date: End date in epoch timestamp

    Returns:
    - List of MLB weeks with start/end epochs, labels, and ISO dates
    """
    logger.append_keys(request_id=request.state.request_id)
    metrics.add_dimension(name=ENDPOINT, value="/odds/get_mlb_weeks_in_range")

    try:
        if start_date >= end_date:
            raise HTTPException(
                status_code=400, detail="Start date must be before end date"
            )

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

        logger.info(f"Getting MLB weeks for range: {start_date} to {end_date}")

        mlb_helper = MLBHelper(request_id=request.state.request_id)
        weeks = mlb_helper.get_mlb_weeks_in_range(start_date, end_date)

        response_data = {
            "start_date": start_date,
            "end_date": end_date,
            "start_date_iso": datetime.fromtimestamp(start_date).isoformat(),
            "end_date_iso": datetime.fromtimestamp(end_date).isoformat(),
            "total_weeks_found": len(weeks),
            "weeks": weeks,
            "sport": "baseball",
            "league": "mlb",
        }

        metrics.add_metric(name=GET_MLB_WEEKS_SUCCESS, unit=MetricUnit.Count, value=1)
        metrics.flush_metrics()

        logger.info(f"Found {len(weeks)} MLB weeks in specified range")

        return JSONResponse(status_code=200, content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        metrics.add_metric(name=GET_MLB_WEEKS_EXCEPTION, unit=MetricUnit.Count, value=1)
        metrics.flush_metrics()

        logger.error(f"Error getting MLB weeks in range: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
