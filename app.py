from fastapi import FastAPI, Request, Depends
from mangum import Mangum
from aws_lambda_powertools import Logger
from middleware.request_id_middlware import RequestIdMiddleware
from middleware.memory_cleanup_middleware import MemoryCleanupMiddleware
from api.endpoints.get_all_routes import get_all_routes
from fastapi.middleware.cors import CORSMiddleware
from middleware.jtw_middleware import JWTMiddleware
from common.helpers.jwt import inject_user_token
from middleware.cognito_auth_middleware import CognitoAuthMiddleware
import os
import configparser
from starlette.middleware.base import BaseHTTPMiddleware
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
app = FastAPI(
    title="FortunasBet API",
    description="API for FortunasBet application.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


stage = os.getenv("STAGE", "").lower()
if stage == "prod":
    allowed_origins = ["https://fortunasbet.com"]
elif stage == "testing":
    allowed_origins = ["https://testing.fortunasbet.com"]
else:
    allowed_origins = ["*"]

app.add_middleware(CognitoAuthMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(JWTMiddleware)
app.add_middleware(MemoryCleanupMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

inject_user_token()

app = get_all_routes(app)

handler = Mangum(app)
