from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_optional
from clients.espn_client import ESPNClient
from common.constants.services import API_SERVICE
from exceptions.espn_exceptions import ESPNException

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/get_mlb_odds", response_model=dict)
@jwt_optional()
@exceptions_decorator
def get_mlb_odds(
    request: Request,
    date: str = Query(
        ...,
        description="Date in YYYYMMDD format (e.g., 20250920)",
        min_length=8,
        max_length=8,
    ),
):
    """
    Get MLB games with odds for a specific date.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info(f"Getting MLB odds for date {date}")

    try:
        espn_client = ESPNClient(request_id=request.state.request_id)
        odds_data = espn_client.get_mlb_scoreboard_with_odds(date=date)

        if not odds_data:
            return JSONResponse(
                status_code=200,
                content={
                    "message": f"No odds data available for MLB on {date}",
                    "odds": [],
                    "count": 0,
                    "date": date,
                    "sport": "baseball",
                    "league": "mlb",
                },
            )

        odds_dict = jsonable_encoder(odds_data)
        logger.info(f"Successfully retrieved odds for {len(odds_data)} MLB games")

        return JSONResponse(
            status_code=200,
            content={
                "message": f"Retrieved MLB odds for {date} successfully",
                "odds": odds_dict,
                "count": len(odds_data),
                "date": date,
                "sport": "baseball",
                "league": "mlb",
            },
        )

    except ESPNException as e:
        logger.error(f"ESPN API error: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "message": "ESPN service temporarily unavailable",
                "error": str(e),
            },
        )

    except Exception as e:
        logger.error(f"Unexpected error getting MLB odds: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "message": "Internal server error while fetching MLB odds",
                "error": str(e),
            },
        )
