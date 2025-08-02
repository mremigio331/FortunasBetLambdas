import base64
import json
from exceptions.jwt_exeptions import InvalidJWTException
import configparser
import os
from aws_lambda_powertools import Logger
from starlette.requests import Request as StarletteRequest
import boto3
import contextvars
from starlette.requests import Request as StarletteRequest
import contextvars

logger = Logger(service="workout-tracer-api")


def decode_jwt(token: str) -> dict:
    """
    Decodes a JWT token without verifying the signature.
    Use only for extracting claims; do not trust the data for authentication/authorization.
    """
    try:
        payload = token.split(".")[1]
        # Pad base64 if needed
        padding = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload + padding)
        claims = json.loads(decoded)
        logger.debug(f"Decoded JWT claims: {claims}")  # Debug log
        return claims
    except Exception as e:
        logger.error(f"Failed to decode JWT: {e}, token: {token}")  # Debug log
        raise InvalidJWTException(f"Invalid JWT: {e}")


def inject_user_token():
    # Remove reading from dev_creds.cfg, only use id_token from cookies
    orig_init = StarletteRequest.__init__

    def new_init(self, *args, **kwargs):
        scope = args[0]
        id_token = None
        headers = list(scope.get("headers", []))
        # Find the cookie header
        cookie_header = next((v for k, v in headers if k == b"cookie"), None)
        if cookie_header:
            cookies = cookie_header.decode("latin-1").split(";")
            for cookie in cookies:
                if cookie.strip().startswith("id_token="):
                    id_token = cookie.strip().split("=", 1)[1]
                    break
        # Only inject Authorization header if id_token is found in cookies
        if id_token and not any(k == b"authorization" for k, v in headers):
            headers.append((b"authorization", f"Bearer {id_token}".encode("latin-1")))
            scope["headers"] = headers
        # Optionally, adjust for local vs. staging/prod (no-op here, but you could add logic if needed)
        orig_init(self, *args, **kwargs)

    StarletteRequest.__init__ = new_init
    logger.debug(
        "Injecting token: Authorization header will be injected from cookies if present."
    )


def update_cognito_user_attributes(
    user_pool_id: str, user_id: str, name: str = None, email: str = None
):
    """
    Update the name and/or email attributes for a user in Cognito User Pool.
    """
    client = boto3.client("cognito-idp", region_name="us-west-2")

    attributes = []
    if name is not None:
        attributes.append({"Name": "name", "Value": name})
    if email is not None:
        attributes.append({"Name": "email", "Value": email})
    if not attributes:
        return

    response = client.admin_update_user_attributes(
        UserPoolId=user_pool_id, Username=user_id, UserAttributes=attributes
    )
    logger.debug(f"Updated Cognito user {user_id} attributes: {attributes}")
    return response
