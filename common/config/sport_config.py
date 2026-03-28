from dataclasses import dataclass, field
from typing import Dict, Set


@dataclass(frozen=True)
class SportRules:
    sport_key: str
    espn_sport: str
    espn_league: str
    espn_league_id: str
    allowed_points: Set[int]
    max_bets_per_week: int
    point_limits: Dict[int, int]


NFL_RULES = SportRules(
    sport_key="NFL",
    espn_sport="football",
    espn_league="nfl",
    espn_league_id="28",
    allowed_points={1, 2, 3},
    max_bets_per_week=3,
    point_limits={1: 1, 2: 1, 3: 1},
)

MLB_RULES = SportRules(
    sport_key="MLB",
    espn_sport="baseball",
    espn_league="mlb",
    espn_league_id="10",
    allowed_points={1, 6},
    max_bets_per_week=5,
    point_limits={1: 4, 6: 1},
)

SPORT_REGISTRY: Dict[str, SportRules] = {"NFL": NFL_RULES, "MLB": MLB_RULES}


def get_sport_rules(sport_key: str) -> SportRules:
    """Get rules for a sport. Defaults to NFL for backward compatibility."""
    return SPORT_REGISTRY.get(sport_key.upper(), NFL_RULES)
