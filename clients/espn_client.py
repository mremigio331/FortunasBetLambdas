from aws_lambda_powertools import Logger
from aws_lambda_powertools.metrics import Metrics, MetricUnit
import boto3
from botocore.exceptions import ClientError
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

    def get_nfl_week_ods(self, week: int, year: int, season_type: int = 2):
        """
        Returns over/under lines for all NFL games in the given week/year.
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
                    comp = event["competitions"][0]
                    odds = comp.get("odds", [])
                    competitors = comp.get("competitors", [])

                    # Extract team information
                    home_team = None
                    away_team = None

                    for competitor in competitors:
                        team_info = competitor.get("team", {})
                        team_data = {
                            "id": team_info.get("id"),
                            "name": team_info.get("displayName"),
                            "abbreviation": team_info.get("abbreviation"),
                            "logo": team_info.get("logo"),
                        }

                        if competitor.get("homeAway") == "home":
                            home_team = team_data
                        else:
                            away_team = team_data

                    game_data = {
                        "matchup": event["name"],
                        "date": event["date"],
                        "game_id": event.get("id"),
                        "teams": {"home": home_team, "away": away_team},
                        "spread": None,
                        "spreadDetails": None,
                        "favoredTeam": None,
                        "overUnder": None,
                        "homeTeamOdds": None,
                        "awayTeamOdds": None,
                    }

                    if odds and len(odds) > 0:
                        odds_data = odds[0]

                        # Get the spread (this is what you want for betting)
                        spread_value = odds_data.get("spread")
                        spread_details = odds_data.get("details")

                        if spread_value is not None:
                            game_data["spread"] = spread_value
                            game_data["spreadDetails"] = spread_details

                            # Determine favored team based on spread
                            # Negative spread means home team is favored
                            if spread_value < 0:
                                game_data["favoredTeam"] = "home"
                            elif spread_value > 0:
                                game_data["favoredTeam"] = "away"
                            else:
                                game_data["favoredTeam"] = "even"  # Pick 'em game

                        # Keep over/under for reference
                        game_data["overUnder"] = odds_data.get("overUnder")

                        # Extract home and away team odds
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
