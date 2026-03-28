from aws_lambda_powertools import Logger
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")


class MLBHelper:
    """
    Handles MLB-specific week boundary calculations.
    MLB weeks run Monday 00:00:00 EST through Sunday 23:59:59 EST.
    """

    def __init__(self, request_id: str):
        self.logger = Logger()
        self.logger.append_keys(request_id=request_id)

    def get_mlb_week_boundary(self, event_datetime: int) -> Tuple[int, int]:
        """
        Calculate MLB week boundary: Monday 00:00:00 ET to Sunday 23:59:59 ET.

        Constructs boundary datetimes explicitly with ZoneInfo("America/New_York")
        so that DST transitions (spring-forward / fall-back) are resolved correctly.
        Using timedelta + replace() can produce wrong offsets when the arithmetic
        crosses a DST boundary; building the datetime from (year, month, day) avoids this.

        Args:
            event_datetime: Epoch timestamp of the event

        Returns:
            (week_start_epoch, week_end_epoch)
        """
        event_dt = datetime.fromtimestamp(event_datetime, tz=EST)

        # Monday = 0 in Python's weekday()
        days_since_monday = event_dt.weekday()
        monday_date = (event_dt - timedelta(days=days_since_monday)).date()
        sunday_date = monday_date + timedelta(days=6)

        # Build wall-clock times explicitly so ZoneInfo picks the right UTC offset
        week_start = datetime(
            monday_date.year,
            monday_date.month,
            monday_date.day,
            0,
            0,
            0,
            tzinfo=EST,
        )
        week_end = datetime(
            sunday_date.year,
            sunday_date.month,
            sunday_date.day,
            23,
            59,
            59,
            tzinfo=EST,
        )

        self.logger.info(
            f"MLB week boundary for {event_dt.isoformat()}: "
            f"{week_start.isoformat()} to {week_end.isoformat()}"
        )

        return int(week_start.timestamp()), int(week_end.timestamp())

    def get_mlb_weeks_in_range(self, start_epoch: int, end_epoch: int) -> List[Dict]:
        """
        Generate all MLB weeks (Mon-Sun EST) within a date range.

        Args:
            start_epoch: Start date in epoch timestamp
            end_epoch: End date in epoch timestamp

        Returns:
            List of dicts with week number, start/end epochs, labels, and ISO dates
        """
        weeks = []
        current = datetime.fromtimestamp(start_epoch, tz=EST)
        end = datetime.fromtimestamp(end_epoch, tz=EST)

        # Align to Monday
        days_since_monday = current.weekday()
        monday_date = (current - timedelta(days=days_since_monday)).date()

        week_num = 1
        while True:
            current_monday = monday_date + timedelta(weeks=week_num - 1)
            current_sunday = current_monday + timedelta(days=6)

            # Build wall-clock times explicitly for correct DST handling
            week_start_dt = datetime(
                current_monday.year,
                current_monday.month,
                current_monday.day,
                0,
                0,
                0,
                tzinfo=EST,
            )
            week_end_dt = datetime(
                current_sunday.year,
                current_sunday.month,
                current_sunday.day,
                23,
                59,
                59,
                tzinfo=EST,
            )

            if week_start_dt >= end:
                break

            weeks.append(
                {
                    "week": week_num,
                    "start": int(week_start_dt.timestamp()),
                    "end": int(week_end_dt.timestamp()),
                    "label": f"Week {week_num}",
                    "start_date": week_start_dt.isoformat(),
                    "end_date": week_end_dt.isoformat(),
                }
            )
            week_num += 1

        self.logger.info(
            f"Generated {len(weeks)} MLB weeks between "
            f"{datetime.fromtimestamp(start_epoch, tz=EST).isoformat()} and "
            f"{datetime.fromtimestamp(end_epoch, tz=EST).isoformat()}"
        )

        return weeks
