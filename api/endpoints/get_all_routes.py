from api.endpoints.fortunas_bet import home
from api.endpoints.user import get_requestors_profile
from common.constants.tags import HOME, USER_PROFILE
from fastapi import FastAPI


def get_all_routes(app: FastAPI) -> FastAPI:
    """
    Registers all API routes with the FastAPI application.

    Args:
        app (FastAPI): The FastAPI application instance.

    Returns:
        FastAPI: The updated FastAPI application instance with all routes registered.
    """
    app.include_router(home.router, prefix="/fortunasbet", tags=[HOME])
    app.include_router(
        get_requestors_profile.router, prefix="/user", tags=[USER_PROFILE]
    )
    return app
