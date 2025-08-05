from aws_lambda_powertools import Logger
import boto3
from botocore.exceptions import ClientError
from common.models.bet import BetModel
from datetime import datetime
from exceptions.bet_exceptions import (
    DuplicateBetException,
    BetNotFound,
    InvalidGameStatusException,
)
import os
from typing import List, Optional, Any, Dict
from decimal import Decimal


class BetHelper:
    """
    A class to interact with DynamoDB for bet operations in the FortunasBet application.
    """

    def __init__(self, request_id: str):
        self.dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        table_name = os.getenv("TABLE_NAME")
        self.table = self.dynamodb.Table(table_name)
        self.logger = Logger()
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
        existing_bet = self.get_bet(bet.room_id, bet.points_wagered, bet.user_id)
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
        event_datetime: int = None,
    ) -> Optional[dict]:
        """
        Fetch a specific bet from DynamoDB.
        If event_datetime is provided, looks for exact match. Otherwise, queries for any bet with those points for that user.
        """
        try:
            if event_datetime:
                # Look for exact bet with specific event_datetime
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
                    self.logger.info(
                        f"Retrieved {points_wagered}-point bet for user {user_id} in room {room_id} for event {event_datetime}"
                    )
                    return serializable_item
            else:
                # Query for any bet with those points for that user
                response = self.table.query(
                    KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
                    ExpressionAttributeValues={
                        ":pk": f"ROOM#{room_id}",
                        ":sk_prefix": f"POINT#{points_wagered}#USER#{user_id}",
                    },
                )
                items = response.get("Items", [])
                if items:
                    # Return the first match (most recent)
                    serializable_item = self._convert_decimals_to_floats(items[0])
                    self.logger.info(
                        f"Retrieved {points_wagered}-point bet for user {user_id} in room {room_id}"
                    )
                    return serializable_item

            self.logger.info(
                f"No {points_wagered}-point bet found for user {user_id} in room {room_id}"
            )
            return None
        except ClientError as e:
            self.logger.error(
                f"Error fetching bet for user {user_id} in room {room_id}: {e}"
            )
            raise

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

            self.logger.info(
                f"Retrieved {len(serializable_items)} bets for room {room_id}"
            )
            return serializable_items
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

            self.logger.info(
                f"Retrieved {len(serializable_items)} {points_wagered}-point bets for room {room_id}"
            )
            return serializable_items
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
                KeyConditionExpression="PK = :pk AND contains(SK, :user_id)",
                ExpressionAttributeValues={
                    ":pk": f"ROOM#{room_id}",
                    ":user_id": f"USER#{user_id}",
                },
            )
            items = response.get("Items", [])

            # Convert Decimal values back to float for JSON serialization
            serializable_items = [
                self._convert_decimals_to_floats(item) for item in items
            ]

            self.logger.info(
                f"Retrieved {len(serializable_items)} bets for user {user_id} in room {room_id}"
            )
            return serializable_items
        except ClientError as e:
            self.logger.error(
                f"Error fetching bets for user {user_id} in room {room_id}: {e}"
            )
            raise

    def system_update_bet(
        self, room_id: str, points_wagered: int, user_id: str, system_updates: dict
    ) -> Optional[dict]:
        """
        System update for bet results and locking (can update total_points_earned, locked, etc.).
        This function bypasses game status checks and is for system use only.
        """
        if not system_updates:
            self.logger.info(
                f"No fields to update for {points_wagered}-point bet {user_id} in room {room_id}"
            )
            return None

        try:
            # Fetch current bet for validation
            before_item = self.table.get_item(
                Key={
                    "PK": f"ROOM#{room_id}",
                    "SK": f"POINT#{points_wagered}#USER#{user_id}",
                }
            ).get("Item")

            if not before_item:
                raise BetNotFound(room_id, user_id, points_wagered)

            update_expr = []
            expr_attr_names = {}
            expr_attr_values = {}

            for key, value in system_updates.items():
                placeholder_name = f"#{key}"
                placeholder_value = f":{key}"
                update_expr.append(f"{placeholder_name} = {placeholder_value}")
                expr_attr_names[placeholder_name] = key
                expr_attr_values[placeholder_value] = value

            # Add updated_at timestamp
            update_expr.append("#updated_at = :updated_at")
            expr_attr_names["#updated_at"] = "updated_at"
            expr_attr_values[":updated_at"] = int(datetime.utcnow().timestamp())

            update_expression = "SET " + ", ".join(update_expr)

            response = self.table.update_item(
                Key={
                    "PK": f"ROOM#{room_id}",
                    "SK": f"POINT#{points_wagered}#USER#{user_id}",
                },
                UpdateExpression=update_expression,
                ExpressionAttributeNames=expr_attr_names,
                ExpressionAttributeValues=expr_attr_values,
                ReturnValues="ALL_NEW",
            )

            if "Attributes" in response:
                attrs = response["Attributes"]

                self.logger.info(
                    f"System updated {points_wagered}-point bet for user {user_id} in room {room_id}: {attrs}"
                )
                return attrs
            return None
        except ClientError as e:
            self.logger.error(
                f"Error system updating bet for user {user_id} in room {room_id}: {e}"
            )
            raise

    def delete_bet(self, room_id: str, points_wagered: int, user_id: str) -> bool:
        """
        Delete a bet from DynamoDB.
        """
        try:
            self.table.delete_item(
                Key={
                    "PK": f"ROOM#{room_id}",
                    "SK": f"POINT#{points_wagered}#USER#{user_id}",
                }
            )

            self.logger.info(
                f"Deleted {points_wagered}-point bet for user {user_id} in room {room_id}"
            )
            return True
        except ClientError as e:
            self.logger.error(
                f"Error deleting bet for user {user_id} in room {room_id}: {e}"
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

    def get_user_bets_for_room(self, room_id: str, user_id: str) -> List[dict]:
        """
        Get all bets for a specific user in a room (1, 2, and 3 point bets).
        """
        try:
            response = self.table.query(
                KeyConditionExpression="PK = :pk AND contains(SK, :user_id)",
                ExpressionAttributeValues={
                    ":pk": f"ROOM#{room_id}",
                    ":user_id": f"USER#{user_id}",
                },
            )
            items = response.get("Items", [])

            # Convert Decimal values back to float for JSON serialization
            serializable_items = [
                self._convert_decimals_to_floats(item) for item in items
            ]

            self.logger.info(
                f"Retrieved {len(serializable_items)} bets for user {user_id} in room {room_id}"
            )
            return serializable_items
        except ClientError as e:
            self.logger.error(
                f"Error fetching bets for user {user_id} in room {room_id}: {e}"
            )
            raise
