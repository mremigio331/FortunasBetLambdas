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

    def __init__(self, request_id: str = None):
        self.dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        table_name = os.getenv("TABLE_NAME")
        self.table = self.dynamodb.Table(table_name)
        self.logger = Logger()
        if request_id:
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
        SK: POINT#{points_wagered}#USER#{user_id}

        Validates that the bet doesn't already exist before creating.
        """
        # Check if bet already exists
        existing_bet = self.get_bet(bet.room_id, bet.points_wagered, bet.user_id)
        if existing_bet:
            raise DuplicateBetException(bet.room_id, bet.user_id, bet.points_wagered)

        item = bet.dict()
        item["PK"] = f"ROOM#{bet.room_id}"
        item["SK"] = f"POINT#{bet.points_wagered}#USER#{bet.user_id}"

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
        self, room_id: str, points_wagered: int, user_id: str
    ) -> Optional[dict]:
        """
        Fetch a specific bet from DynamoDB.
        """
        try:
            response = self.table.get_item(
                Key={
                    "PK": f"ROOM#{room_id}",
                    "SK": f"POINT#{points_wagered}#USER#{user_id}",
                }
            )
            item = response.get("Item")
            if item:
                # Convert Decimal values back to float for JSON serialization
                serializable_item = self._convert_decimals_to_floats(item)
                self.logger.info(
                    f"Retrieved {points_wagered}-point bet for user {user_id} in room {room_id}"
                )
                return serializable_item
            else:
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
