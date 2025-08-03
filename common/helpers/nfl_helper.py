from aws_lambda_powertools import Logger
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import os


class NFLHelper:
    """
    A class to handle NFL-related operations and calculations in the FortunasBet application.
    """

    def __init__(self, request_id: str = None):
        self.logger = Logger()
        if request_id:
            self.logger.append_keys(request_id=request_id)

    def get_nfl_season_info(self) -> Dict:
        """
        Returns NFL season structure with approximate dates.
        Note: These are approximate dates and may vary slightly year to year.
        """
        return {
            "preseason": {
                "season_type": 1,
                "weeks": 4,
                "start_month": 8,  # August
                "start_day": 1,
                "duration_weeks": 4,
            },
            "regular_season": {
                "season_type": 2,
                "weeks": 18,
                "start_month": 9,  # September
                "start_day": 8,  # Usually starts around first Thursday after Labor Day
                "duration_weeks": 18,
            },
            "playoffs": {
                "season_type": 3,
                "weeks": 4,
                "start_month": 1,  # January (next year)
                "start_day": 14,  # Usually starts mid-January
                "duration_weeks": 4,
            },
        }

    def get_week_dates_for_season(
        self, year: int, season_type: int, week: int
    ) -> tuple:
        """
        Calculate approximate start and end dates for a specific NFL week.

        Args:
            year: The NFL season year
            season_type: 1=preseason, 2=regular season, 3=playoffs
            week: Week number (1-indexed)

        Returns:
            tuple: (week_start_datetime, week_end_datetime)

        Raises:
            ValueError: If invalid season_type provided
        """
        season_info = self.get_nfl_season_info()

        if season_type == 1:  # Preseason
            season_data = season_info["preseason"]
            start_date = datetime(
                year, season_data["start_month"], season_data["start_day"]
            )
        elif season_type == 2:  # Regular season
            season_data = season_info["regular_season"]
            start_date = datetime(
                year, season_data["start_month"], season_data["start_day"]
            )
        elif season_type == 3:  # Playoffs
            season_data = season_info["playoffs"]
            # Playoffs are in the year AFTER the season year
            start_date = datetime(
                year + 1, season_data["start_month"], season_data["start_day"]
            )
        else:
            raise ValueError(f"Invalid season_type: {season_type}")

        # Calculate the start of the specific week (weeks are 1-indexed)
        week_start = start_date + timedelta(weeks=(week - 1))
        week_end = week_start + timedelta(days=6)  # Week runs Sunday to Saturday

        return week_start, week_end

    def find_nfl_weeks_in_range(self, start_epoch: int, end_epoch: int) -> List[Dict]:
        """
        Find all NFL weeks that fall within the given date range.

        Args:
            start_epoch: Start date in epoch timestamp
            end_epoch: End date in epoch timestamp

        Returns:
            List of dictionaries containing week information
        """
        start_date = datetime.fromtimestamp(start_epoch)
        end_date = datetime.fromtimestamp(end_epoch)

        self.logger.info(f"Finding NFL weeks between {start_date} and {end_date}")

        weeks_in_range = []
        season_info = self.get_nfl_season_info()

        # Check multiple years to cover the range
        start_year = start_date.year
        end_year = end_date.year

        # Extend the year range to handle edge cases
        for year in range(start_year - 1, end_year + 2):
            for season_name, season_data in season_info.items():
                season_type = season_data["season_type"]
                max_weeks = season_data["weeks"]

                for week in range(1, max_weeks + 1):
                    try:
                        week_start, week_end = self.get_week_dates_for_season(
                            year, season_type, week
                        )

                        # Check if this week overlaps with our date range
                        if week_start <= end_date and week_end >= start_date:
                            weeks_in_range.append(
                                {
                                    "year": year,
                                    "season_type": season_type,
                                    "season_name": season_name,
                                    "week": week,
                                    "week_start": week_start.isoformat(),
                                    "week_end": week_end.isoformat(),
                                    "week_start_epoch": int(week_start.timestamp()),
                                    "week_end_epoch": int(week_end.timestamp()),
                                }
                            )

                    except ValueError as e:
                        self.logger.warning(
                            f"Error calculating dates for year {year}, season {season_type}, week {week}: {e}"
                        )
                        continue

        # Sort by year, season_type, and week
        weeks_in_range.sort(key=lambda x: (x["year"], x["season_type"], x["week"]))

        return weeks_in_range

    def group_weeks_by_season(self, weeks: List[Dict]) -> List[Dict]:
        """
        Group weeks by season for easier consumption.

        Args:
            weeks: List of week dictionaries from find_nfl_weeks_in_range

        Returns:
            List of season summaries with their weeks
        """
        seasons_summary = {}
        for week_data in weeks:
            season_key = f"{week_data['year']}_{week_data['season_type']}"
            if season_key not in seasons_summary:
                seasons_summary[season_key] = {
                    "year": week_data["year"],
                    "season_type": week_data["season_type"],
                    "season_name": week_data["season_name"],
                    "weeks": [],
                }
            seasons_summary[season_key]["weeks"].append(week_data["week"])

        return list(seasons_summary.values())

    def validate_nfl_week(self, year: int, season_type: int, week: int) -> bool:
        """
        Validate if the given NFL week parameters are valid.

        Args:
            year: The NFL season year
            season_type: 1=preseason, 2=regular season, 3=playoffs
            week: Week number

        Returns:
            bool: True if valid, False otherwise
        """
        season_info = self.get_nfl_season_info()

        # Check if season_type is valid
        valid_season_types = [data["season_type"] for data in season_info.values()]
        if season_type not in valid_season_types:
            return False

        # Check if week is in valid range for the season type
        for season_data in season_info.values():
            if season_data["season_type"] == season_type:
                return 1 <= week <= season_data["weeks"]

        return False

    def get_current_nfl_week(self) -> Optional[Dict]:
        """
        Get the current NFL week based on today's date.

        Returns:
            Dictionary with current week info or None if not in season
        """
        current_epoch = int(datetime.now().timestamp())

        # Look for current week in a small range around today
        start_epoch = current_epoch - (7 * 24 * 60 * 60)  # One week before
        end_epoch = current_epoch + (7 * 24 * 60 * 60)  # One week after

        weeks = self.find_nfl_weeks_in_range(start_epoch, end_epoch)

        # Find the week that contains today
        for week in weeks:
            if week["week_start_epoch"] <= current_epoch <= week["week_end_epoch"]:
                return week

        return None
