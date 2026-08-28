from time import perf_counter

from opentelemetry import metrics


INSTRUMENTATION_SCOPE = "smartserve.observability"


def get_meter():
    """Return the application meter; it is a no-op when telemetry is disabled."""
    return metrics.get_meter(INSTRUMENTATION_SCOPE)


class ApplicationTelemetry:
    def __init__(self, *, meter=None) -> None:
        self.meter = meter or get_meter()
        self.amap_call_count = self.meter.create_counter(
            "smartserve.amap.call.count",
            unit="{call}",
            description="SmartServe AMap API calls",
        )
        self.amap_call_duration = self.meter.create_histogram(
            "smartserve.amap.call.duration",
            unit="s",
            description="SmartServe AMap API call duration",
        )
        self.readiness_mongodb = self.meter.create_gauge(
            "smartserve.readiness.mongodb",
            description="MongoDB readiness state where one is ready",
        )
        self.readiness_redis = self.meter.create_gauge(
            "smartserve.readiness.redis",
            description="Redis readiness state where one is ready",
        )
        self.readiness_mongodb_duration = self.meter.create_histogram(
            "smartserve.readiness.mongodb.duration",
            unit="s",
            description="MongoDB readiness probe duration",
        )
        self.readiness_redis_duration = self.meter.create_histogram(
            "smartserve.readiness.redis.duration",
            unit="s",
            description="Redis readiness probe duration",
        )

    @staticmethod
    def now() -> float:
        return perf_counter()

    @staticmethod
    def elapsed(started_at: float) -> float:
        return max(0.0, perf_counter() - started_at)

    def record_amap_call(
        self,
        duration: float,
        *,
        operation: str,
        outcome: str,
        error_type: str | None = None,
    ) -> None:
        attributes = {
            "action": operation,
            "outcome": outcome,
        }
        if error_type:
            attributes["error.type"] = error_type
        self.amap_call_count.add(1, attributes)
        self.amap_call_duration.record(duration, attributes)

    def record_readiness(
        self,
        dependency: str,
        *,
        ready: bool,
        duration: float,
    ) -> None:
        gauge = getattr(self, f"readiness_{dependency}")
        duration_histogram = getattr(
            self,
            f"readiness_{dependency}_duration",
        )
        gauge.set(1 if ready else 0)
        duration_histogram.record(duration)


telemetry = ApplicationTelemetry()
