from api.endpoints.fortunas_bet import home
from api.endpoints.user import get_requestors_profile, update_user_profile
from api.endpoints.room import create_room, edit_room
from common.constants.tags import HOME, USER_PROFILE, ROOM
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
    app.include_router(update_user_profile.router, prefix="/user", tags=[USER_PROFILE])
    app.include_router(create_room.router, prefix="/room", tags=[ROOM])
    app.include_router(edit_room.router, prefix="/room", tags=[ROOM])
    return app
