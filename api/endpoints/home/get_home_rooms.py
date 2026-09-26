from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.membership_helper import MembershipHelper
from common.helpers.room_helper import RoomHelper
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/rooms")
@jwt_required()
@exceptions_decorator
def get_home_rooms(request: Request):
    """
    Fast home-page room list: the user's approved, active rooms only.

    This intentionally omits current-week bets and week resolution so the home
    page can render room cards immediately. Bets are loaded lazily per room via
    GET /home/rooms/{room_id}/current-bets.
    """
    logger.append_keys(request_id=request.state.request_id)
    user_id = request.state.user_id

    membership_helper = MembershipHelper(request_id=request.state.request_id)
    all_memberships = membership_helper.get_all_membership_requests_for_user(
        user_id=user_id
    )

    approved = [m for m in all_memberships if m.get("status") == "approved"]
    if not approved:
        return JSONResponse(
            status_code=200,
            content={"message": "No active rooms found.", "rooms": [], "room_count": 0},
        )

    room_helper = RoomHelper(request_id=request.state.request_id)
    rooms = []

    for membership in approved:
        pk = membership.get("PK", "")
        room_id = pk.split("#", 1)[1] if "#" in pk else pk

        try:
            room_data = room_helper.get_room(room_id)
            if not room_data:
                continue

            status = room_data.get("status", "Active")
            if status in ("Archived", "Completed"):
                continue

            rooms.append(
                {
                    "room_id": room_id,
                    "room_name": room_data.get("room_name"),
                    "room_sport": room_data.get("sport", "NFL"),
                    "room_status": status,
                }
            )
        except Exception as e:
            logger.warning(f"Error loading room {room_id} for user {user_id}: {e}")
            continue

    logger.info(f"Retrieved {len(rooms)} home rooms for user {user_id}")
    return JSONResponse(
        status_code=200,
        content={
            "message": "Retrieved home rooms successfully.",
            "rooms": rooms,
            "room_count": len(rooms),
        },
    )
