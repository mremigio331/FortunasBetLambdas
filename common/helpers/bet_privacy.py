from aws_lambda_powertools import Logger

from common.constants.services import API_SERVICE

logger = Logger(service=API_SERVICE)

GAME_STARTED_STATUSES = [
    "STATUS_IN_PROGRESS",
    "IN_PROGRESS",
    "LIVE",
    "STATUS_FINAL",
    "FINAL",
    "COMPLETED",
]


def is_game_started(espn_client, sport: str, league: str, game_id: str) -> bool:
    """
    Checks ESPN for game status. Returns True if started/completed.
    Returns False if not started or if ESPN data is unavailable (privacy-safe default).
    """
    try:
        event_data = espn_client.get_event(sport, league, game_id)

        if not event_data:
            logger.warning(
                f"Could not retrieve event data for game {game_id}, defaulting to not started"
            )
            return False

        status_name = event_data.get("status", {}).get("name", "").upper()
        return status_name in GAME_STARTED_STATUSES

    except Exception as e:
        logger.warning(
            f"Error checking game status for {game_id}: {e}, defaulting to not started"
        )
        return False


def redact_hidden_bet(bet_dict: dict) -> dict:
    """
    Redacts sensitive fields from a bet dict for hidden bets.
    Sets game_bet=None, total_points_earned=None, odds_snapshot={}.
    Preserves: user_id, room_id, points_wagered, sport, league, week,
    season_type, event_datetime, submitted_at.
    Returns the modified dict.
    """
    bet_dict["game_bet"] = None
    bet_dict["total_points_earned"] = None
    bet_dict["odds_snapshot"] = {}
    return bet_dict
