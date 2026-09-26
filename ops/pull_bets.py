"""
Ops tool for pulling full bet dicts out of DynamoDB for debugging.

Unlike the BetHelper.get_* methods used by the API (which grade bets and
enhance them with live ESPN data, mutating DynamoDB as a side effect), this
tool reads the RAW stored item by default so you can inspect the true persisted
state of a bet. Grading and ESPN enrichment are opt-in via flags.

Lookup strategies:
  by-room        Pull every bet (active + removed) in a room.
  by-user        Pull every bet for a user in a room.
  by-game        Find a user's bet(s) on a specific ESPN game_id in a room.
  by-sk          Pull one exact bet by its full SK components.
  find-game      Scan ALL rooms for bets on a given game_id (cross-room search).
  removed        Pull soft-deleted (REMOVED#) bets for a user in a room.

Examples:
  python ops/pull_bets.py by-room --room-id abc123
  python ops/pull_bets.py by-user --room-id abc123 --user-id u-1 --grade
  python ops/pull_bets.py by-game --room-id abc123 --user-id u-1 --game-id 401547 --espn
  python ops/pull_bets.py by-sk --room-id abc123 --points-wagered 3 --user-id u-1 --event-datetime 1700000000
  python ops/pull_bets.py find-game --game-id 401547 --stage prod
  python ops/pull_bets.py removed --room-id abc123 --user-id u-1
"""

import sys
import os
import json
import argparse
from decimal import Decimal

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import boto3

from common.models.bet import BetModel
from common.helpers.bet_helper import BetHelper
from common.helpers.room_helper import RoomHelper

REGION = "us-west-2"
REQUEST_ID = "ops-pull-bets"


def _table_name(stage: str) -> str:
    """Resolve the DynamoDB table name for the given stage."""
    return (
        "FortunasBet-UserTable-Prod"
        if stage == "prod"
        else "FortunasBet-UserTable-Testing"
    )


def _decimals_to_native(obj):
    """Recursively convert Decimal -> int/float so items are JSON serializable."""
    if isinstance(obj, Decimal):
        # Preserve ints (e.g. epoch timestamps) as ints when possible.
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: _decimals_to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimals_to_native(v) for v in obj]
    return obj


def _dump(items, count_label="bet(s)"):
    """Pretty-print a list of items as JSON and a trailing summary line."""
    native = _decimals_to_native(items)
    print(json.dumps(native, indent=2, default=str))
    print(f"\n--- {len(native)} {count_label} ---", file=sys.stderr)


def _raw_query_room(table, room_id, sk_prefix="POINT#"):
    """Raw DynamoDB query for a room's bets by SK prefix (no grading/enrichment)."""
    response = table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
        ExpressionAttributeValues={
            ":pk": BetModel.create_pk(room_id),
            ":sk_prefix": sk_prefix,
        },
    )
    return response.get("Items", [])


def _apply_enrichment(items, table_name, grade, espn):
    """Optionally run grading and/or ESPN enrichment via BetHelper.

    Note: grading mutates DynamoDB (writes graded results back). Only use
    --grade when you intend to (re)grade, not for a pure read.
    """
    if not (grade or espn):
        return [_decimals_to_native(i) for i in items]

    helper = BetHelper(request_id=REQUEST_ID, table_name=table_name)
    out = []
    for item in items:
        native = helper._convert_decimals_to_floats(item)
        if grade:
            graded = helper.check_and_grade_bet(native)
            if graded:
                native = graded
        if espn:
            native = helper._enhance_bet_with_game_data(native)
        out.append(native)
    return out


def cmd_by_room(args, table):
    items = _raw_query_room(table, args.room_id)
    if not args.include_removed:
        items = [i for i in items if not i.get("SK", "").startswith("REMOVED#")]
    else:
        items += _raw_query_room(table, args.room_id, sk_prefix="REMOVED#")
    items = _apply_enrichment(items, _table_name(args.stage), args.grade, args.espn)
    _dump(items)


def cmd_by_user(args, table):
    items = _raw_query_room(table, args.room_id)
    user_tag = f"USER#{args.user_id}"
    filtered = [
        i
        for i in items
        if user_tag in i.get("SK", "") and not i.get("SK", "").startswith("REMOVED#")
    ]
    filtered = _apply_enrichment(
        filtered, _table_name(args.stage), args.grade, args.espn
    )
    _dump(filtered)


def cmd_by_game(args, table):
    items = _raw_query_room(table, args.room_id)
    user_tag = f"USER#{args.user_id}"
    filtered = [
        i
        for i in items
        if user_tag in i.get("SK", "")
        and i.get("game_id") == args.game_id
        and not i.get("SK", "").startswith("REMOVED#")
    ]
    filtered = _apply_enrichment(
        filtered, _table_name(args.stage), args.grade, args.espn
    )
    _dump(filtered)


def cmd_by_sk(args, table):
    response = table.get_item(
        Key={
            "PK": BetModel.create_pk(args.room_id),
            "SK": BetModel.create_sk(
                args.points_wagered, args.user_id, args.event_datetime
            ),
        }
    )
    item = response.get("Item")
    items = [item] if item else []
    items = _apply_enrichment(items, _table_name(args.stage), args.grade, args.espn)
    _dump(items)


def cmd_find_game(args, table):
    """Scan every room for bets on a given game_id. Useful when you only know
    the ESPN game_id and not which room/user placed the bet."""
    room_helper = RoomHelper(request_id=REQUEST_ID, table_name=_table_name(args.stage))
    rooms = room_helper.get_all_rooms()
    matches = []
    for room in rooms:
        room_id = room["room_id"]
        items = _raw_query_room(table, room_id)
        if args.include_removed:
            items += _raw_query_room(table, room_id, sk_prefix="REMOVED#")
        for i in items:
            if i.get("game_id") == args.game_id:
                matches.append(i)
    matches = _apply_enrichment(matches, _table_name(args.stage), args.grade, args.espn)
    _dump(matches, count_label=f"bet(s) on game {args.game_id} across all rooms")


def cmd_removed(args, table):
    items = _raw_query_room(table, args.room_id, sk_prefix="REMOVED#")
    user_tag = f"USER#{args.user_id}"
    filtered = [i for i in items if user_tag in i.get("SK", "")]
    for i in filtered:
        i["status"] = "removed"
    filtered = _apply_enrichment(
        filtered, _table_name(args.stage), args.grade, args.espn
    )
    _dump(filtered, count_label="removed bet(s)")


def _add_common_flags(p, needs_room=True):
    if needs_room:
        p.add_argument("--room-id", required=True, help="The room ID.")
    p.add_argument(
        "--stage",
        choices=["testing", "prod"],
        default="testing",
        help="Stage/table to read from (default: testing).",
    )
    p.add_argument(
        "--grade",
        action="store_true",
        help="Run grading (WARNING: mutates DynamoDB with graded results).",
    )
    p.add_argument(
        "--espn",
        action="store_true",
        help="Enrich output with live ESPN game_status data (read-only).",
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Pull full bet dicts from DynamoDB for debugging."
    )
    sub = parser.add_subparsers(dest="command", required=True, help="Lookup strategy.")

    p_room = sub.add_parser("by-room", help="All bets in a room.")
    _add_common_flags(p_room)
    p_room.add_argument(
        "--include-removed",
        action="store_true",
        help="Also include soft-deleted (REMOVED#) bets.",
    )
    p_room.set_defaults(func=cmd_by_room)

    p_user = sub.add_parser("by-user", help="All active bets for a user in a room.")
    _add_common_flags(p_user)
    p_user.add_argument("--user-id", required=True, help="The user ID.")
    p_user.set_defaults(func=cmd_by_user)

    p_game = sub.add_parser("by-game", help="A user's bet(s) on a game in a room.")
    _add_common_flags(p_game)
    p_game.add_argument("--user-id", required=True, help="The user ID.")
    p_game.add_argument("--game-id", required=True, help="The ESPN game/event ID.")
    p_game.set_defaults(func=cmd_by_game)

    p_sk = sub.add_parser("by-sk", help="One exact bet by its full SK components.")
    _add_common_flags(p_sk)
    p_sk.add_argument("--user-id", required=True, help="The user ID.")
    p_sk.add_argument(
        "--points-wagered", type=int, required=True, help="Points wagered (1/2/3/6)."
    )
    p_sk.add_argument(
        "--event-datetime", type=int, required=True, help="Event datetime epoch."
    )
    p_sk.set_defaults(func=cmd_by_sk)

    p_find = sub.add_parser(
        "find-game", help="Scan ALL rooms for bets on a game_id (cross-room)."
    )
    _add_common_flags(p_find, needs_room=False)
    p_find.add_argument("--game-id", required=True, help="The ESPN game/event ID.")
    p_find.add_argument(
        "--include-removed",
        action="store_true",
        help="Also include soft-deleted (REMOVED#) bets.",
    )
    p_find.set_defaults(func=cmd_find_game)

    p_removed = sub.add_parser("removed", help="Removed bets for a user in a room.")
    _add_common_flags(p_removed)
    p_removed.add_argument("--user-id", required=True, help="The user ID.")
    p_removed.set_defaults(func=cmd_removed)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(_table_name(args.stage))

    args.func(args, table)


if __name__ == "__main__":
    main()
