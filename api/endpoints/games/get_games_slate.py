from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from typing import Optional

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from clients.espn_client import ESPNClient
from common.constants.services import API_SERVICE
from exceptions.espn_exceptions import ESPNException

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/slate", response_model=dict)
@jwt_required()
@exceptions_decorator
def get_games_slate(
    request: Request,
    sport: str = Query(..., description="Sport, e.g. 'football' or 'baseball'"),
    league: str = Query(..., description="League, e.g. 'nfl' or 'mlb'"),
    week: Optional[int] = Query(
        None, description="NFL week number (required for NFL)", ge=1, le=18
    ),
    year: Optional[int] = Query(
        None, description="Season year (required for NFL)", ge=2020, le=2030
    ),
    season_type: int = Query(
        2,
        description="Season type (1=preseason, 2=regular, 3=postseason)",
        ge=1,
        le=3,
    ),
    date: Optional[str] = Query(
        None,
        description="Date in YYYYMMDD format (required for MLB)",
    ),
):
    """
    Get all games for a slate WITHOUT odds.

    Fast bulk call (single ESPN scoreboard request) used to render the games
    list immediately. Odds are loaded lazily per not-yet-started game via
    GET /games/odds. NFL uses week/year/season_type; MLB uses date.
    """
    logger.append_keys(request_id=request.state.request_id)
    league_lower = (league or "").lower()
    logger.info(
        f"Getting {league_lower} slate (week={week}, year={year}, "
        f"season_type={season_type}, date={date})"
    )

    if league_lower == "mlb":
        if not date:
            return JSONResponse(
                status_code=400,
                content={
                    "message": "date (YYYYMMDD) is required for MLB slate",
                    "error": "MISSING_DATE",
                },
            )
    else:
        if week is None or year is None:
            return JSONResponse(
                status_code=400,
                content={
                    "message": "week and year are required for NFL slate",
                    "error": "MISSING_WEEK_OR_YEAR",
                },
            )

    try:
        espn_client = ESPNClient(request_id=request.state.request_id)
        games = espn_client.get_slate(
            sport=sport,
            league=league,
            week=week,
            year=year,
            season_type=season_type,
            date=date,
        )

        games_dict = jsonable_encoder(games)
        logger.info(f"Successfully retrieved {len(games_dict)} games for slate")

        return JSONResponse(
            status_code=200,
            content={
                "message": "Retrieved games slate successfully",
                "games": games_dict,
                "count": len(games_dict),
                "sport": sport,
                "league": league,
                "week": week,
                "year": year,
                "season_type": season_type,
                "date": date,
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
        logger.error(f"Unexpected error getting games slate: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "message": "Internal server error while fetching games slate",
                "error": str(e),
            },
        )
