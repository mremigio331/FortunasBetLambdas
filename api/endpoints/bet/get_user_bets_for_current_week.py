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
from common.helpers.room_helper import RoomHelper
from common.helpers.mlb_helper import MLBHelper
from common.models.bet import BetModel
from common.constants.services import API_SERVICE
from clients.espn_client import ESPNClient
from exceptions.bet_exceptions import BetNotFound, UserProfileNotFoundException
from common.helpers.week_helper import WeekHelper

logger = Logger(service=API_SERVICE)
router = APIRouter()


def _get_current_mlb_week_boundaries(request_id: str):
    """
    Get the current MLB week boundaries (Monday 00:00:00 EST - Sunday 23:59:59 EST).
    Returns (week_start_epoch, week_end_epoch) for the current week.
    """
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


@router.get("/get_user_bets_for_current_week", response_model=List[Dict[str, Any]])
@jwt_required()
@exceptions_decorator
def get_user_bets_for_current_week(
    request: Request,
):
    """
    Get all bets for the current week for a specific user.
    Sport-aware: uses NFL week schedule for NFL rooms and
    Monday-Sunday EST boundaries for MLB rooms.
    """
    logger.append_keys(request_id=request.state.request_id)
    user_id = getattr(request.state, "user_token", None)

    membership_helper = MembershipHelper(request_id=request.state.request_id)
    rooms = membership_helper.get_all_membership_requests_for_user(user_id=user_id)

    if not rooms:
        logger.info(f"No active rooms found for user {user_id}.")
        return JSONResponse(
            status_code=200,
            content={
                "message": "No active rooms found for the user.",
                "bets": {},
            },
        )

    active_rooms = [room for room in rooms if room["status"] == "approved"]
    week_helper = WeekHelper(request_id=request.state.request_id)
    room_helper = RoomHelper(request_id=request.state.request_id)
    bet_helper = BetHelper(request_id=request.state.request_id)

    # Cache week info per sport so we only compute once
    nfl_week_info = None
    mlb_week_boundaries = None

    bets = {}

    for room in active_rooms:
        pk = room.get("PK", "")
        room_id = pk.split("#", 1)[1] if "#" in pk else pk

        # Look up room sport
        room_data = room_helper.get_room(room_id)
        sport = room_data.get("sport", "NFL") if room_data else "NFL"

        active_bets = bet_helper.get_user_bets_for_room(
            user_id=user_id,
            room_id=room_id,
        )

        if sport == "MLB":
            # Compute MLB week boundaries once
            if mlb_week_boundaries is None:
                mlb_week_boundaries = _get_current_mlb_week_boundaries(
                    request.state.request_id
                )
            week_start_epoch, week_end_epoch = mlb_week_boundaries
            bets[room_id] = _filter_bets_for_mlb_week(
                active_bets, week_start_epoch, week_end_epoch
            )
        else:
            # NFL (default)
            if nfl_week_info is None:
                nfl_week_info = week_helper.get_nfl_current_week()
            week_start = (
                isoparse(nfl_week_info["week_start"])
                if nfl_week_info["week_start"]
                else None
            )
            week_end = (
                isoparse(nfl_week_info["week_end"])
                if nfl_week_info["week_end"]
                else None
            )
            bets[room_id] = _filter_bets_for_nfl_week(active_bets, week_start, week_end)

    logger.info(f"Active rooms for user {user_id}: {len(active_rooms)}")

    return JSONResponse(
        status_code=200,
        content={
            "message": "Retrieved current week bets successfully.",
            "bets": bets,
        },
    )
