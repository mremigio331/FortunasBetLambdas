from fastapi import APIRouter, Request, Path, Depends
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from aws_lambda_powertools import Logger
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from decimal import Decimal
from dateutil.parser import isoparse

from api.decorators.exceptions_decorator import exceptions_decorator
from api.decorators.jwt_decorator import jwt_required
from common.helpers.bet_helper import BetHelper
from common.helpers.membership_helper import MembershipHelper
from common.models.bet import BetModel
from common.constants.services import API_SERVICE
from clients.espn_client import ESPNClient
from exceptions.bet_exceptions import BetNotFound, UserProfileNotFoundException
from common.helpers.week_helper import WeekHelper

logger = Logger(service=API_SERVICE)
router = APIRouter()


@router.get("/get_user_bets_for_current_week", response_model=List[Dict[str, Any]])
@jwt_required()
@exceptions_decorator
def get_user_bets_for_current_week(
    request: Request,
):
    """
    Get all bets for the current week for a specific user.

    Parameters:
    - user_id: The user ID to retrieve bets for
    """
    logger.append_keys(request_id=request.state.request_id)
    user_id = request.state.user_id

    membership_helper = MembershipHelper(request_id=request.state.request_id)
    rooms = membership_helper.get_all_membership_requests_for_user(user_id=user_id)

    week_helper = WeekHelper(request_id=request.state.request_id)
    current_week_info = week_helper.get_nfl_current_week()

    active_rooms = [room for room in rooms if room["status"] == "approved"]
    bet_helper = BetHelper(request_id=request.state.request_id)
    bets = {}
    # Parse week start/end as datetimes
    week_start = (
        isoparse(current_week_info["week_start"])
        if current_week_info["week_start"]
        else None
    )
    week_end = (
        isoparse(current_week_info["week_end"])
        if current_week_info["week_end"]
        else None
    )

    logger.info(f"Active rooms: {active_rooms[0]}")

    for room in active_rooms:
        # PK is in the format 'ROOM#<id>'
        pk = room.get("PK", "")
        room_id = pk.split("#", 1)[1] if "#" in pk else pk
        active_bets = bet_helper.get_user_bets_for_room(
            user_id=user_id,
            room_id=room_id,
        )
        # Filter bets for current week
        one_point = None
        two_point = None
        three_point = None
        for bet in active_bets:
            # event_datetime is epoch seconds
            event_dt = bet.get("event_datetime")
            if event_dt is None:
                continue
            # Convert to datetime
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
        bets[room_id] = {
            "one_point": one_point if one_point else None,
            "two_point": two_point if two_point else None,
            "three_point": three_point if three_point else None,
        }

    logger.info(f"Active rooms for user {user_id}: {len(active_rooms)}")

    return JSONResponse(
        status_code=200,
        content={
            "message": f"Retrieved current NFL week information successfully.",
            "bets": bets,
        },
    )
