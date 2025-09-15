#!/bin/bash

export STAGE="Dev"
export COGNITO_USER_POOL_ID=$(aws cognito-idp list-user-pools --region us-west-2 --max-results 60 --query "UserPools[?Name=='FortunasBet-UserPool-Testing'].Id" --output text)
export COGNITO_CLIENT_ID=$(aws cognito-idp list-user-pools --max-results 60 --region us-west-2 \
--query "UserPools[].Id" --output text | xargs -n1 -I {} aws cognito-idp list-user-pool-clients \
    --user-pool-id {} --region us-west-2 \
    --query "UserPoolClients[?contains(ClientName, 'FortunasBetUserPoolClientTesting')].ClientId" \
    --output text
)
export COGNITO_REGION="us-west-2"
export COGNITO_API_REDIRECT_URI="http://localhost:5000/"
export COGNITO_DOMAIN="https://fortunasbet-testing.auth.us-west-2.amazoncognito.com"
export API_URL="https://api.testing.fortunasbet.com"
export TABLE_NAME="FortunasBet-UserTable-Testing"

LOG_FILE="local_api.log"
uvicorn app:app --reload --port 5000 2>&1 | tee "$LOG_FILE"