# FortunasBets Lambda Functions

This package contains the serverless backend API for the FortunasBets application. Built with FastAPI and AWS Lambda, it provides a complete REST API with authentication, room management, membership system, and user profiles.

## 🏗️ Architecture Overview

- **FastAPI**: Modern Python web framework for building APIs
- **AWS Lambda**: Serverless compute for API endpoints
- **Mangum**: ASGI adapter for running FastAPI on Lambda
- **DynamoDB**: NoSQL database for data persistence
- **Cognito**: JWT authentication and user management
- **Lambda Layers**: Shared dependencies across functions

## 📋 Prerequisites

- Python 3.11+
- AWS CLI configured with appropriate permissions
- Docker (for creating Lambda layers)
- Access to FortunasBets DynamoDB table
- Cognito User Pool configured

## 🚀 Getting Started

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Create Lambda Layer
The Lambda layer contains all Python dependencies for deployment:

```bash
# Create layer with default name
./create_lambda_layer.sh

```

This script:
1. Creates a Docker container with Amazon Linux
2. Installs all requirements.txt dependencies
3. Packages them into a ZIP file for Lambda layer deployment

### Run Local Development Server
```bash
# Make script executable (first time)
chmod +x run_local_api.sh

# Start local development server
./run_local_api.sh
```

The local server will:
- Start on `http://localhost:5000`
- Connect to AWS Cognito for authentication
- Use the configured DynamoDB table
- Enable hot reload for development

### Manual Local Setup
If you prefer to run manually:

```bash
# Set environment variables
export STAGE="Dev"
export COGNITO_USER_POOL_ID="your-user-pool-id"
export COGNITO_CLIENT_ID="your-client-id"
export COGNITO_REGION="us-west-2"
export TABLE_NAME="FortunasBet-UserTable-Testing"

# Start server
uvicorn app:app --reload --port 5000
```

## 📁 Project Structure

```
api/
├── endpoints/           # API route handlers
│   ├── fortunas_bet/   # Home/health endpoints
│   ├── user/           # User profile management
│   ├── room/           # Room CRUD operations
│   └── membership/     # Membership management
├── decorators/         # Custom decorators (JWT, exceptions)
└── get_all_routes.py   # Route registration

common/
├── helpers/            # Business logic helpers
│   ├── room_helper.py
│   ├── membership_helper.py
│   └── user_profile_helper.py
├── models/             # Pydantic data models
│   ├── room.py
│   ├── membership.py
│   └── user_profile.py
└── constants/          # Application constants

exceptions/             # Custom exception classes
middleware/             # FastAPI middleware
app.py                 # Main FastAPI application
```

## 🛠️ API Endpoints

### Authentication
All protected endpoints require JWT token from Cognito.

### Room Management
```
POST   /room/create_room              # Create new room
GET    /room/get_room/{room_id}       # Get room details
PUT    /room/edit_room/{room_id}      # Update room
GET    /room/get_all_rooms            # List all rooms
GET    /room/get_valid_leagues        # Get allowed leagues
```

### Membership Management
```
POST   /membership/create_membership_request    # Request room access
GET    /membership/get_all_membership_request   # Get user's requests
GET    /membership/get_admin_requests/{room_id} # Get pending requests (admin)
PUT    /membership/edit_membership_requests     # Approve/deny requests
```

### User Profile
```
GET    /user/get_requestors_profile   # Get current user profile
PUT    /user/update_user_profile      # Update user profile
```

### Health Check
```
GET    /fortunasbet/                  # API health check
```

## 🔑 Authentication

The API uses AWS Cognito JWT tokens for authentication:

```python
from api.decorators.jwt_decorator import jwt_required

@router.post("/protected-endpoint")
@jwt_required()
def protected_endpoint(request: Request):
    user_id = request.state.user_id  # Available after JWT validation
    # Your endpoint logic here
```

### JWT Decorator Options
```python
@jwt_required()                    # Required JWT
```

## 🗄️ Database Models

### Room Model
- Single-table DynamoDB design
- Supports multiple leagues (MLB, NFL)
- Multi-admin architecture
- Public/private rooms
- Date range validation

### Membership Model
- Request/invitation system
- Status tracking (pending, approved, denied)
- Admin approval workflow
- Join date tracking

### User Profile Model
- Cognito integration
- Profile customization
- Activity tracking

## 🧪 Testing

### Local Testing
```bash
# Start local server
./run_local_api.sh

# Test endpoints
curl http://localhost:5000/fortunasbet/

# Test with JWT (get token from Cognito)
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
     http://localhost:5000/room/get_all_rooms
```

### API Documentation
When running locally, visit:
- **Swagger UI**: `http://localhost:5000/docs`
- **ReDoc**: `http://localhost:5000/redoc`

## 🚀 Deployment

### Via CDK (Recommended)
The Lambda functions are deployed through the CDK package:

```bash
cd ../FortunasBetCDK
cdk deploy FortunasBets-LambdaStack-Dev
```

### Manual Deployment
1. Create Lambda layer: `./create_lambda_layer.sh`
2. Upload layer to AWS Lambda
3. Package function code
4. Deploy via AWS CLI or Console

## 🔧 Configuration

### Environment Variables
Required environment variables:
```bash
STAGE                    # Dev/Prod
COGNITO_USER_POOL_ID     # Cognito User Pool ID
COGNITO_CLIENT_ID        # Cognito App Client ID
COGNITO_REGION           # AWS Region
TABLE_NAME               # DynamoDB table name
```

### AWS Permissions Required
The Lambda execution role needs:
- DynamoDB read/write access
- Cognito read access
- CloudWatch logs write access

## 🐛 Troubleshooting

### Common Issues

1. **Import Errors**: Ensure Lambda layer is properly created and attached
2. **DynamoDB Access**: Check IAM permissions and table name
3. **JWT Validation**: Verify Cognito configuration
4. **CORS Issues**: Check API Gateway CORS settings

### Debugging
```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Check CloudWatch logs
aws logs tail /aws/lambda/your-function-name --follow

# Test JWT token locally
python -c "
import jwt
token = 'your-jwt-token'
print(jwt.decode(token, options={'verify_signature': False}))
"
```

### Local Development Tips
- Use ngrok for external testing: `ngrok http 5000`
- Check environment variables: `printenv | grep COGNITO`
- Test DynamoDB connection: Use AWS CLI to verify table access
