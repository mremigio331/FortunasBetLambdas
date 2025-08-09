from aws_lambda_powertools import Logger
from datetime import datetime, timedelta
from typing import Optional, Tuple
from common.helpers.nfl_helper import NFLHelper
from clients.espn_client import ESPNClient
from datetime import datetime, timezone
from dateutil.parser import isoparse


class WeekHelper:
    """
    A class to handle week boundary calculations for different sports.
    """

    def __init__(self, request_id: str):
        self.logger = Logger()
        self.logger.append_keys(request_id=request_id)
        self.request_id = request_id

    def get_week_boundary(
        self, sport: str, league: str, event_datetime: int, game_id: str = None
    ) -> Optional[Tuple[int, int]]:
        """
        Get week start and end boundaries based on sport and league.

        Args:
            sport: The sport (e.g., 'football', 'basketball')
            league: The league (e.g., 'nfl', 'nba')
            event_datetime: Event timestamp in epoch seconds
            game_id: Optional game ID for sports that need specific game lookup

        Returns:
            tuple: (week_start_epoch, week_end_epoch) or None if not found
        """
        sport_lower = sport.lower()
        league_lower = league.lower()

        # NFL and NCAA Football use sport-specific weeks
        if sport_lower == "football" and league_lower in ["nfl", "ncaa"]:
            return self._get_football_week_boundary(
                league_lower, event_datetime, game_id
            )

        # Other sports use calendar weeks
        else:
            return self._get_calendar_week_boundary(event_datetime)

    def _get_football_week_boundary(
        self, league: str, event_datetime: int, game_id: str = None
    ) -> Optional[Tuple[int, int]]:
        """
        Get week boundaries for football leagues (NFL/NCAA).

        Args:
            league: The football league ('nfl' or 'ncaa')
            event_datetime: Event timestamp in epoch seconds
            game_id: The game ID to look up the specific week

        Returns:
            tuple: (week_start_epoch, week_end_epoch) or None if not found
        """
        if league == "nfl":
            return self._get_nfl_week_boundary(event_datetime, game_id)
        elif league == "ncaa":
            # For now, use calendar weeks for NCAA - can be enhanced later
            self.logger.info("Using calendar week boundary for NCAA football")
            return self._get_calendar_week_boundary(event_datetime)
        else:
            self.logger.warning(f"Unknown football league: {league}")
            return None

    def _get_nfl_week_boundary(
        self, event_datetime: int, game_id: str = None
    ) -> Optional[Tuple[int, int]]:
        """
        Get NFL week boundaries using the NFL schedule.

        Args:
            event_datetime: Event timestamp in epoch seconds
            game_id: The NFL game ID

        Returns:
            tuple: (week_start_epoch, week_end_epoch) or None if not found
        """
        if not game_id:
            self.logger.warning("Game ID required for NFL week boundary calculation")
            return None

        try:
            # Extract year from event_datetime
            event_dt = datetime.fromtimestamp(event_datetime)
            year = event_dt.year

            # Use NFLHelper to find the week boundary - pass request_id
            request_id = getattr(self.logger, "_keys", {}).get("request_id")
            nfl_helper = NFLHelper(request_id=request_id)
            week_boundary = nfl_helper.get_week_boundary_by_game_id(game_id, year)

            if week_boundary:
                self.logger.info(
                    f"Found NFL week boundary for game {game_id}: {week_boundary}"
                )
                return week_boundary
            else:
                self.logger.warning(
                    f"Could not find NFL week boundary for game {game_id}"
                )
                return None

        except Exception as e:
            self.logger.error(f"Error getting NFL week boundary: {e}")
            return None

    def _get_calendar_week_boundary(self, event_datetime: int) -> Tuple[int, int]:
        """
        Get calendar week boundaries (Sunday to Saturday).

        Args:
            event_datetime: Event timestamp in epoch seconds

        Returns:
            tuple: (week_start_epoch, week_end_epoch)
        """
        try:
            # Convert to datetime
            event_dt = datetime.fromtimestamp(event_datetime)

            # Find the Sunday of the week (start of week)
            days_since_sunday = event_dt.weekday() + 1  # Monday=0, so Sunday=6, adjust
            if days_since_sunday == 7:  # If it's Sunday
                days_since_sunday = 0

            week_start = event_dt - timedelta(days=days_since_sunday)
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

            # End of week is Saturday
            week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)

            week_start_epoch = int(week_start.timestamp())
            week_end_epoch = int(week_end.timestamp())

            self.logger.info(
                f"Calendar week boundary: {week_start_epoch} to {week_end_epoch}"
            )

            return week_start_epoch, week_end_epoch

        except Exception as e:
            self.logger.error(f"Error calculating calendar week boundary: {e}")
            # Fallback: use event_datetime as both start and end
            return event_datetime, event_datetime

    def get_nfl_current_week(self):
        espn_client = ESPNClient(request_id=self.request_id)

        now = datetime.now(timezone.utc)
        full_schedule = espn_client.get_nfl_schedule(now.year)
        schedule = full_schedule["leagues"][0]["calendar"]

        current_week_info = {
            "season_type_label": None,
            "season_type_value": None,
            "week_label": None,
            "week_value": None,
            "week_start": None,
            "week_end": None,
        }

        for season in schedule:
            for week in season.get("entries", []):
                start = isoparse(week["startDate"])
                end = isoparse(week["endDate"])
                if start <= now <= end:
                    current_week_info = {
                        "season_type_label": season["label"],
                        "season_type_value": season["value"],
                        "week_label": week["label"],
                        "week_value": week["value"],
                        "week_start": week["startDate"],
                        "week_end": week["endDate"],
                    }
        return current_week_info
