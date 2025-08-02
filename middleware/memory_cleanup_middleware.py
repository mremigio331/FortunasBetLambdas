from starlette.middleware.base import BaseHTTPMiddleware
from aws_lambda_powertools import Logger
from aws_lambda_powertools.metrics import Metrics, MetricUnit
import gc
import tracemalloc
import os
from common.constants.services import API_SERVICE
from common.constants.metrics import (
    API_METRICS_NAMESPACE,
    ENDPOINT,
    REQUEST_MEMORY_ALLOCATED_KB,
    REQUEST_MEMORY_FREED_KB,
)

logger = Logger(service=API_SERVICE)


class MemoryCleanupMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Attach request_id if available
        if hasattr(request.state, "request_id") and request.state.request_id:
            logger.append_keys(request_id=request.state.request_id)

        # Get endpoint name for metrics
        endpoint = request.url.path

        # Get stage for metrics namespace
        metrics = Metrics(
            namespace=API_METRICS_NAMESPACE,
            service=API_SERVICE,
        )
        metrics.add_dimension(name=ENDPOINT, value=endpoint)

        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        response = await call_next(request)

        gc.collect()  # Run garbage collection after every request

        # Only take snapshot if tracemalloc is still tracing
        if tracemalloc.is_tracing():
            snapshot_after = tracemalloc.take_snapshot()
            stats = snapshot_after.compare_to(snapshot_before, "filename")
            total_before = (
                sum([stat.size_diff for stat in stats if stat.size_diff < 0]) * -1
            )
            total_after = sum([stat.size_diff for stat in stats if stat.size_diff > 0])

            logger.info(
                f"Memory cleanup: {total_before / 1024:.2f} KB freed, {total_after / 1024:.2f} KB newly allocated after request."
            )

            # Add a metric for memory used during the request (in KB)
            metrics.add_metric(
                name=REQUEST_MEMORY_ALLOCATED_KB,
                unit=MetricUnit.Kilobytes,
                value=total_after / 1024,
            )
            metrics.add_metric(
                name=REQUEST_MEMORY_FREED_KB,
                unit=MetricUnit.Kilobytes,
                value=total_before / 1024,
            )
            metrics.flush_metrics()

            tracemalloc.stop()
        else:
            logger.warning(
                "tracemalloc is not tracing; skipping memory snapshot and metrics."
            )

        return response
