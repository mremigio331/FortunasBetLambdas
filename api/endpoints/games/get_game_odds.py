from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from clients.espn_client import ESPNClient
from common.constants.services import API_SERVICE
from exceptions.espn_exceptions import ESPNException

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/odds", response_model=dict)
@jwt_required()
@exceptions_decorator
def get_game_odds(
    request: Request,
    sport: str = Query(..., description="Sport, e.g. 'football' or 'baseball'"),
    league: str = Query(..., description="League, e.g. 'nfl' or 'mlb'"),
    game_id: str = Query(..., description="The ESPN game/event id"),
):
    """
    Get betting odds for a single game.

    Called lazily per not-yet-started game after the slate has rendered, so the
    games list appears immediately while lines fill in with a loading state.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info(f"Getting odds for {league} game {game_id} (sport={sport})")

    try:
        espn_client = ESPNClient(request_id=request.state.request_id)
        odds = espn_client.get_game_odds(sport=sport, league=league, game_id=game_id)

        if not odds:
            return JSONResponse(
                status_code=200,
                content={
                    "message": f"No odds available for game {game_id}",
                    "odds": {},
                    "game_id": game_id,
                    "sport": sport,
                    "league": league,
                    "hasOdds": False,
                },
            )

        odds_dict = jsonable_encoder(odds)
        has_odds = odds_dict.get("spread") is not None or (
            odds_dict.get("overUnder") is not None
        )
        logger.info(f"Successfully retrieved odds for game {game_id}")

        return JSONResponse(
            status_code=200,
            content={
                "message": f"Retrieved odds for game {game_id} successfully",
                "odds": odds_dict,
                "game_id": game_id,
                "sport": sport,
                "league": league,
                "hasOdds": has_odds,
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
        logger.error(f"Unexpected error getting game odds: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "message": "Internal server error while fetching game odds",
                "error": str(e),
            },
        )
