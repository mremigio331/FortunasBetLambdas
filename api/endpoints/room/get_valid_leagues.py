from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger

from api.decorators.exceptions_decorator import exceptions_decorator
from common.models.room import allowed_leagues, allowed_sports
from common.config.sport_config import SPORT_REGISTRY
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()

# Map each sport key to its league identifier from the sport config
SPORT_LEAGUE_MAP = {
    key: [rules.espn_league.upper()] for key, rules in SPORT_REGISTRY.items()
}


@router.get("/get_valid_leagues", response_model=dict)
@exceptions_decorator
def get_valid_leagues(request: Request, sport: Optional[str] = Query(None)):
    """
    Get valid/allowed leagues for room creation.
    If a sport query parameter is provided, returns leagues for that sport only.
    Otherwise returns all valid leagues across all sports.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info("Getting valid leagues", extra={"sport_filter": sport})

    try:
        if sport:
            sport_upper = sport.upper()
            if sport_upper not in allowed_sports:
                return JSONResponse(
                    status_code=400,
                    content={
                        "message": f"Invalid sport: {sport}. Must be one of {allowed_sports}",
                    },
                )
            leagues = SPORT_LEAGUE_MAP.get(sport_upper, [])
        else:
            leagues = allowed_leagues

        logger.info(f"Successfully retrieved {len(leagues)} valid leagues")

        return JSONResponse(
            status_code=200,
            content={
                "message": f"Retrieved {len(leagues)} valid leagues successfully",
                "leagues": leagues,
                "count": len(leagues),
            },
        )

    except Exception as e:
        logger.error(f"Error retrieving valid leagues: {e}")
        raise
