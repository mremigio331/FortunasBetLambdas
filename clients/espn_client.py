from aws_lambda_powertools import Logger
from aws_lambda_powertools.metrics import Metrics, MetricUnit
import boto3
from botocore.exceptions import ClientError
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import json
import time
import datetime
import os
from common.constants.services import API_SERVICE
from common.constants.metrics import (
    API_METRICS_NAMESPACE,
    ESPN_API_CALL,
    ESPN_SUCCESS,
    ESPN_EXCEPTION,
    LEAGUE_DIMENSION,
    ESPN_LEAGUE_PATHS,
    ENDPOINT,
)


class ESPNClient:
    def __init__(self, request_id=None, stage=None):
        self.logger = Logger(service=API_SERVICE)
        if request_id:
            self.logger.append_keys(request_id=request_id)

        if stage:
            self.stage = stage
        else:
            self.stage = os.getenv("STAGE", "dev")
        self.metrics = Metrics(
            namespace=API_METRICS_NAMESPACE,
            service=API_SERVICE,
        )

    def _parse_event(self, event: dict) -> dict:
        """
        Parse an ESPN scoreboard event into a standardised game_data dict.
        Works for both NFL and MLB events since the scoreboard schema is
        identical across sports on the site API.

        Returns a game_data dict with teams, status, venue, and null odds
        placeholders ready to be filled by _attach_odds.
        """
        comp = event["competitions"][0]
        competitors = comp.get("competitors", [])

        home_team = None
        away_team = None

        for competitor in competitors:
            team_info = competitor.get("team", {})
            team_data = {
                "id": team_info.get("id"),
                "name": team_info.get("displayName"),
                "abbreviation": team_info.get("abbreviation"),
                "logo": team_info.get("logo"),
                "score": competitor.get("score"),
                "winner": competitor.get("winner", False),
                "records": competitor.get("records", []),
            }

            # Extract probable starting pitcher if available
            for probable in competitor.get("probables", []):
                if probable.get("name") == "probableStartingPitcher":
                    team_data["probableStartingPitcher"] = probable
                    break

            if competitor.get("homeAway") == "home":
                home_team = team_data
            else:
                away_team = team_data

        status = comp.get("status", {})
        game_status = {
            "type": status.get("type", {}),
            "period": status.get("period", 0),
            "displayClock": status.get("displayClock", ""),
            "completed": status.get("type", {}).get("completed", False),
            "state": status.get("type", {}).get("state", "pre"),
            "detail": status.get("type", {}).get("detail", ""),
            "shortDetail": status.get("type", {}).get("shortDetail", ""),
        }

        venue = comp.get("venue", {})
        venue_info = {
            "name": venue.get("fullName", ""),
            "city": venue.get("address", {}).get("city", ""),
            "state": venue.get("address", {}).get("state", ""),
            "indoor": venue.get("indoor", False),
        }

        return {
            "matchup": event["name"],
            "date": event["date"],
            "game_id": event.get("id"),
            "teams": {"home": home_team, "away": away_team},
            "status": game_status,
            "venue": venue_info,
            "spread": None,
            "spreadDetails": None,
            "favoredTeam": None,
            "overUnder": None,
            "homeTeamOdds": None,
            "awayTeamOdds": None,
        }

    def _attach_odds(self, game_data: dict, odds_data: dict) -> None:
        """
        Mutate *game_data* in-place by extracting spread, over/under, and
        moneyline values from an ESPN odds payload.

        *odds_data* is a single odds item (the first element from either
        ``comp["odds"]`` for inline scoreboard odds or
        ``odds_response["items"]`` for the separate odds endpoint).
        """
        spread_value = odds_data.get("spread")
        spread_details = odds_data.get("details")

        if spread_value is not None:
            game_data["spread"] = spread_value

            if spread_value < 0:
                game_data["favoredTeam"] = "home"
            elif spread_value > 0:
                game_data["favoredTeam"] = "away"
            else:
                game_data["favoredTeam"] = "even"

            # Build spreadDetails from the actual spread value and team abbreviations
            # ESPN's "details" field often contains moneyline info for MLB, not the spread
            favored = game_data["favoredTeam"]
            if favored == "home" and game_data.get("teams", {}).get("home"):
                abbr = game_data["teams"]["home"].get("abbreviation", "HOME")
                game_data["spreadDetails"] = f"{abbr} {spread_value}"
            elif favored == "away" and game_data.get("teams", {}).get("away"):
                abbr = game_data["teams"]["away"].get("abbreviation", "AWAY")
                game_data["spreadDetails"] = f"{abbr} {spread_value}"
            else:
                game_data["spreadDetails"] = spread_details

        game_data["overUnder"] = odds_data.get("overUnder")

        home_odds = odds_data.get("homeTeamOdds", {})
        away_odds = odds_data.get("awayTeamOdds", {})
        game_data["homeTeamOdds"] = {
            "moneyLine": home_odds.get("moneyLine"),
            "spreadOdds": home_odds.get("spreadOdds"),
        }
        game_data["awayTeamOdds"] = {
            "moneyLine": away_odds.get("moneyLine"),
            "spreadOdds": away_odds.get("spreadOdds"),
        }

    def get_nfl_week_odds(self, week: int, year: int, season_type: int = 2):
        """
        Returns Total lines for all NFL games in the given week/year.
        """
        self.metrics.add_dimension(
            name=ENDPOINT, value="/sports/football/nfl/scoreboard"
        )
        self.metrics.add_dimension(name=LEAGUE_DIMENSION, value="NFL")
        self.metrics.add_metric(name=ESPN_API_CALL, unit=MetricUnit.Count, value=1)

        try:
            url = (
                f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
                f"?seasontype={season_type}&week={week}&year={year}"
            )
            self.logger.info(f"Fetching NFL odds from: {url}")
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            results = []
            for event in data.get("events", []):
                try:
                    game_data = self._parse_event(event)

                    odds = event["competitions"][0].get("odds", [])
                    if odds and len(odds) > 0:
                        self._attach_odds(game_data, odds[0])

                    results.append(game_data)
                except Exception as e:
                    self.logger.warning(
                        f"Failed to parse odds for event {event.get('id')}: {e}"
                    )
                    continue

            self.metrics.add_metric(name=ESPN_SUCCESS, unit=MetricUnit.Count, value=1)
            self.metrics.flush_metrics()
            return results

        except requests.RequestException as e:
            self.metrics.add_metric(name=ESPN_EXCEPTION, unit=MetricUnit.Count, value=1)
            self.metrics.flush_metrics()
            self.logger.error(f"Request failed: {e}")
            return []

    def get_nfl_scoreboard(
        self, week: int = None, year: int = None, season_type: int = 2
    ):
        """
        Returns NFL scoreboard data for the given week/year.
        """
        self.metrics.add_dimension(
            name=ENDPOINT, value="/sports/football/nfl/scoreboard"
        )
        self.metrics.add_dimension(name=LEAGUE_DIMENSION, value="NFL")
        self.metrics.add_metric(name=ESPN_API_CALL, unit=MetricUnit.Count, value=1)

        try:
            url = (
                "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
            )
            params = {}
            if season_type:
                params["seasontype"] = season_type
            if week:
                params["week"] = week
            if year:
                params["year"] = year

            self.logger.info(
                f"Fetching NFL scoreboard from: {url} with params: {params}"
            )
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            self.metrics.add_metric(name=ESPN_SUCCESS, unit=MetricUnit.Count, value=1)
            self.metrics.flush_metrics()
            return data

        except requests.RequestException as e:
            self.metrics.add_metric(name=ESPN_EXCEPTION, unit=MetricUnit.Count, value=1)
            self.metrics.flush_metrics()
            self.logger.error(f"Request failed: {e}")
            return {}

    def get_mlb_scoreboard(self, date: str):
        """
        Returns MLB scoreboard data for a specific date.

        Args:
            date: Date string in YYYYMMDD format (e.g., '20250920').

        Returns:
            dict: MLB scoreboard data including events, teams, and scores
        """
        self.metrics.add_dimension(
            name=ENDPOINT, value="/sports/baseball/mlb/scoreboard"
        )
        self.metrics.add_dimension(name=LEAGUE_DIMENSION, value="MLB")
        self.metrics.add_metric(name=ESPN_API_CALL, unit=MetricUnit.Count, value=1)

        try:
            url = (
                "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
            )
            params = {"dates": date}

            self.logger.info(
                f"Fetching MLB scoreboard from: {url} with params: {params}"
            )
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            self.metrics.add_metric(name=ESPN_SUCCESS, unit=MetricUnit.Count, value=1)
            self.metrics.flush_metrics()
            return data

        except requests.RequestException as e:
            self.metrics.add_metric(name=ESPN_EXCEPTION, unit=MetricUnit.Count, value=1)
            self.metrics.flush_metrics()
            self.logger.error(f"Request failed: {e}")
            return {}

    def get_mlb_game_odds(self, event_id: str):
        """
        Returns odds data for a specific MLB game event.

        Args:
            event_id: The ESPN event ID for the MLB game.

        Returns:
            dict: Odds data including spreads, over/under, and moneyline values.
        """
        self.metrics.add_dimension(
            name=ENDPOINT,
            value=f"/sports/baseball/mlb/events/{event_id}/odds",
        )
        self.metrics.add_dimension(name=LEAGUE_DIMENSION, value="MLB")
        self.metrics.add_metric(name=ESPN_API_CALL, unit=MetricUnit.Count, value=1)

        try:
            url = (
                f"https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb"
                f"/events/{event_id}/competitions/{event_id}/odds"
            )
            params = {"lang": "en", "region": "us"}

            self.logger.info(
                f"Fetching MLB game odds from: {url} with params: {params}"
            )
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            self.metrics.add_metric(name=ESPN_SUCCESS, unit=MetricUnit.Count, value=1)
            self.metrics.flush_metrics()
            return data

        except requests.RequestException as e:
            self.metrics.add_metric(name=ESPN_EXCEPTION, unit=MetricUnit.Count, value=1)
            self.metrics.flush_metrics()
            self.logger.error(f"Failed to fetch MLB odds for event {event_id}: {e}")
            return {}

    def get_mlb_scoreboard_with_odds(self, date: str):
        """
        Fetches MLB scoreboard for a date, then fetches odds for each game
        in parallel. Returns a list of game_data dicts matching the format
        used by get_nfl_week_odds.

        Args:
            date: Date string in YYYYMMDD format (e.g., '20250920').

        Returns:
            list[dict]: List of game data dicts with odds attached.
        """
        scoreboard = self.get_mlb_scoreboard(date)
        events = scoreboard.get("events", [])
        if not events:
            return []

        # Fetch odds for all games in parallel
        odds_map = {}

        def fetch_odds(event_id):
            return event_id, self.get_mlb_game_odds(event_id)

        with ThreadPoolExecutor(max_workers=min(len(events), 10)) as executor:
            futures = {
                executor.submit(fetch_odds, event["id"]): event["id"]
                for event in events
                if event.get("id")
            }
            for future in as_completed(futures):
                try:
                    event_id, odds_data = future.result()
                    odds_map[event_id] = odds_data
                except Exception as e:
                    event_id = futures[future]
                    self.logger.warning(
                        f"Failed to fetch odds for MLB event {event_id}: {e}"
                    )

        results = []
        for event in events:
            try:
                game_data = self._parse_event(event)

                # Try odds from the parallel fetch first (core API)
                event_odds = odds_map.get(event.get("id"), {})
                odds_items = event_odds.get("items", [])
                if odds_items:
                    self._attach_odds(game_data, odds_items[0])
                else:
                    # Fall back to inline odds from the scoreboard response
                    inline_odds = event["competitions"][0].get("odds", [])
                    if inline_odds:
                        self._attach_odds(game_data, inline_odds[0])

                results.append(game_data)
            except Exception as e:
                self.logger.warning(f"Failed to parse MLB event {event.get('id')}: {e}")
                continue

        return results

    def get_nfl_schedule(self, year: int):
        """
        Returns the complete NFL schedule for a given year.
        This includes all games with their dates and week assignments.

        Args:
            year: The NFL season year

        Returns:
            dict: Complete NFL schedule data
        """
        self.metrics.add_dimension(
            name=ENDPOINT, value="/sports/football/nfl/scoreboard"
        )
        self.metrics.add_dimension(name=LEAGUE_DIMENSION, value="NFL")
        self.metrics.add_metric(name=ESPN_API_CALL, unit=MetricUnit.Count, value=1)

        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={year}"
            self.logger.info(f"Fetching NFL schedule from: {url}")
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()

            self.metrics.add_metric(name=ESPN_SUCCESS, unit=MetricUnit.Count, value=1)
            self.metrics.flush_metrics()
            return data

        except requests.RequestException as e:
            self.metrics.add_metric(name=ESPN_EXCEPTION, unit=MetricUnit.Count, value=1)
            self.metrics.flush_metrics()
            self.logger.error(f"Request failed: {e}")
            return {}

    def get_event(self, sport: str, league: str, event_id: str):
        """
        Returns event data for a specific event by ID.

        Args:
            sport: The sport (e.g., 'football')
            league: The league (e.g., 'nfl')
            event_id: The ESPN event ID

        Returns:
            dict: Event data including status information and pickcenter odds
        """
        self.metrics.add_dimension(
            name=ENDPOINT, value=f"/sports/{sport}/{league}/summary"
        )
        self.metrics.add_dimension(name=LEAGUE_DIMENSION, value=league.upper())
        self.metrics.add_metric(name=ESPN_API_CALL, unit=MetricUnit.Count, value=1)

        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary?event={event_id}"

            self.logger.info(f"Fetching event data from: {url}")
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Log the full response to see the structure
            self.logger.info(f"ESPN API Response structure: {list(data.keys())}")

            # Extract relevant event information
            event_data = {}

            # Extract pickcenter odds if present
            pickcenter = data.get("pickcenter", [])
            event_data["pickcenter"] = pickcenter

            # Check different possible structures in the ESPN response
            if "header" in data:
                header = data["header"]
                self.logger.info(f"Header structure: {list(header.keys())}")

                # Look for competition data in header
                if "competitions" in header and len(header["competitions"]) > 0:
                    competition = header["competitions"][0]
                    self.logger.info(
                        f"Competition structure: {list(competition.keys())}"
                    )

                    # Extract status information
                    status = competition.get("status", {})
                    status_type = status.get("type", {})

                    self.logger.info(f"Status structure: {status}")

                    # Extract competitor information (teams and scores)
                    competitors = competition.get("competitors", [])
                    teams_data = []

                    for competitor in competitors:
                        team_info = competitor.get("team", {})
                        team_data = {
                            "id": team_info.get("id"),
                            "name": team_info.get("displayName", ""),
                            "abbreviation": team_info.get("abbreviation", ""),
                            "homeAway": competitor.get("homeAway", ""),
                            "score": competitor.get("score", "0"),
                            "winner": competitor.get("winner", False),
                        }
                        teams_data.append(team_data)

                    self.logger.info(f"Extracted {len(teams_data)} teams with scores")

                    event_data.update(
                        {
                            "id": competition.get("id"),
                            "date": competition.get("date"),
                            "status": {
                                "name": status_type.get("name", ""),
                                "state": status_type.get("state", ""),
                                "completed": status_type.get("completed", False),
                                "detail": status_type.get("detail", ""),
                                "shortDetail": status_type.get("shortDetail", ""),
                                "home_score": teams_data[0]["score"],
                                "away_score": teams_data[1]["score"],
                            },
                            "startDate": competition.get("startDate"),
                            "competitors": teams_data,
                        }
                    )

                elif "competition" in header:
                    # Alternative structure
                    competition = header["competition"]
                    self.logger.info(
                        f"Alternative competition structure: {list(competition.keys())}"
                    )

                    # Extract status information
                    status = competition.get("status", {})
                    status_type = status.get("type", {})

                    self.logger.info(f"Status structure: {status}")

                    # Extract competitor information (teams and scores)
                    competitors = competition.get("competitors", [])
                    teams_data = []

                    for competitor in competitors:
                        team_info = competitor.get("team", {})
                        team_data = {
                            "id": team_info.get("id"),
                            "name": team_info.get("displayName", ""),
                            "abbreviation": team_info.get("abbreviation", ""),
                            "homeAway": competitor.get("homeAway", ""),
                            "score": competitor.get("score", "0"),
                            "winner": competitor.get("winner", False),
                        }
                        teams_data.append(team_data)

                    self.logger.info(f"Extracted {len(teams_data)} teams with scores")

                    event_data.update(
                        {
                            "id": competition.get("id"),
                            "date": competition.get("date"),
                            "status": {
                                "name": status_type.get("name", ""),
                                "state": status_type.get("state", ""),
                                "completed": status_type.get("completed", False),
                                "detail": status_type.get("detail", ""),
                                "shortDetail": status_type.get("shortDetail", ""),
                                "home_score": teams_data[0]["score"],
                                "away_score": teams_data[1]["score"],
                            },
                            "startDate": competition.get("startDate"),
                            "competitors": teams_data,
                        }
                    )
                else:
                    self.logger.warning(
                        f"No competition data found in header. Available keys: {list(header.keys())}"
                    )
            else:
                self.logger.warning(
                    f"No header found in ESPN response. Available keys: {list(data.keys())}"
                )

            if not event_data:
                self.logger.warning(
                    f"Could not extract event data from ESPN response. Full response logged."
                )
                # Log a subset of the response for debugging (first few keys)
                debug_data = {k: v for k, v in list(data.items())[:5]}
                self.logger.info(f"ESPN response sample: {debug_data}")

            self.metrics.add_metric(name=ESPN_SUCCESS, unit=MetricUnit.Count, value=1)
            self.metrics.flush_metrics()
            return event_data

        except requests.RequestException as e:
            self.metrics.add_metric(name=ESPN_EXCEPTION, unit=MetricUnit.Count, value=1)
            self.metrics.flush_metrics()
            self.logger.error(f"Request failed: {e}")
            return {}
