from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger

from api.decorators.exceptions_decorator import exceptions_decorator
from common.models.room import allowed_leagues
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/get_valid_leagues", response_model=dict)
@exceptions_decorator
def get_valid_leagues(request: Request):
    """
    Get all valid/allowed leagues for room creation.
    Returns a list of valid league options.
    """
    logger.append_keys(request_id=request.state.request_id)
    logger.info("Getting valid leagues")

    try:
        logger.info(f"Successfully retrieved {len(allowed_leagues)} valid leagues")

        return JSONResponse(
            status_code=200,
            content={
                "message": f"Retrieved {len(allowed_leagues)} valid leagues successfully",
                "leagues": allowed_leagues,
                "count": len(allowed_leagues),
            },
        )

    except Exception as e:
        logger.error(f"Error retrieving valid leagues: {e}")
        raise
