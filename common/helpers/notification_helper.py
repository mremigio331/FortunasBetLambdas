import time
import uuid
from typing import Optional
from boto3.dynamodb.conditions import Key
from common.models.notification_model import NotificationModel


class NotificationHelper:
    def __init__(self, request_id: str):
        self.dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        table_name = os.getenv("TABLE_NAME")
        self.table = self.dynamodb.Table(table_name)
        self.logger = Logger()
        self.logger.append_keys(request_id=request_id)

    def create_notification(self, user_id: str, message: str) -> NotificationModel:
        notification_id = str(uuid.uuid4())
        timestamp = int(time.time())
        notification = NotificationModel(
            view=False,
            message=message,
            timestamp=timestamp,
        )
        pk = NotificationModel.create_pk(user_id)
        sk = NotificationModel.create_sk(notification_id)
        item = {
            "PK": pk,
            "SK": sk,
            "view": notification.view,
            "message": notification.message,
            "timestamp": notification.timestamp,
        }
        self.table.put_item(Item=item)
        if self.logger:
            self.logger.info(f"Notification created for user {user_id}: {message}")
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
