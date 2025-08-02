from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response
from starlette.requests import Request
from urllib.parse import urlencode, urlparse, parse_qs
import os
import httpx
from aws_lambda_powertools import Logger
from common.constants.services import API_SERVICE

COGNITO_DOMAIN = os.getenv("COGNITO_DOMAIN", "")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "")
# Update redirect URI to port 5000
COGNITO_API_REDIRECT_URI = os.getenv("COGNITO_API_REDIRECT_URI")
COGNITO_AUTH_URL = f"{COGNITO_DOMAIN}/login?" + urlencode(
    {
        "client_id": COGNITO_CLIENT_ID,
        "response_type": "code",  # Use code flow
        "scope": "openid email profile",
        "redirect_uri": COGNITO_API_REDIRECT_URI,
    }
)

logger = Logger(service=API_SERVICE)


class CognitoAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        logger.debug(f"Processing authentication request: {request.url.path}")
        # Only apply to /docs and root (for redirect)
        if request.url.path in ["/docs", "/"]:
            id_token = request.cookies.get("id_token")
            code = request.query_params.get("code")
            logger.debug(
                f"Authentication tokens - id_token: {bool(id_token)}, code: {bool(code)}"
            )
            if not id_token and code:
                logger.info("Attempting token exchange with authorization code")
                # Exchange code for tokens
                async with httpx.AsyncClient() as client:
                    token_resp = await client.post(
                        f"{COGNITO_DOMAIN}/oauth2/token",
                        data={
                            "grant_type": "authorization_code",
                            "client_id": COGNITO_CLIENT_ID,
                            "code": code,
                            "redirect_uri": COGNITO_API_REDIRECT_URI,
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                logger.debug(
                    f"Token exchange response status: {token_resp.status_code}"
                )
                if token_resp.status_code == 200:
                    tokens = token_resp.json()
                    id_token = tokens.get("id_token")
                    logger.info(
                        f"Token exchange successful, id_token received: {bool(id_token)}"
                    )
                    if id_token:
                        response = RedirectResponse(url="/docs")
                        response.set_cookie("id_token", id_token, httponly=True)
                        return response
                else:
                    logger.error(
                        f"Token exchange failed with status {token_resp.status_code}: {token_resp.text}"
                    )
                # If token exchange fails, redirect to Cognito login
                logger.info(
                    "Redirecting to Cognito login due to token exchange failure"
                )
                return RedirectResponse(COGNITO_AUTH_URL)
            # This block is likely NOT being executed because another middleware (JWTMiddleware) is returning 401 first
            if request.url.path == "/docs" and not id_token:
                logger.info(
                    "No id_token found for /docs endpoint, redirecting to Cognito login"
                )
                return RedirectResponse(COGNITO_AUTH_URL)
        response = await call_next(request)
        logger.debug(
            f"Request processed: {request.url.path} -> {getattr(response, 'status_code', 'unknown')}"
        )
        return response
