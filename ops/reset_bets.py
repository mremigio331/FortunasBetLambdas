import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from common.helpers.bet_helper import BetHelper
from common.helpers.room_helper import RoomHelper
import argparse


def reset_bets(args):
    """
    Handle the reset logic based on the parsed arguments.
    """
    # Determine the table name based on the stage
    table_name = (
        "FortunasBet-UserTable-Testing"
        if args.stage != "prod"
        else "FortunasBet-UserTable-Prod"
    )
    bet_helper = BetHelper(request_id="ops-tool", table_name=table_name)

    if args.command == "reset-room":
        count = bet_helper.reset_bets_for_room(args.room_id)
        print(f"Successfully reset {count} bets in room {args.room_id}.")
    elif args.command == "reset-bet":
        bet_helper.reset_bet(
            room_id=args.room_id,
            points_wagered=args.points_wagered,
            user_id=args.user_id,
            event_datetime=args.event_datetime,
        )
        print(
            f"Successfully reset bet in room {args.room_id} for user {args.user_id} "
            f"with points wagered {args.points_wagered} and event datetime {args.event_datetime}."
        )
    elif args.command == "reset-all-bets":
        room_helper = RoomHelper(request_id="ops-tool", table_name=table_name)
        rooms = room_helper.get_all_rooms()  # Fetch all room IDs
        total_bets_reset = 0

        for room in rooms:
            count = bet_helper.reset_bets_for_room(room_id=room["room_id"])
            total_bets_reset += count
            print(f"Successfully reset {count} bets in room {room['room_id']}.")

        print(f"Successfully reset a total of {total_bets_reset} bets in all rooms.")


def main():
    """
    Parse arguments and call the reset_bets function.
    """
    parser = argparse.ArgumentParser(description="Reset bets in DynamoDB.")
    subparsers = parser.add_subparsers(
        dest="command", required=True, help="Command to execute."
    )

    # Subparser for resetting all bets in a room
    reset_room_parser = subparsers.add_parser(
        "reset-room", help="Reset all bets in a specific room."
    )
    reset_room_parser.add_argument(
        "--room-id", required=True, help="The ID of the room to reset bets for."
    )
    reset_room_parser.add_argument(
        "--stage",
        choices=["testing", "prod"],
        default="testing",
        help="The stage to operate on (default: testing).",
    )

    # Subparser for resetting a single bet
    reset_bet_parser = subparsers.add_parser("reset-bet", help="Reset a specific bet.")
    reset_bet_parser.add_argument("--room-id", required=True, help="The room ID.")
    reset_bet_parser.add_argument(
        "--points-wagered",
        type=int,
        required=True,
        help="The points wagered for the bet.",
    )
    reset_bet_parser.add_argument("--user-id", required=True, help="The user ID.")
    reset_bet_parser.add_argument(
        "--event-datetime",
        type=int,
        required=True,
        help="The event datetime for the bet.",
    )
    reset_bet_parser.add_argument(
        "--stage",
        choices=["testing", "prod"],
        default="testing",
        help="The stage to operate on (default: testing).",
    )

    # Subparser for resetting all bets in all rooms
    reset_all_bets_parser = subparsers.add_parser(
        "reset-all-bets", help="Reset all bets in all rooms."
    )
    reset_all_bets_parser.add_argument(
        "--stage",
        choices=["testing", "prod"],
        default="testing",
        help="The stage to operate on (default: testing).",
    )

    args = parser.parse_args()
    reset_bets(args)


if __name__ == "__main__":
    main()
