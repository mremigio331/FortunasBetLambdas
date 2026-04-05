from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger
from datetime import datetime, timezone
from dateutil.parser import isoparse

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.bet_helper import BetHelper
from common.helpers.membership_helper import MembershipHelper
from common.helpers.room_helper import RoomHelper
from common.helpers.mlb_helper import MLBHelper
from common.helpers.week_helper import WeekHelper
from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)
router = APIRouter()


def _get_current_mlb_week_boundaries(request_id: str):
    """Get current MLB week boundaries (Monday 00:00:00 EST - Sunday 23:59:59 EST)."""
    mlb_helper = MLBHelper(request_id=request_id)
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    return mlb_helper.get_mlb_week_boundary(now_epoch)


def _filter_bets_for_nfl_week(active_bets, week_start, week_end):
    """Filter and bucket bets into NFL point slots for the current NFL week."""
    one_point = None
    two_point = None
    three_point = None
    for bet in active_bets:
        event_dt = bet.get("event_datetime")
        if event_dt is None:
            continue
        event_dt = datetime.fromtimestamp(event_dt, tz=timezone.utc)
        if week_start and week_end and not (week_start <= event_dt <= week_end):
            continue
        points = int(bet.get("points_wagered", 0))
        if points == 1:
            one_point = bet
        elif points == 2:
            two_point = bet
        elif points == 3:
            three_point = bet
    return {
        "sport": "NFL",
        "one_point": one_point,
        "two_point": two_point,
        "three_point": three_point,
    }


def _filter_bets_for_mlb_week(active_bets, week_start_epoch, week_end_epoch):
    """Filter bets into MLB structure for the current MLB week."""
    regular_bets = []
    big_bet = None
    for bet in active_bets:
        event_dt = bet.get("event_datetime")
        if event_dt is None:
            continue
        if not (week_start_epoch <= event_dt <= week_end_epoch):
            continue
        points = int(bet.get("points_wagered", 0))
        if points == 6:
            big_bet = bet
        else:
            regular_bets.append(bet)
    return {
        "sport": "MLB",
        "regular_bets": regular_bets,
        "big_bet": big_bet,
        "total_bets": len(regular_bets) + (1 if big_bet else 0),
    }


@router.get("/get_home_data")
@jwt_required()
@exceptions_decorator
def get_home_data(request: Request):
    """
    Consolidated endpoint for the home page.
    Returns active rooms with current week bets for the authenticated user.
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
            content={
                "message": "No active rooms found.",
                "rooms": [],
                "room_count": 0,
            },
        )

    room_helper = RoomHelper(request_id=request.state.request_id)
    bet_helper = BetHelper(request_id=request.state.request_id)
    week_helper = WeekHelper(request_id=request.state.request_id)

    # Cache week info per sport so we only compute once
    nfl_week_info = None
    mlb_week_boundaries = None

    rooms = []

    for membership in approved:
        pk = membership.get("PK", "")
        room_id = pk.split("#", 1)[1] if "#" in pk else pk

        try:
            room_data = room_helper.get_room(room_id)
            if not room_data:
                continue

            sport = room_data.get("sport", "NFL")
            status = room_data.get("status", "Active")

            # Skip archived or completed rooms
            if status in ("Archived", "Completed"):
                continue

            active_bets = bet_helper.get_user_bets_for_room(
                user_id=user_id,
                room_id=room_id,
            )

            if sport == "MLB":
                if mlb_week_boundaries is None:
                    mlb_week_boundaries = _get_current_mlb_week_boundaries(
                        request.state.request_id
                    )
                week_start_epoch, week_end_epoch = mlb_week_boundaries
                bets = _filter_bets_for_mlb_week(
                    active_bets, week_start_epoch, week_end_epoch
                )
            else:
                if nfl_week_info is None:
                    nfl_week_info = week_helper.get_nfl_current_week()
                week_start = (
                    isoparse(nfl_week_info["week_start"])
                    if nfl_week_info.get("week_start")
                    else None
                )
                week_end = (
                    isoparse(nfl_week_info["week_end"])
                    if nfl_week_info.get("week_end")
                    else None
                )
                bets = _filter_bets_for_nfl_week(active_bets, week_start, week_end)

            rooms.append(
                {
                    "room_id": room_id,
                    "room_name": room_data.get("room_name"),
                    "room_sport": sport,
                    "room_status": status,
                    "bets": bets,
                }
            )

        except Exception as e:
            logger.warning(f"Error processing room {room_id} for user {user_id}: {e}")
            rooms.append(
                {
                    "room_id": room_id,
                    "room_name": None,
                    "room_sport": None,
                    "room_status": None,
                    "bets": {},
                }
            )

    logger.info(f"Retrieved home data for user {user_id}: {len(rooms)} active rooms")

    return JSONResponse(
        status_code=200,
        content={
            "message": "Retrieved home data successfully.",
            "rooms": rooms,
            "room_count": len(rooms),
        },
    )
