from typing import List

from common.config.sport_config import get_sport_rules, SportRules
from exceptions.bet_exceptions import (
    InvalidPointsWageredException,
    PointValueLimitExceeded,
    WeeklyBetLimitExceeded,
)


class BetValidator:
    def __init__(self, sport_key: str, request_id: str):
        self.rules: SportRules = get_sport_rules(sport_key)
        self.request_id = request_id

    def validate_point_value(self, points_wagered: int) -> None:
        """Validate that point value is allowed for this sport."""
        if points_wagered not in self.rules.allowed_points:
            raise InvalidPointsWageredException(
                points_wagered, self.rules.sport_key, self.rules.allowed_points
            )

    def validate_weekly_limits(
        self, existing_bets: List[dict], new_points: int
    ) -> None:
        """Validate weekly bet count and per-point-value limits.

        Excludes bets with REMOVED# SK prefix from active counts.
        """
        active_bets = [
            b for b in existing_bets if not b.get("SK", "").startswith("REMOVED#")
        ]

        if len(active_bets) >= self.rules.max_bets_per_week:
            raise WeeklyBetLimitExceeded(self.rules.max_bets_per_week)

        same_point_count = sum(
            1 for b in active_bets if b.get("points_wagered") == new_points
        )
        max_for_point = self.rules.point_limits.get(new_points, 0)
        if same_point_count >= max_for_point:
            raise PointValueLimitExceeded(new_points, max_for_point)
