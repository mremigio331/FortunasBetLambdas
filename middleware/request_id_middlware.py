from starlette.middleware.base import BaseHTTPMiddleware
from aws_lambda_powertools import Logger
from common.constants.services import API_SERVICE
import uuid

logger = Logger(service=API_SERVICE)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        context = request.scope.get("aws.context")
        if context:
            request_id = getattr(context, "aws_request_id", None)
            logger.append_keys(request_id=request_id)
        else:
            request_id = str(uuid.uuid4())
            logger.append_keys(request_id=request_id)
            logger.info("No aws.context found generated request_id")
        request.state.request_id = request_id
        response = await call_next(request)
        return response
