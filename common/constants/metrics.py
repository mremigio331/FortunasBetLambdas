import os

STAGE = os.getenv("STAGE", "dev").lower()
API_METRICS_NAMESPACE = f"FortunasBet-{STAGE.upper()}"

ENDPOINT = "Endpoint"
REQUEST_MEMORY_ALLOCATED_KB = "RequestMemoryAllocatedKB"
REQUEST_MEMORY_FREED_KB = "RequestMemoryFreedKB"

# ESPN Client Constants
ESPN_API_CALL = "ESPNApiCall"
ESPN_SUCCESS = "ESPNSuccess"
ESPN_EXCEPTION = "ESPNException"
LEAGUE_DIMENSION = "League"

# ESPN League Paths
ESPN_LEAGUE_PATHS = {
    "nfl": "football/nfl",
    "nba": "basketball/nba",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
}
