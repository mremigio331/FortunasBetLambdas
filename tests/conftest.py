"""Shared pytest configuration for the FortunasBetLambdas test suite."""

from hypothesis import HealthCheck, settings

# Property-based tests for this suite run a minimum of 100 iterations.
settings.register_profile(
    "default",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("default")
