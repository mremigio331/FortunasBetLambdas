from fastapi import APIRouter, Request, Path
from fastapi.responses import JSONResponse
from aws_lambda_powertools import Logger
from datetime import datetime, timezone
from dateutil.parser import isoparse

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.bet_helper import BetHelper
from common.helpers.room_helper import RoomHelper
from common.helpers.week_helper import WeekHelper
from common.constants.services import API_SERVICE

# Reuse the exact bucketing/boundary logic the consolidated endpoint uses so the
# lazy per-room path stays consistent with the legacy /home/get_home_data.
from api.endpoints.home.get_home_data import (
    _filter_bets_for_nfl_week,
    _filter_bets_for_mlb_week,
    _get_current_mlb_week_boundaries,
)

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/rooms/{room_id}/current-bets")
@jwt_required()
@exceptions_decorator
def get_room_current_bets(
    request: Request,
    room_id: str = Path(..., description="The room ID to load current-week bets for"),
):
    """
    Current-week bets for a single room, bucketed by sport.

    Loaded lazily per room card on the home page so a slow bet lookup for one
    room never blocks the others (and the room list renders without it).
    """
    logger.append_keys(request_id=request.state.request_id)
    user_id = request.state.user_id

    room_helper = RoomHelper(request_id=request.state.request_id)
    room_data = room_helper.get_room(room_id)
    if not room_data:
        return JSONResponse(
            status_code=200,
            content={
                "message": f"Room {room_id} not found.",
                "room_id": room_id,
                "bets": {},
            },
        )

    sport = room_data.get("sport", "NFL")

    bet_helper = BetHelper(request_id=request.state.request_id)
    active_bets = bet_helper.get_user_bets_for_room(user_id=user_id, room_id=room_id)

    if sport == "MLB":
        week_start_epoch, week_end_epoch = _get_current_mlb_week_boundaries(
            request.state.request_id
        )
        bets = _filter_bets_for_mlb_week(active_bets, week_start_epoch, week_end_epoch)
    else:
        week_helper = WeekHelper(request_id=request.state.request_id)
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

    logger.info(f"Retrieved current-week bets for room {room_id}, user {user_id}")
    return JSONResponse(
        status_code=200,
        content={
            "message": "Retrieved current-week bets successfully.",
            "room_id": room_id,
            "room_sport": sport,
            "bets": bets,
        },
    )
