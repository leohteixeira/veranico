"""Domain errors: one class per stable code, with the HTTP status the problem mapper uses."""


class DomainError(Exception):
    code: str  # stable, snake_case
    status: int  # HTTP status used by the problem mapper
    retryable: bool = False

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.code)
        self.detail = detail


class NotFoundError(DomainError):
    code = "not_found"
    status = 404


class LocationNotFoundError(DomainError):
    code = "location_not_found"
    status = 404


class DatasetNotFoundError(DomainError):
    code = "dataset_not_found"
    status = 404


class ForbiddenError(DomainError):
    code = "forbidden"
    status = 403


class ConflictError(DomainError):
    code = "conflict"
    status = 409


class InvalidStateError(DomainError):
    code = "invalid_state"
    status = 409


class IdempotencyConflictError(DomainError):
    code = "idempotency_conflict"
    status = 409


class InvalidArgumentsError(DomainError):
    code = "invalid_arguments"
    status = 422


class InvalidCoverError(DomainError):
    code = "invalid_cover"
    status = 422


class InsufficientHistoryError(DomainError):
    code = "insufficient_history"
    status = 422


class OutsideCoverageError(DomainError):
    code = "outside_coverage"
    status = 422


class UnknownCarrierError(DomainError):
    code = "unknown_carrier"
    status = 422


class MessageTooLongError(DomainError):
    code = "message_too_long"
    status = 422


class LocationAmbiguousError(DomainError):
    code = "location_ambiguous"
    status = 422


class RateLimitedError(DomainError):
    code = "rate_limited"
    status = 429


class AllowanceExhaustedError(DomainError):
    code = "allowance_exhausted"
    status = 429


class SpendCeilingReachedError(DomainError):
    code = "spend_ceiling_reached"
    status = 429


class NotImplementedYetError(DomainError):
    """A route stub before its module lands."""

    code = "not_implemented"
    status = 501


class DeliveryFailedError(DomainError):
    code = "delivery_failed"
    status = 502


class WeatherSourceUnavailableError(DomainError):
    code = "weather_source_unavailable"
    status = 503
    retryable = True


class ModelUnavailableError(DomainError):
    code = "model_unavailable"
    status = 503
    retryable = True


class ShuttingDownError(DomainError):
    """An open stream ended by a graceful shutdown."""

    code = "shutting_down"
    status = 503
    retryable = True
