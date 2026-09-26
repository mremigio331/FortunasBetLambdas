from aws_lambda_powertools import Logger
from datetime import datetime, timedelta
from typing import Optional, Tuple
from common.helpers.nfl_helper import NFLHelper
from common.helpers.mlb_helper import MLBHelper
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

        # MLB uses Monday-Sunday EST week boundaries
        if sport_lower == "baseball" and league_lower == "mlb":
            return self._get_mlb_week_boundary(event_datetime)

        # Other sports use calendar weeks
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

    def _get_mlb_week_boundary(self, event_datetime: int) -> Tuple[int, int]:
        """
        Get MLB week boundaries using MLBHelper (Monday-Sunday EST).

        Args:
            event_datetime: Event timestamp in epoch seconds

        Returns:
            tuple: (week_start_epoch, week_end_epoch)
        """
        mlb_helper = MLBHelper(request_id=self.request_id)
        return mlb_helper.get_mlb_week_boundary(event_datetime)

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

    def get_nfl_season_year(self, now: datetime) -> int:
        """
        Derive the NFL Season_Year for a given moment.

        The NFL season spans two calendar years: it starts in the late summer and
        finishes with the playoffs in the following January/February. ESPN keys
        the whole season on the year it started in, so a January playoff date
        belongs to the prior calendar year's schedule.

        Args:
            now: The moment to derive the Season_Year for. Naive and
                timezone-aware datetimes are both accepted; only the calendar
                month and year of the value provided are used.

        Returns:
            int: The current calendar year for August-December, or the prior
                calendar year for January-July.
        """
        if now.month >= 8:
            return now.year
        return now.year - 1

    @staticmethod
    def _ensure_aware(moment: datetime) -> datetime:
        """
        Return a timezone-aware version of a datetime, assuming UTC when naive.

        Boundary comparisons must never raise "can't compare offset-naive and
        offset-aware datetimes", so any naive value that reaches the comparison
        is treated as UTC.

        Args:
            moment: A naive or timezone-aware datetime.

        Returns:
            datetime: The same instant, guaranteed to carry a tzinfo.
        """
        if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
            return moment.replace(tzinfo=timezone.utc)
        return moment

    def _parse_espn_datetime(self, value) -> Optional[datetime]:
        """
        Parse an ESPN ISO 8601 timestamp into a timezone-aware datetime.

        ESPN calendar entries carry a UTC offset (e.g. `2025-01-11T05:00Z`), so
        `isoparse` yields an aware value. Anything missing an offset is treated
        as UTC by `_ensure_aware`.

        Args:
            value: The raw `startDate`/`endDate` value from a calendar entry.

        Returns:
            Optional[datetime]: The parsed aware datetime, or None if the value
                is missing, not a string, or not parseable.
        """
        if not isinstance(value, str) or not value.strip():
            return None

        try:
            return self._ensure_aware(isoparse(value))
        except (ValueError, OverflowError) as e:
            self.logger.warning(
                f"Could not parse ESPN schedule datetime {value!r}: {e}"
            )
            return None

    def _extract_schedule_calendar(self, full_schedule) -> list:
        """
        Pull the season calendar out of an ESPN schedule payload.

        The payload nests the calendar at `leagues[0].calendar`. A failed or
        empty ESPN response (`{}`) - or one whose shape has drifted - yields an
        empty calendar instead of raising `KeyError`/`IndexError`, letting the
        caller fall through to the adjacent-year retry and off-season handling.

        Args:
            full_schedule: The raw payload from `ESPNClient.get_nfl_schedule`.

        Returns:
            list: The season calendar, or an empty list when it is absent.
        """
        if not isinstance(full_schedule, dict):
            self.logger.warning(
                "NFL schedule payload was not a mapping; using an empty calendar"
            )
            return []

        leagues = full_schedule.get("leagues")
        if not isinstance(leagues, list) or not leagues:
            self.logger.warning(
                "NFL schedule payload is missing 'leagues'; using an empty calendar"
            )
            return []

        league = leagues[0]
        if not isinstance(league, dict):
            self.logger.warning(
                "NFL schedule 'leagues[0]' was not a mapping; using an empty calendar"
            )
            return []

        calendar = league.get("calendar")
        if not isinstance(calendar, list):
            self.logger.warning(
                "NFL schedule payload is missing 'calendar'; using an empty calendar"
            )
            return []

        return calendar

    def _find_containing_week(self, calendar, now: datetime) -> Optional[dict]:
        """
        Find the calendar week whose boundaries contain a given moment.

        Both boundaries and `now` are compared as timezone-aware datetimes, so
        the result is the same regardless of the server's local time zone
        (Requirements 5.6, 6.6). Aware datetimes compare on the absolute
        instant, so no explicit ET conversion is needed - an ET boundary and a
        UTC `now` describe the same timeline.

        Malformed calendar shapes are skipped rather than raising: non-mapping
        seasons or entries, missing `entries`, and unparseable dates are all
        ignored.

        Args:
            calendar: The season calendar from `_extract_schedule_calendar`.
                Each season is expected to hold week entries under `entries`.
            now: The moment to locate. Naive values are assumed to be UTC.

        Returns:
            Optional[dict]: `{"season": <season>, "week": <entry>}` for the
                first entry whose start <= now <= end, or None if the moment
                falls outside every entry.
        """
        now = self._ensure_aware(now)

        if not isinstance(calendar, list):
            return None

        for season in calendar:
            if not isinstance(season, dict):
                continue

            entries = season.get("entries")
            if not isinstance(entries, list):
                continue

            for week in entries:
                if not isinstance(week, dict):
                    continue

                start = self._parse_espn_datetime(week.get("startDate"))
                end = self._parse_espn_datetime(week.get("endDate"))
                if start is None or end is None:
                    continue

                if start <= now <= end:
                    return {"season": season, "week": week}

        return None

    def _coerce_int(self, value) -> Optional[int]:
        """
        Normalize an ESPN season type or week value to an int.

        ESPN returns these as strings (`"2"`, `"12"`), while every consumer -
        the response model and the frontend selection controls - works in
        numbers. Normalizing here keeps strict-equality option matching from
        silently failing downstream (Requirement 6.1).

        Args:
            value: The raw `value` from a calendar season or week entry.

        Returns:
            Optional[int]: The numeric equivalent, or None when the value is
                missing or not numeric.
        """
        if value is None or isinstance(value, bool):
            return None

        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return int(value)

        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                try:
                    return int(float(value.strip()))
                except ValueError:
                    self.logger.warning(
                        f"Could not normalize ESPN numeric value {value!r} to an int"
                    )
                    return None

        self.logger.warning(
            f"Unexpected type for ESPN numeric value {value!r}; treating as None"
        )
        return None

    def _to_iso(self, value) -> Optional[str]:
        """
        Normalize an ESPN boundary timestamp to a canonical ISO 8601 string.

        ESPN's own format (`2024-09-05T07:00Z`) omits seconds and occasionally
        the offset. Reparsing and re-emitting guarantees a full ISO 8601 value
        that always carries an offset, which is what the response contract
        promises.

        Args:
            value: The raw `startDate`/`endDate` from a calendar entry.

        Returns:
            Optional[str]: The canonical ISO 8601 timestamp, the original
                string if it could not be parsed, or None when absent.
        """
        parsed = self._parse_espn_datetime(value)
        if parsed is None:
            return value if isinstance(value, str) and value.strip() else None
        return parsed.isoformat()

    def _off_season_week(self, season_year: Optional[int]) -> dict:
        """
        Build the off-season payload: an explicit indicator, not bare nulls.

        `season_year` stays populated so callers still know which season the
        System believes it is between (Requirements 5.4, 5.5).

        Args:
            season_year: The Season_Year that was searched.

        Returns:
            dict: The normalized off-season payload.
        """
        return {
            "is_off_season": True,
            "season_year": season_year,
            "season_type_label": None,
            "season_type_value": None,
            "week_label": None,
            "week_value": None,
            "week_start": None,
            "week_end": None,
        }

    def _build_current_week(self, season_year: int, found: dict) -> dict:
        """
        Build the in-season payload from a matched calendar entry.

        Args:
            season_year: The Season_Year whose schedule produced the match.
            found: The `{"season", "week"}` result from `_find_containing_week`.

        Returns:
            dict: The normalized current-week payload with numeric season type
                and week values and ISO 8601 boundaries.
        """
        season = found.get("season") or {}
        week = found.get("week") or {}

        return {
            "is_off_season": False,
            "season_year": season_year,
            "season_type_label": season.get("label"),
            "season_type_value": self._coerce_int(season.get("value")),
            "week_label": week.get("label"),
            "week_value": self._coerce_int(week.get("value")),
            "week_start": self._to_iso(week.get("startDate")),
            "week_end": self._to_iso(week.get("endDate")),
        }

    def get_nfl_current_week(self) -> dict:
        """
        Resolve the current NFL week from the ESPN schedule calendar.

        Uses the NFL Season_Year - not the calendar year - to choose which
        schedule to request, so a January/February playoff moment asks for the
        prior calendar year (Requirements 5.1, 5.2). If no week in that
        schedule contains the present moment, the adjacent Season_Years are
        tried before declaring off-season, which covers season-boundary drift
        and ESPN publishing the containing week under the neighbouring year
        (Requirement 5.3).

        Boundary comparisons are timezone-aware, so the result does not depend
        on the server's local zone (Requirement 5.6).

        Returns:
            dict: A normalized payload shaped like the `CurrentNflWeek`
                response model:
                  {
                    "is_off_season": bool,
                    "season_year": int | None,
                    "season_type_label": str | None,
                    "season_type_value": int | None,   # numeric
                    "week_label": str | None,
                    "week_value": int | None,          # numeric
                    "week_start": str | None,          # ISO 8601
                    "week_end": str | None,            # ISO 8601
                  }
                Off-season returns `is_off_season: True` with null week fields
                and the Season_Year still populated (Requirements 5.4, 5.5).
        """
        espn_client = ESPNClient(request_id=self.request_id)

        now = datetime.now(timezone.utc)
        season_year = self.get_nfl_season_year(now)

        # Fast path: the plain scoreboard already resolves the current season
        # and week and carries the full calendar, so a single lightweight call
        # answers the common in-season case without fetching a full-year
        # schedule (~850KB) for up to three candidate years.
        try:
            calendar = self._extract_schedule_calendar(espn_client.get_nfl_calendar())
            found = self._find_containing_week(calendar, now)
            if found is not None:
                current_week_info = self._build_current_week(season_year, found)
                self.logger.info(
                    "Resolved current NFL week via fast calendar path: "
                    f"{current_week_info['season_type_label']} "
                    f"{current_week_info['week_label']}"
                )
                return current_week_info
            self.logger.info(
                "Fast calendar path did not contain the present moment; "
                "falling back to full-schedule resolution"
            )
        except Exception as e:
            self.logger.warning(
                f"Fast calendar path failed ({e}); falling back to "
                "full-schedule resolution"
            )

        # Preferred Season_Year first, then its neighbours (Requirement 5.3).
        candidate_years = [season_year, season_year - 1, season_year + 1]

        for candidate_year in candidate_years:
            calendar = self._extract_schedule_calendar(
                espn_client.get_nfl_schedule(candidate_year)
            )
            found = self._find_containing_week(calendar, now)

            if found is not None:
                current_week_info = self._build_current_week(candidate_year, found)
                self.logger.info(
                    f"Resolved current NFL week from season {candidate_year}: "
                    f"{current_week_info['season_type_label']} "
                    f"{current_week_info['week_label']}"
                )
                return current_week_info

            self.logger.info(
                f"No NFL week contains {now.isoformat()} in season {candidate_year}"
            )

        self.logger.info(
            f"No NFL week contains {now.isoformat()} in seasons {candidate_years}; "
            "reporting off-season"
        )
        return self._off_season_week(season_year)
