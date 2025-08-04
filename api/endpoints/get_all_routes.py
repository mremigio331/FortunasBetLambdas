from api.endpoints.fortunas_bet import home
from api.endpoints.user import get_requestors_profile, update_user_profile
from api.endpoints.room import (
    create_room,
    edit_room,
    get_room,
    get_all_rooms,
    get_valid_leagues,
)
from api.endpoints.membership import (
    get_all_membership_request,
    get_admin_requests,
    create_membership_request,
    edit_membership_requests,
    get_user_membership_requests,
    get_room_members,
    change_member_status,
)
from api.endpoints.bet import create_bet, get_bets_for_room
from api.endpoints.odds import get_nfl_odds, get_nfl_weeks_in_range
from common.constants.tags import BET, HOME, USER_PROFILE, ROOM, MEMBERSHIP, ODDS
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
    app.include_router(get_all_rooms.router, prefix="/room", tags=[ROOM])
    app.include_router(get_valid_leagues.router, prefix="/room", tags=[ROOM])
    app.include_router(get_room.router, prefix="/room", tags=[ROOM])

    app.include_router(
        get_all_membership_request.router, prefix="/membership", tags=[MEMBERSHIP]
    )
    app.include_router(
        get_admin_requests.router, prefix="/membership", tags=[MEMBERSHIP]
    )
    app.include_router(
        create_membership_request.router, prefix="/membership", tags=[MEMBERSHIP]
    )
    app.include_router(
        edit_membership_requests.router, prefix="/membership", tags=[MEMBERSHIP]
    )
    app.include_router(
        get_user_membership_requests.router, prefix="/membership", tags=[MEMBERSHIP]
    )
    app.include_router(get_room_members.router, prefix="/membership", tags=[MEMBERSHIP])
    app.include_router(
        change_member_status.router, prefix="/membership", tags=[MEMBERSHIP]
    )

    app.include_router(get_nfl_odds.router, prefix="/odds", tags=[ODDS])
    app.include_router(get_nfl_weeks_in_range.router, prefix="/odds", tags=[ODDS])

    app.include_router(create_bet.router, prefix="/bet", tags=[BET])
    app.include_router(get_bets_for_room.router, prefix="/bet", tags=[BET])

    return app
