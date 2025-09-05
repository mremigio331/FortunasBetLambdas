import os
import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from common.helpers.user_profile_helper import UserProfileHelper

logger = Logger(service="FortunasBet-Cognito-User-Creator")


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    logger.info("POST_CONFIRMATION Lambda triggered.")

    if event["triggerSource"] == "PostConfirmation_ConfirmSignUp":
        user_attrs = event["request"]["userAttributes"]
        logger.info(f"User attributes: {user_attrs}")

        user_id = user_attrs["sub"]
        email = user_attrs.get("email")
        name = user_attrs.get("name", "unknown")

        try:
            user_profile_helper = UserProfileHelper(request_id=context.aws_request_id)
            user_profile_helper.create_user_profile(
                user_id=user_id,
                email=email,
                name=name,
            )
            # Publish to SNS topic if ARN is set

        except Exception as e:
            logger.error(f"Failed to create user profile: {e}")
            raise

        try:
            topic_arn = os.environ.get("USER_ADDED_TOPIC_ARN")
            if topic_arn:
                sns = boto3.client("sns")
                response = sns.publish(
                    TopicArn=topic_arn,
                    Subject="New FortunasBet User Signup",
                    Message=f"New user signed up:\nID: {user_id}\nEmail: {email}\nName: {name}",
                )
                logger.info(
                    f"Published user signup to SNS topic: {topic_arn} with response: {response}"
                )
            else:
                logger.warning("USER_ADDED_TOPIC_ARN not set, skipping SNS publish.")
        except Exception as e:
            logger.error(f"Failed to publish to SNS topic: {e}")

    else:
        logger.warning(f"Unsupported triggerSource: {event['triggerSource']}")

    return event
