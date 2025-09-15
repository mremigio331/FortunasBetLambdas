from aws_lambda_powertools import Logger
import boto3
from botocore.exceptions import ClientError
from common.models.bet import BetModel
from datetime import datetime
from exceptions.bet_exceptions import (
    DuplicateBetException,
    BetNotFound,
    InvalidGameStatusException,
    DuplicateGameException,
)
import os
from typing import List, Optional, Any, Dict
from decimal import Decimal
from clients.espn_client import ESPNClient
import random
import uuid


class BetHelper:
    """
    A class to interact with DynamoDB for bet operations in the FortunasBet application.
    """

    def __init__(self, request_id: str, table_name: str = None):
        self.dynamodb = boto3.resource("dynamodb", region_name="us-west-2")

        if table_name:
            self.table = self.dynamodb.Table(table_name)
        else:
            table_name = os.getenv("TABLE_NAME")
            self.table = self.dynamodb.Table(table_name)

        self.logger = Logger()
        self.request_id = request_id
        self.logger.append_keys(request_id=request_id)

    def _convert_floats_to_decimals(self, obj: Any) -> Any:
        """
        Recursively convert float values to Decimal values for DynamoDB compatibility.
        """
        if isinstance(obj, float):
            return Decimal(str(obj))
        elif isinstance(obj, dict):
            return {
                key: self._convert_floats_to_decimals(value)
                for key, value in obj.items()
            }
        elif isinstance(obj, list):
            return [self._convert_floats_to_decimals(item) for item in obj]
        else:
            return obj

    def _convert_decimals_to_floats(self, obj: Any) -> Any:
        """
        Recursively convert Decimal values back to float values for JSON serialization.
        """
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, dict):
            return {
                key: self._convert_decimals_to_floats(value)
                for key, value in obj.items()
            }
        elif isinstance(obj, list):
            return [self._convert_decimals_to_floats(item) for item in obj]
        else:
            return obj

    def create_bet(self, bet: BetModel) -> dict:
        """
        Create a new bet in DynamoDB.
        PK: ROOM#{room_id}
        SK: POINT#{points_wagered}#USER#{user_id}#EVENT#{event_datetime}

        Validates that the bet doesn't already exist and checks week boundary constraints.
        """
        # First check if exact bet already exists (same event)
        existing_bet = self.get_bet(
            bet.room_id, bet.points_wagered, bet.user_id, bet.event_datetime
        )
        if existing_bet:
            raise DuplicateBetException(bet.room_id, bet.user_id, bet.points_wagered)

        # Then validate week boundary constraints
        self.validate_week_boundary_bet(
            room_id=bet.room_id,
            user_id=bet.user_id,
            points_wagered=bet.points_wagered,
            sport=bet.sport,
            league=bet.league,
            event_datetime=bet.event_datetime,
            game_id=bet.game_id,
        )

        item = bet.dict()
        item["PK"] = f"ROOM#{bet.room_id}"
        item["SK"] = (
            f"POINT#{bet.points_wagered}#USER#{bet.user_id}#EVENT#{bet.event_datetime}"
        )

        # Convert float values to Decimal for DynamoDB compatibility
        item = self._convert_floats_to_decimals(item)

        # Check if the user has already placed a bet on the same game ID
        user_game_ids = self.get_user_game_ids_for_room(bet.room_id, bet.user_id)
        if bet.game_id in user_game_ids:
            raise DuplicateGameException(bet.game_id)

        try:
            self.table.put_item(Item=item)
            self.logger.info(
                f"Created {bet.points_wagered}-point bet for user {bet.user_id} in room {bet.room_id}: {item}"
            )

            return item
        except ClientError as e:
            self.logger.error(
                f"Error creating bet for user {bet.user_id} in room {bet.room_id}: {e}"
            )
            raise

    def get_bet(
        self,
        room_id: str,
        points_wagered: int,
        user_id: str,
        event_datetime: int,
    ) -> Optional[dict]:
        """
        Fetch a specific bet from DynamoDB using the exact SK.
        """
        response = self.table.get_item(
            Key={
                "PK": f"ROOM#{room_id}",
                "SK": f"POINT#{points_wagered}#USER#{user_id}#EVENT#{event_datetime}",
            }
        )

        item = response.get("Item")
        if item:
            # Convert Decimal values back to float for JSON serialization
            serializable_item = self._convert_decimals_to_floats(item)

            # Check and grade the bet if needed
            graded_bet = self.check_and_grade_bet(serializable_item)
            if graded_bet:
                serializable_item = graded_bet

            # Enhance with current ESPN game data
            enhanced_item = self._enhance_bet_with_game_data(serializable_item)

            self.logger.info(
                f"Retrieved {points_wagered}-point bet for user {user_id} in room {room_id} for event {event_datetime}"
            )
            return enhanced_item

        self.logger.info(
            f"No {points_wagered}-point bet found for user {user_id} in room {room_id} for event {event_datetime}"
        )
        return None

    def get_all_bets_for_room(self, room_id: str) -> List[dict]:
        """
        Fetch all bets for a specific room, ordered by point value then user.
        """
        try:
            response = self.table.query(
                KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
                ExpressionAttributeValues={
                    ":pk": f"ROOM#{room_id}",
                    ":sk_prefix": "POINT#",
                },
            )
            items = response.get("Items", [])

            # Convert Decimal values back to float for JSON serialization
            serializable_items = [
                self._convert_decimals_to_floats(item) for item in items
            ]

            # Check and grade each bet if needed
            graded_items = []
            for item in serializable_items:
                graded_bet = self.check_and_grade_bet(item)
                if graded_bet:
                    enhanced_bet = self._enhance_bet_with_game_data(graded_bet)
                    graded_items.append(enhanced_bet)
                else:
                    enhanced_bet = self._enhance_bet_with_game_data(item)
                    graded_items.append(enhanced_bet)

            self.logger.info(f"Retrieved {len(graded_items)} bets for room {room_id}")
            return graded_items
        except ClientError as e:
            self.logger.error(f"Error fetching bets for room {room_id}: {e}")
            raise

    def get_bets_by_point_value(self, room_id: str, points_wagered: int) -> List[dict]:
        """
        Fetch all bets for a specific point value in a room.
        """
        try:
            response = self.table.query(
                KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
                ExpressionAttributeValues={
                    ":pk": f"ROOM#{room_id}",
                    ":sk_prefix": f"POINT#{points_wagered}#",
                },
            )
            items = response.get("Items", [])

            # Convert Decimal values back to float for JSON serialization
            serializable_items = [
                self._convert_decimals_to_floats(item) for item in items
            ]

            # Check and grade each bet if needed
            graded_items = []
            for item in serializable_items:
                graded_bet = self.check_and_grade_bet(item)
                if graded_bet:
                    enhanced_bet = self._enhance_bet_with_game_data(graded_bet)
                    graded_items.append(enhanced_bet)
                else:
                    enhanced_bet = self._enhance_bet_with_game_data(item)
                    graded_items.append(enhanced_bet)

            self.logger.info(
                f"Retrieved {len(graded_items)} {points_wagered}-point bets for room {room_id}"
            )
            return graded_items
        except ClientError as e:
            self.logger.error(
                f"Error fetching {points_wagered}-point bets for room {room_id}: {e}"
            )
            raise

    def get_user_bets_for_room(self, room_id: str, user_id: str) -> List[dict]:
        """
        Get all bets for a specific user in a room (1, 2, and 3 point bets).
        """
        try:
            response = self.table.query(
                KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
                ExpressionAttributeValues={
                    ":pk": f"ROOM#{room_id}",
                    ":sk_prefix": "POINT#",
                },
            )
            items = response.get("Items", [])

            # Convert Decimal values back to float for JSON serialization
            serializable_items = [
                self._convert_decimals_to_floats(item) for item in items
            ]

            # Filter for user_id in SK
            user_id_str = f"USER#{user_id}"
            filtered_items = [
                item for item in serializable_items if user_id_str in item.get("SK", "")
            ]

            # Check and grade each bet if needed
            graded_items = []
            for item in filtered_items:
                graded_bet = self.check_and_grade_bet(item)
                if graded_bet:
                    enhanced_bet = self._enhance_bet_with_game_data(graded_bet)
                    graded_items.append(enhanced_bet)
                else:
                    enhanced_bet = self._enhance_bet_with_game_data(item)
                    graded_items.append(enhanced_bet)

            self.logger.info(
                f"Retrieved {len(graded_items)} bets for user {user_id} in room {room_id}"
            )
            return graded_items
        except ClientError as e:
            self.logger.error(
                f"Error fetching bets for user {user_id} in room {room_id}: {e}"
            )
            raise

    def get_user_game_ids_for_room(self, room_id: str, user_id: str) -> List[str]:
        """
        Get all game IDs a user has placed bets on in a specific room.

        Args:
            room_id: The room ID.
            user_id: The user ID.

        Returns:
            List of game IDs the user has placed bets on.
        """
        try:
            response = self.table.query(
                KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
                ExpressionAttributeValues={
                    ":pk": f"ROOM#{room_id}",
                    ":sk_prefix": f"POINT#",
                },
            )
            items = response.get("Items", [])

            # Filter items for the specific user and extract game IDs
            user_id_str = f"USER#{user_id}"
            game_ids = [
                item["game_id"]
                for item in items
                if user_id_str in item.get("SK", "") and "game_id" in item
            ]

            self.logger.info(
                f"Retrieved {len(game_ids)} game IDs for user {user_id} in room {room_id}"
            )
            return game_ids
        except ClientError as e:
            self.logger.error(
                f"Error fetching game IDs for user {user_id} in room {room_id}: {e}"
            )
            raise

    def validate_week_boundary_bet(
        self,
        room_id: str,
        user_id: str,
        points_wagered: int,
        sport: str,
        league: str,
        event_datetime: int,
        game_id: str,
    ) -> bool:
        """
        Check if a user already has a bet with the same points within the same week boundary.

        Args:
            room_id: The room ID
            user_id: The user ID
            points_wagered: Points being wagered (1, 2, or 3)
            sport: The sport (e.g., 'football')
            league: The league (e.g., 'nfl')
            event_datetime: Event timestamp in epoch seconds
            game_id: The game ID

        Returns:
            bool: True if bet is valid (no duplicate), False if duplicate exists

        Raises:
            DuplicateBetException: If a duplicate bet exists in the same week
        """
        from common.helpers.week_helper import WeekHelper

        try:
            # Get week boundaries for this sport/league
            # Pass request_id from self.logger context
            request_id = getattr(self.logger, "_keys", {}).get("request_id")
            week_helper = WeekHelper(request_id=request_id)
            week_boundary = week_helper.get_week_boundary(
                sport, league, event_datetime, game_id
            )

            if not week_boundary:
                self.logger.warning(
                    f"Could not determine week boundary for {sport}/{league}, allowing bet"
                )
                return True

            week_start_epoch, week_end_epoch = week_boundary

            # Query for existing bets with same points in this week
            response = self.table.query(
                KeyConditionExpression="PK = :pk",
                FilterExpression="contains(SK, :point_user) AND #event_dt BETWEEN :week_start AND :week_end",
                ExpressionAttributeValues={
                    ":pk": f"ROOM#{room_id}",
                    ":point_user": f"POINT#{points_wagered}#USER#{user_id}",
                    ":week_start": week_start_epoch,
                    ":week_end": week_end_epoch,
                },
                ExpressionAttributeNames={"#event_dt": "event_datetime"},
            )

            existing_bets = response.get("Items", [])

            if existing_bets:
                self.logger.warning(
                    f"User {user_id} already has a {points_wagered}-point bet in this week "
                    f"(week boundary: {week_start_epoch} to {week_end_epoch})"
                )
                raise DuplicateBetException(
                    f"You already have a {points_wagered}-point bet placed this week"
                )

            self.logger.info(
                f"Bet validation passed for user {user_id}, {points_wagered} points in week "
                f"{week_start_epoch} to {week_end_epoch}"
            )
            return True

        except DuplicateBetException:
            raise
        except Exception as e:
            self.logger.error(f"Error validating week boundary bet: {e}")
            # In case of error, allow the bet to proceed
            return True

    def _enhance_bet_with_game_data(self, bet_data: dict) -> dict:
        """
        Enhance bet data with current ESPN game data (scores, status).

        Args:
            bet_data: The bet dictionary from DynamoDB

        Returns:
            Enhanced bet data with game_status field containing structured team data
        """
        try:
            game_id = bet_data.get("game_id")
            sport = bet_data.get("sport")
            league = bet_data.get("league")

            if not all([game_id, sport, league]):
                self.logger.warning(
                    f"Missing required fields for ESPN data: game_id={game_id}, sport={sport}, league={league}"
                )
                return bet_data

            # Get current game data from ESPN
            request_id = getattr(self.logger, "_keys", {}).get("request_id")
            espn_client = ESPNClient(request_id=request_id)

            game_data = espn_client.get_event(
                sport=sport, league=league, event_id=game_id
            )

            if game_data:
                # Extract team information and scores
                competitors = game_data.get("competitors", [])
                status = game_data.get("status", {})

                home_team = None
                away_team = None

                for competitor in competitors:
                    team_info = {
                        "name": competitor.get("name", "Unknown"),
                        "short_name": competitor.get(
                            "abbreviation", competitor.get("name", "UNK")[:3].upper()
                        ),
                        "score": int(competitor.get("score", 0)),
                    }

                    if competitor.get("homeAway", "").lower() == "home":
                        home_team = team_info
                    elif competitor.get("homeAway", "").lower() == "away":
                        away_team = team_info

                # Create structured game status
                bet_data["game_status"] = {
                    "status": {
                        "name": status.get("name", ""),
                        "state": status.get("state", ""),
                        "detail": status.get("detail", ""),
                        "completed": status.get("completed", False),
                    },
                    "home_team": home_team,
                    "away_team": away_team,
                    "start_date": game_data.get("startDate"),
                    "game_id": game_id,
                }

                self.logger.info(
                    f"Enhanced bet with structured game status for game_id: {game_id}, home: {home_team}, away: {away_team}"
                )
            else:
                self.logger.warning(
                    f"Could not fetch ESPN game data for game_id: {game_id}"
                )

        except Exception as e:
            self.logger.error(f"Error enhancing bet with game data: {str(e)}")

        return bet_data

    def check_and_grade_bet(self, bet_data: dict) -> Optional[dict]:
        """
        Check if a bet's total_points_earned is None and grade it using ESPN API.

        Args:
            bet_data: The bet dictionary from DynamoDB

        Returns:
            Updated bet data if grading was performed, None if no grading needed
        """
        game_id = bet_data.get("game_id", "unknown")
        user_id = bet_data.get("user_id", "unknown")
        points_wagered = bet_data.get("points_wagered", "unknown")

        self.logger.info(
            f"Starting bet grading check for game_id: {game_id}, user: {user_id}, points: {points_wagered}"
        )

        # Check if bet already has points earned
        total_points_earned = bet_data.get("total_points_earned")
        if total_points_earned is not None:
            self.logger.info(
                f"Bet already graded with {total_points_earned} points - skipping grading"
            )
            return None

        self.logger.info(
            f"Bet not yet graded (total_points_earned is {total_points_earned}) - proceeding with grading"
        )

        try:
            # Get current game status from ESPN
            espn_client = ESPNClient(request_id=self.request_id)

            sport = bet_data["sport"]
            league = bet_data["league"]
            self.logger.info(
                f"Fetching game data from ESPN for {sport}/{league} game_id: {game_id}"
            )

            game_data = espn_client.get_event(
                sport=sport, league=league, event_id=game_id
            )

            if not game_data:
                self.logger.warning(
                    f"Could not fetch game data from ESPN for game_id: {game_id}"
                )
                return None

            # Log detailed game status information
            status_data = game_data.get("status", {})
            # The ESPN client restructures the status data
            game_status = status_data.get("name", "")
            game_state = status_data.get("state", "")
            game_detail = status_data.get("detail", "")
            completed = status_data.get("completed", False)

            # Update odds_snapshot or current_status in bet_data
            if "odds_snapshot" in bet_data and isinstance(
                bet_data["odds_snapshot"], dict
            ):
                bet_data["odds_snapshot"]["status"] = status_data
            else:
                bet_data["current_status"] = game_data

            # Persist the updated status to DynamoDB
            pk = bet_data.get("PK")
            sk = bet_data.get("SK")
            if pk and sk:
                item = self._convert_floats_to_decimals(bet_data)
                self.table.put_item(Item=item)
                self.logger.info(
                    f"Updated odds_snapshot/status in DynamoDB for PK: {pk}, SK: {sk}"
                )

            self.logger.info(
                f"Game status details - name: '{game_status}', state: '{game_state}', detail: '{game_detail}', completed: {completed}"
            )

            self.logger.info(f"Bet data before grading: {bet_data}")

            # Check if game is completed - use multiple conditions for reliability
            is_final = (
                game_status.lower() in ["final", "status_final"]
                or game_detail.lower() == "final"
                or completed is True
                or game_state == "post"
            )

            if not is_final:
                self.logger.info(
                    f"Game not yet final - status: '{game_status}', state: '{game_state}', detail: '{game_detail}', completed: {completed} - skipping grading"
                )
                return bet_data

            self.logger.info(f"Game is final - proceeding with bet grading")

            # Grade the bet based on type
            bet_type = bet_data["game_bet"]["bet_type"]

            self.logger.info(f"Grading {bet_type} bet")
            points_earned = None

            if bet_type == "spread":
                points_earned = self._grade_spread_bet(bet_data, game_data)
            elif bet_type == "over_under":
                points_earned = self._grade_over_under_bet(bet_data, game_data)
            else:
                self.logger.error(f"Unknown bet type: {bet_type}")
                return None

            if points_earned is not None:
                self.logger.info(
                    f"Bet grading complete - earned {points_earned} points, updating database"
                )
                # Update the bet with the graded result
                updated_bet = self._update_bet_result(bet_data, points_earned)
                self.logger.info(
                    f"Successfully updated bet in database with {points_earned} points"
                )
                return updated_bet
            else:
                self.logger.warning(
                    f"Bet grading returned None points - no database update performed"
                )

        except Exception as e:
            self.logger.error(
                f"Error grading bet for game_id {game_id}: {str(e)}", exc_info=True
            )
            return None

        return None

    def _grade_spread_bet(self, bet_data: dict, game_data: dict) -> Optional[float]:
        """
        Grade a spread bet based on game results.

        Args:
            bet_data: The bet dictionary
            game_data: Game data from ESPN API

        Returns:
            Points earned (points_wagered if won, 0 if lost, None if error)
        """
        try:
            game_bet = bet_data["game_bet"]
            self.logger.info(f"Grading spread bet for game_bet: {game_bet}")
            selected_team = game_bet["team_choice"]  # This should be "home" or "away"

            # Use spreadDetails from odds_snapshot
            spread_details = bet_data["odds_snapshot"].get("spreadDetails")
            if not spread_details:
                self.logger.warning(
                    f"Missing spreadDetails in odds_snapshot for bet: {bet_data}"
                )
                return None

            try:
                spread_value = float(spread_details.split(" ")[1])
                self.logger.info(f"Parsed spread value: {spread_value}")
            except (IndexError, ValueError) as e:
                self.logger.error(
                    f"Error parsing spreadDetails '{spread_details}': {e}"
                )
                return None

            points_wagered = bet_data["points_wagered"]

            self.logger.info(
                f"Grading spread bet: team_choice={selected_team}, spread_value={spread_value}, points_wagered={points_wagered}"
            )

            # Get team scores from game data
            competitors = game_data.get("competitors", [])

            if not competitors:
                self.logger.warning(
                    f"No competitor data found in game_data. Available keys: {list(game_data.keys())}"
                )
                return None

            home_score = None
            away_score = None
            home_team_name = None
            away_team_name = None

            for competitor in competitors:
                try:
                    score = int(competitor.get("score", 0))
                    team_name = competitor.get("name", "Unknown")
                    home_away = competitor.get("homeAway", "")

                    if home_away.lower() == "home":
                        home_score = score
                        home_team_name = team_name
                    elif home_away.lower() == "away":
                        away_score = score
                        away_team_name = team_name

                    self.logger.info(
                        f"Team: {team_name} ({home_away}) - Score: {score}"
                    )
                except (ValueError, TypeError) as e:
                    self.logger.error(
                        f"Error parsing score for competitor {competitor}: {e}"
                    )
                    return None

            if home_score is None or away_score is None:
                self.logger.error(
                    f"Could not extract both team scores - home: {home_score}, away: {away_score}"
                )
                return None

            self.logger.info(
                f"Team scores - Home: {home_team_name} = {home_score}, Away: {away_team_name} = {away_score}"
            )

            # Calculate the spread result
            if selected_team.lower() == "home":
                selected_score = home_score
                opponent_score = away_score
                selected_team_name = home_team_name
            else:  # away
                selected_score = away_score
                opponent_score = home_score
                selected_team_name = away_team_name

            # Calculate the margin (selected team score - opponent score)
            margin = selected_score - opponent_score

            # Determine if the bet is a win based on the spread value
            if spread_value < 0:
                # For negative spreads, the margin must be greater than or equal to the absolute spread
                user_wins = margin >= abs(spread_value)
            else:
                # For positive spreads, the margin must be greater than the spread
                user_wins = margin > spread_value

            points_earned = points_wagered if user_wins else 0

            self.logger.info(
                f"Spread bet graded: {selected_team_name} ({selected_team.upper()}) "
                f"spread {spread_value:+.1f}, "
                f"Margin: {margin} (scored {selected_score}, opponent {opponent_score}), "
                f"Result: {'WIN' if user_wins else 'LOSS'} ({points_earned} points)"
            )

            return points_earned

        except Exception as e:
            self.logger.error(f"Error grading spread bet: {e}")
            return None

    def _grade_over_under_bet(self, bet_data: dict, game_data: dict) -> Optional[float]:
        """
        Grade an Total bet based on game results.

        Args:
            bet_data: The bet dictionary
            game_data: Game data from ESPN API

        Returns:
            Points earned (points_wagered if won, 0 if lost, None if error)
        """
        try:
            game_bet = bet_data["game_bet"]
            over_under_choice = game_bet["over_under_choice"]  # "over" or "under"
            total_line = float(
                game_bet["total_value"]
            )  # Changed from total_line to total_value
            points_wagered = bet_data["points_wagered"]

            self.logger.info(
                f"Grading Total bet: choice={over_under_choice}, line={total_line}, points_wagered={points_wagered}"
            )

            # Get team scores from game data
            competitors = game_data.get("competitors", [])

            if not competitors:
                self.logger.warning(
                    f"No competitor data found in game_data. Available keys: {list(game_data.keys())}"
                )
                return None

            total_score = 0
            team_scores = []

            for competitor in competitors:
                try:
                    score = int(competitor.get("score", 0))
                    team_name = competitor.get("name", "Unknown")
                    home_away = competitor.get("homeAway", "")
                    total_score += score
                    team_scores.append(f"{team_name} ({home_away}): {score}")
                    self.logger.info(
                        f"Team: {team_name} ({home_away}) - Score: {score}"
                    )
                except (ValueError, TypeError) as e:
                    self.logger.error(
                        f"Error parsing score for competitor {competitor}: {e}"
                    )
                    return None

            self.logger.info(
                f"Total game score: {total_score} (Teams: {', '.join(team_scores)})"
            )

            # Determine if bet won
            if over_under_choice.lower() == "over":
                user_wins = total_score > total_line
            else:  # under
                user_wins = total_score < total_line

            points_earned = points_wagered if user_wins else 0

            self.logger.info(
                f"Total bet graded: {over_under_choice.upper()} {total_line}, "
                f"Total score: {total_score}, "
                f"Result: {'WIN' if user_wins else 'LOSS'} ({points_earned} points)"
            )

            return points_earned

        except Exception as e:
            self.logger.error(f"Error grading Total bet: {e}")
            return None

    def _update_bet_result(self, bet_data: dict, points_earned: float) -> dict:
        """
        Update a bet in DynamoDB with the graded result.

        Args:
            bet_data: The original bet dictionary
            points_earned: Points earned from the bet

        Returns:
            Updated bet dictionary
        """
        try:
            game_id = bet_data.get("game_id", "unknown")
            user_id = bet_data.get("user_id", "unknown")
            room_id = bet_data.get("room_id", "unknown")

            self.logger.info(
                f"Updating bet result for game_id: {game_id}, user: {user_id}, room: {room_id}"
            )

            # Update the bet data
            old_total_points = bet_data.get("total_points_earned")
            bet_data["total_points_earned"] = points_earned
            bet_data["graded_at"] = int(datetime.now().timestamp())

            # Also update the game_bet result and points_earned
            if "game_bet" in bet_data:
                result_text = "win" if points_earned > 0 else "loss"
                bet_data["game_bet"]["result"] = result_text
                bet_data["game_bet"]["points_earned"] = int(points_earned)
                self.logger.info(
                    f"Updated game_bet with result: {result_text}, points_earned: {points_earned}"
                )

            self.logger.info(
                f"Updated total_points_earned from {old_total_points} to {points_earned}"
            )

            # Convert to DynamoDB format
            item = self._convert_floats_to_decimals(bet_data)

            # Log the key being updated
            pk = item.get("PK", f"ROOM#{room_id}")
            sk = item.get("SK", "unknown")
            self.logger.info(f"Updating DynamoDB item with PK: {pk}, SK: {sk}")

            # Update in DynamoDB
            self.table.put_item(Item=item)

            self.logger.info(
                f"Successfully updated bet in DynamoDB with {points_earned} points earned"
            )

            # Return the serializable version
            updated_item = self._convert_decimals_to_floats(item)
            self.logger.info(
                f"Returning updated bet data with total_points_earned: {updated_item.get('total_points_earned')}"
            )
            return updated_item

        except Exception as e:
            self.logger.error(
                f"Error updating bet result in database: {str(e)}", exc_info=True
            )
            raise

    def validate_odds_snapshot(self, odds_snapshot: dict, event_data: dict) -> bool:
        """
        Validate that the home/away team odds in odds_snapshot match those in event_data.
        Returns True if they match, False otherwise. Adds detailed logging for debugging.
        """
        self.logger.info(
            f"Validating odds snapshot: odds_snapshot={odds_snapshot}, event_data keys={list(event_data.keys())}"
        )
        home_odds_req = odds_snapshot.get("homeTeamOdds", {})
        away_odds_req = odds_snapshot.get("awayTeamOdds", {})

        pickcenter = event_data.get("pickcenter", [])
        print(event_data)
        self.logger.info(f"Event pickcenter: {pickcenter}")
        espn_bet = next(
            (p for p in pickcenter if p.get("provider", {}).get("name") == "ESPN BET"),
            None,
        )
        if not espn_bet:
            self.logger.warning("No ESPN BET provider found in event_data pickcenter.")
            return False

        home_odds_event = espn_bet.get("homeTeamOdds", {})
        away_odds_event = espn_bet.get("awayTeamOdds", {})
        spread_event = espn_bet.get("spread")
        over_under_event = espn_bet.get("overUnder")

        spread_req = odds_snapshot.get("spread")
        over_under_req = odds_snapshot.get("overUnder")

        self.logger.info(
            f"Comparing home odds: request={home_odds_req}, event={home_odds_event}"
        )
        self.logger.info(
            f"Comparing away odds: request={away_odds_req}, event={away_odds_event}"
        )
        self.logger.info(
            f"Comparing spread: request={spread_req}, event={spread_event}"
        )
        self.logger.info(
            f"Comparing overUnder: request={over_under_req}, event={over_under_event}"
        )

        match = (
            home_odds_req.get("moneyLine") == home_odds_event.get("moneyLine")
            and home_odds_req.get("spreadOdds") == home_odds_event.get("spreadOdds")
            and away_odds_req.get("moneyLine") == away_odds_event.get("moneyLine")
            and away_odds_req.get("spreadOdds") == away_odds_event.get("spreadOdds")
            and spread_req == spread_event
            and over_under_req == over_under_event
        )
        self.logger.info(f"Odds snapshot match result: {match}")
        return match

    def reset_bets_for_room(self, room_id: str) -> None:
        """
        Reset all bets in a given room by setting their total_points_earned to None.

        Args:
            room_id: The room ID whose bets need to be reset.
        """
        try:
            # Fetch all bets for the room
            bets = self.get_all_bets_for_room(room_id)

            for bet in bets:
                # Update total_points_earned to None
                bet["total_points_earned"] = None

                # Convert to DynamoDB format and update the item
                item = self._convert_floats_to_decimals(bet)
                self.table.put_item(Item=item)

                self.logger.info(
                    f"Reset total_points_earned for bet with PK: {bet['PK']}, SK: {bet['SK']}"
                )
            return len(bets)

            self.logger.info(f"Successfully reset all bets for room {room_id}")
        except Exception as e:
            self.logger.error(f"Error resetting bets for room {room_id}: {e}")
            raise

    def reset_bet(
        self, room_id: str, points_wagered: int, user_id: str, event_datetime: int
    ) -> None:
        """
        Reset an individual bet by setting its total_points_earned to None.

        Args:
            room_id: The room ID.
            points_wagered: The points wagered for the bet.
            user_id: The user ID who placed the bet.
            event_datetime: The event datetime for the bet.
        """
        try:
            # Fetch the specific bet
            bet = self.get_bet(room_id, points_wagered, user_id, event_datetime)

            if not bet:
                self.logger.warning(
                    f"No bet found for room_id={room_id}, points_wagered={points_wagered}, user_id={user_id}, event_datetime={event_datetime}"
                )
                return

            # Update total_points_earned to None
            bet["total_points_earned"] = None

            # Convert to DynamoDB format and update the item
            item = self._convert_floats_to_decimals(bet)
            self.table.put_item(Item=item)

            self.logger.info(
                f"Reset total_points_earned for bet with PK: {bet['PK']}, SK: {bet['SK']}"
            )
        except Exception as e:
            self.logger.error(
                f"Error resetting bet for room_id={room_id}, points_wagered={points_wagered}, user_id={user_id}, event_datetime={event_datetime}: {e}"
            )
            raise

    def assign_bet_uuids(self, room_id: str) -> int:
        """
        Assign a UUID to any bet in the room that doesn't already have one.

        Args:
            room_id: The room ID whose bets need to be checked and updated.

        Returns:
            int: The number of bets updated.
        """
        try:
            # Fetch all bets for the room
            bets = self.get_all_bets_for_room(room_id)
            updated_count = 0

            for bet in bets:
                if "bet_uuid" not in bet:
                    # Generate a UUID for bet_uuid
                    bet["bet_uuid"] = str(uuid.uuid4())

                    # Convert to DynamoDB format and update the item
                    item = self._convert_floats_to_decimals(bet)
                    self.table.put_item(Item=item)

                    self.logger.info(
                        f"Assigned bet_uuid {bet['bet_uuid']} to bet with PK: {bet['PK']}, SK: {bet['SK']}"
                    )
                    updated_count += 1

            self.logger.info(
                f"Assigned bet_uuid to {updated_count} bets in room {room_id}"
            )
            return updated_count
        except Exception as e:
            self.logger.error(f"Error assigning bet_uuids for room {room_id}: {e}")
            raise
            raise
