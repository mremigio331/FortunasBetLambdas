from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.datastructures import MutableHeaders
from aws_lambda_powertools import Logger
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)


class VersioningMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        git_commit = request.headers.get("X-Git-Commit")
        if git_commit:
            logger.info(f"Captured X-Git-Commit: {git_commit}")
        else:
            logger.info("X-Git-Commit header not found.")
        response = await call_next(request)
        return response
