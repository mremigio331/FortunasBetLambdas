from functools import wraps
from exceptions.user_exceptions import (
    UserNotFound,
    InvalidUserIdException,
    ProfileNotPublicOrDoesNotExist,
)
from exceptions.jwt_exeptions import (
    InvalidJWTException,
    ExpiredJWTException,
    MissingJWTException,
    JWTSignatureException,
)
from exceptions.room_exceptions import (
    InvalidLeagueException,
    EmptyLeagueListException,
    RoomNotFoundException,
    UnauthorizedRoomAccessException,
    InvalidDateRangeException,
    EmptyAdminsListException,
)
from fastapi.responses import JSONResponse
from botocore.exceptions import ClientError


def exceptions_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)

        # 4XX
        except UserNotFound as exc:
            return JSONResponse(
                content={"message": str(exc) or "User not found."}, status_code=404
            )
        except RoomNotFoundException as exc:
            return JSONResponse(
                content={"message": str(exc) or "Room not found."}, status_code=404
            )
        except InvalidUserIdException as exc:
            return JSONResponse(
                content={"message": str(exc) or "Invalid user ID."}, status_code=400
            )
        except (
            InvalidLeagueException,
            EmptyLeagueListException,
            InvalidDateRangeException,
            EmptyAdminsListException,
        ) as exc:
            return JSONResponse(
                content={"message": str(exc) or "Invalid room data."}, status_code=400
            )
        except (InvalidJWTException, JWTSignatureException) as exc:
            return JSONResponse(
                content={"message": str(exc) or "Invalid JWT."}, status_code=401
            )
        except ExpiredJWTException as exc:
            return JSONResponse(
                content={"message": str(exc) or "JWT expired."}, status_code=401
            )
        except MissingJWTException as exc:
            return JSONResponse(
                content={"message": str(exc) or "JWT missing."}, status_code=401
            )
        except (ProfileNotPublicOrDoesNotExist, UnauthorizedRoomAccessException) as exc:
            return JSONResponse(
                status_code=403,
                content={
                    "message": str(exc) or "Access denied: insufficient permissions."
                },
            )

        ### 5XX
        except ClientError as exc:
            return JSONResponse(
                content={"message": str(exc) or "Internal server error."},
                status_code=500,
            )

    return wrapper
