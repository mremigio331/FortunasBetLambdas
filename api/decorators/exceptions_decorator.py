from functools import wraps
from exceptions.user_exceptions import (
    UserNotFound,
    InvalidUserIdException,
    ProfileNotPublicOrDoesNotExist,
    UserNameTooLong,
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
    MembershipAlreadyExistsException,
)
from exceptions.bet_exceptions import (
    DuplicateBetException,
    BetNotFound,
    InvalidGameStatusException,
    InvalidPointsWageredException,
    InvalidBetTypeException,
    BetLockedException,
    UserProfileNotFoundException,
    GameDataNotFoundException,
)
from exceptions.bet_exceptions import OddsSnapshotMismatch
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
        except BetNotFound as exc:
            return JSONResponse(
                content={
                    "message": str(exc) or "Bet not found.",
                    "room_id": exc.room_id,
                    "user_id": exc.user_id,
                    "points_wagered": exc.points_wagered,
                },
                status_code=404,
            )
        except InvalidUserIdException as exc:
            return JSONResponse(
                content={"message": str(exc) or "Invalid user ID."}, status_code=400
            )
        except UserNameTooLong as exc:
            return JSONResponse(
                content={"message": str(exc) or "User name is too long."},
                status_code=400,
            )
        except (
            InvalidLeagueException,
            EmptyLeagueListException,
            InvalidDateRangeException,
            EmptyAdminsListException,
            InvalidGameStatusException,
            InvalidPointsWageredException,
            InvalidBetTypeException,
            BetLockedException,
            GameDataNotFoundException,
            OddsSnapshotMismatch,
        ) as exc:
            return JSONResponse(
                content={"message": str(exc) or "Invalid request data."},
                status_code=400,
            )
        except DuplicateBetException as exc:
            return JSONResponse(
                content={
                    "message": str(exc) or "Bet already exists.",
                    "room_id": exc.room_id,
                    "user_id": exc.user_id,
                    "points_wagered": exc.points_wagered,
                },
                status_code=409,
            )
        except MembershipAlreadyExistsException as exc:
            return JSONResponse(
                content={
                    "message": str(exc) or "Membership request already exists.",
                    "room_id": exc.room_id,
                    "user_id": exc.user_id,
                },
                status_code=409,
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
        except UserProfileNotFoundException as exc:
            return JSONResponse(
                content={
                    "message": str(exc) or "Unable to retrieve user profile.",
                    "user_id": exc.user_id,
                },
                status_code=500,
            )
        except ClientError as exc:
            return JSONResponse(
                content={"message": str(exc) or "Internal server error."},
                status_code=500,
            )

    return wrapper
