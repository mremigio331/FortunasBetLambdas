from fastapi import APIRouter
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger
from common.constants.services import API_SERVICE

# Set up structured logger
logger = Logger(service=API_SERVICE)

router = APIRouter()


@router.get(path="/", summary="Home Endpoint", response_description="Welcome message")
async def home():
    """
    Home Endpoint

    Returns:
        A welcome message for the PAT API.
    """
    logger.info("Called home endpoint.")
    return JSONResponse(
        content={"message": "Welcome to FortunasBet API"}, status_code=200
    )
