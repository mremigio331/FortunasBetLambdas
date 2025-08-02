import os

STAGE = os.getenv("STAGE", "dev").lower()
API_METRICS_NAMESPACE = f"FortunasBet-{STAGE.upper()}"

ENDPOINT = "Endpoint"
REQUEST_MEMORY_ALLOCATED_KB = "RequestMemoryAllocatedKB"
REQUEST_MEMORY_FREED_KB = "RequestMemoryFreedKB"
