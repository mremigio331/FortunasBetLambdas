from enum import Enum
from datetime import datetime
from typing import Any
from aws_lambda_powertools import Logger
from botocore.exceptions import ClientError
import boto3
import os
from decimal import Decimal


class AuditActions(Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class AuditActionHelper:
    """
    Helper class for managing audit actions.
    Provides methods to create audit entries for user profiles and Strava profiles.
    """

    def __init__(self, request_id: str, table_name: str = None):
        """
        Initializes the helper with a DynamoDB table.
        :param table: The DynamoDB table instance.
        """
        self.dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        if table_name:
            self.table = self.dynamodb.Table(table_name)
        else:
            table_name = os.getenv("TABLE_NAME", "FortunasBet-UserTable-Testing")
            self.table = self.dynamodb.Table(table_name)
        self.logger = Logger()
        self.logger.append_keys(request_id=request_id)

    def to_dict(self, obj):
        if obj is None:
            return None
        if hasattr(obj, "dict"):
            return obj.dict()
        if isinstance(obj, dict):
            return obj
        return dict(obj)  # fallback, may raise if not dict-like

    def convert_floats_to_decimal(self, obj):
        if isinstance(obj, dict):
            return {k: self.convert_floats_to_decimal(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.convert_floats_to_decimal(v) for v in obj]
        elif isinstance(obj, float):
            return Decimal(str(obj))
        else:
            return obj

    def create_audit_record(
        self,
        pk: str,
        sk: str,
        user_id: str,
        entity_type: str,
        action: str,
        before: Any,
        after: Any,
    ) -> dict:
        """
        Create a new audit record for each action.
        Each audit action gets its own DynamoDB item for better performance and compliance.

        Args:
            pk: The partition key for the audit record
            sk: The sort key for the audit record
            user_id: The user performing the action
            entity_type: Type of entity being audited (e.g., "PROFILE", "STRAVA", "BET")
            action: The action performed (CREATE, UPDATE, DELETE)
            before: State before the change (None for CREATE)
            after: State after the change (None for DELETE)
        """
        timestamp = datetime.utcnow()
        timestamp_iso = timestamp.isoformat()
        timestamp_unix = int(timestamp.timestamp())

        before_dict = self.convert_floats_to_decimal(self.to_dict(before))
        after_dict = self.convert_floats_to_decimal(self.to_dict(after))

        audit_item = {
            "PK": pk,
            "SK": sk,
            "user_id": user_id,
            "entity_type": entity_type,
            "action": action,
            "before": before_dict,
            "after": after_dict,
            "timestamp": timestamp_iso,
            "timestamp_unix": timestamp_unix,
        }

        try:
            self.table.put_item(Item=audit_item)
            self.logger.info(
                f"Created audit record for {user_id}: {entity_type} {action} at {timestamp_iso}"
            )
            return audit_item
        except ClientError as e:
            self.logger.error(f"Error creating audit record for {user_id}: {e}")
            raise

    def get_audit_trail(self, pk: str, sk_prefix: str, limit: int = 50):
        """
        Get audit trail for any entity, filtered by partition key and sort key prefix.
        Handles pagination automatically to ensure all results are returned.

        Args:
            pk: The partition key to query (e.g., "USER#12345", "ROOM#room-uuid", "SYSTEM#GLOBAL")
            sk_prefix: The sort key prefix to filter by (e.g., "AUDIT#", "AUDIT#PROFILE#", "AUDIT#MEMBERSHIP#")
            limit: Maximum number of records to return
        """

        try:
            all_items = []
            last_evaluated_key = None
            items_collected = 0

            while items_collected < limit:
                # Calculate remaining items needed
                remaining_limit = limit - items_collected

                query_params = {
                    "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
                    "ExpressionAttributeValues": {":pk": pk, ":sk_prefix": sk_prefix},
                    "ScanIndexForward": False,  # Most recent first
                    "Limit": min(remaining_limit, 1000),  # DynamoDB max per query
                }

                if last_evaluated_key:
                    query_params["ExclusiveStartKey"] = last_evaluated_key

                response = self.table.query(**query_params)
                items = response.get("Items", [])
                all_items.extend(items)
                items_collected += len(items)

                # Check if there are more items to fetch
                last_evaluated_key = response.get("LastEvaluatedKey")
                if not last_evaluated_key or not items:
                    break

            return all_items[:limit]  # Ensure we don't exceed the requested limit

        except ClientError as e:
            self.logger.error(
                f"Error querying audit trail for PK={pk}, SK prefix={sk_prefix}: {e}"
            )
            raise

    def get_audit_records_by_date_range(
        self,
        pk: str,
        start_timestamp: int,
        end_timestamp: int,
        sk_prefix: str = "AUDIT#",
    ):
        """
        Get audit records for any entity within a specific date range.
        Handles pagination automatically to ensure all results are returned.

        Args:
            pk: The partition key to query (e.g., "USER#12345", "ROOM#room-uuid")
            start_timestamp: Unix timestamp for start of range
            end_timestamp: Unix timestamp for end of range
            sk_prefix: The sort key prefix to filter by (default: "AUDIT#")
        """

        try:
            all_items = []
            last_evaluated_key = None

            while True:
                query_params = {
                    "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
                    "FilterExpression": "#ts BETWEEN :start AND :end",
                    "ExpressionAttributeNames": {"#ts": "timestamp_unix"},
                    "ExpressionAttributeValues": {
                        ":pk": pk,
                        ":sk_prefix": sk_prefix,
                        ":start": start_timestamp,
                        ":end": end_timestamp,
                    },
                    "ScanIndexForward": False,  # Most recent first
                }

                if last_evaluated_key:
                    query_params["ExclusiveStartKey"] = last_evaluated_key

                response = self.table.query(**query_params)
                items = response.get("Items", [])
                all_items.extend(items)

                # Check if there are more items to fetch
                last_evaluated_key = response.get("LastEvaluatedKey")
                if not last_evaluated_key or not items:
                    break

            return all_items

        except ClientError as e:
            self.logger.error(
                f"Error querying audit records by date range for PK={pk}: {e}"
            )
            raise
