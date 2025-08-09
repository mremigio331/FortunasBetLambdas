import time
import uuid
from typing import Optional
import boto3
from boto3.dynamodb.conditions import Key
from common.models.notification_model import NotificationModel
from common.models.notification_model import NotificationType
from aws_lambda_powertools import Logger
import os


class NotificationHelper:
    def __init__(self, request_id: str):
        self.dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        table_name = os.getenv("TABLE_NAME")
        self.table = self.dynamodb.Table(table_name)
        self.logger = Logger()
        self.logger.append_keys(request_id=request_id)

    def create_notification(
        self, user_id: str, message: str, notification_type: NotificationType
    ) -> NotificationModel:
        """
        Create a notification for a user.
        notification_type should be a NotificationType enum or its value (str).
        """
        notification_id = str(uuid.uuid4())
        timestamp = int(time.time())
        # Accept both enum and str for notification_type

        notification = NotificationModel(
            view=False,
            message=message,
            notification_type=notification_type,
            timestamp=timestamp,
        )
        pk = NotificationModel.create_pk(user_id)
        sk = NotificationModel.create_sk(notification_id)
        item = {
            "PK": pk,
            "SK": sk,
            "view": notification.view,
            "message": notification.message,
            "notification_type": notification.notification_type.value,
            "timestamp": notification.timestamp,
        }
        self.table.put_item(Item=item)
        if self.logger:
            self.logger.info(
                f"Notification created for user {user_id}: {message} [{notification_type.value}]"
            )
        return notification

    def acknowledge_notification(self, user_id: str, notification_id: str) -> bool:
        pk = NotificationModel.create_pk(user_id)
        sk = NotificationModel.create_sk(notification_id)
        response = self.table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression="SET #v = :true",
            ExpressionAttributeNames={"#v": "view"},
            ExpressionAttributeValues={":true": True},
            ReturnValues="UPDATED_NEW",
        )
        updated = response.get("Attributes", {}).get("view", False)
        if self.logger:
            self.logger.info(
                f"Notification {notification_id} for user {user_id} acknowledged."
            )
        return updated

    def get_notifications(self, user_id: str) -> list[NotificationModel]:
        pk = NotificationModel.create_pk(user_id)
        notifications = []
        last_evaluated_key = None
        self.logger.info(f"Retrieving notifications for user {user_id} with PK: {pk}")
        while True:
            query_kwargs = {
                "KeyConditionExpression": Key("PK").eq(pk)
                & Key("SK").begins_with("NOTIFICATION#")
            }
            if last_evaluated_key:
                query_kwargs["ExclusiveStartKey"] = last_evaluated_key
            response = self.table.query(**query_kwargs)
            self.logger.info(f"Query response: {response}")
            notifications.extend([response.get("Items", [])])
            last_evaluated_key = response.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break
        if self.logger:
            self.logger.info(
                f"Retrieved {len(notifications)} notifications for user {user_id} (with pagination)."
            )
        return notifications
