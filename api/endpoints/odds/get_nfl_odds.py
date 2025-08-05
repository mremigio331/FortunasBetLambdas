from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from typing import Optional

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_optional
from clients.espn_client import ESPNClient
from common.constants.services import API_SERVICE
from exceptions.espn_exceptions import ESPNException

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/get_nfl_odds", response_model=dict)
@jwt_optional()
@exceptions_decorator
def get_nfl_odds(
    request: Request,
    week: int = Query(..., description="NFL week number", ge=1, le=18),
    year: int = Query(..., description="NFL season year", ge=2020, le=2030),
    season_type: int = Query(
        2, description="Season type (1=preseason, 2=regular, 3=postseason)", ge=1, le=3
    ),
):
    """
    Get comprehensive NFL odds data for a specific week and year.

    Returns odds information including spreads, money lines, over/under lines,
    and other betting data for all games in the specified week.

    Parameters:
    - week: NFL week number (1-18 for regular season)
    - year: NFL season year (e.g., 2024)
    - season_type: 1=preseason, 2=regular season, 3=postseason
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info(
        f"Getting NFL odds for week {week}, year {year}, season_type {season_type}"
    )

    try:
        espn_client = ESPNClient(request_id=request.state.request_id)
        odds_data = espn_client.get_nfl_week_odds(
            week=week, year=year, season_type=season_type
        )

        if not odds_data:
            logger.warning(f"No odds data found for week {week}, year {year}")
            return JSONResponse(
                status_code=200,
                content={
                    "message": f"No odds data available for NFL week {week}, {year}",
                    "odds": [],
                    "count": 0,
                    "week": week,
                    "year": year,
                    "season_type": season_type,
                    "sport": "football",
                    "league": "nfl",
                },
            )

        odds_dict = jsonable_encoder(odds_data)
        logger.info(f"Successfully retrieved odds for {len(odds_data)} games")

        return JSONResponse(
            status_code=200,
            content={
                "message": f"Retrieved NFL odds for week {week}, {year} successfully",
                "odds": odds_dict,
                "count": len(odds_data),
                "week": week,
                "year": year,
                "season_type": season_type,
                "sport": "football",
                "league": "nfl",
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
        logger.error(f"Unexpected error getting NFL odds: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "message": "Internal server error while fetching NFL odds",
                "error": str(e),
            },
        )
