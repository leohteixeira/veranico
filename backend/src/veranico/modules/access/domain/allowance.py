"""The visitor's daily allowance: limits, usage and the UTC day they belong to."""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta


@dataclass(frozen=True, slots=True)
class Limits:
    conversations: int
    messages: int


@dataclass(frozen=True, slots=True)
class Usage:
    conversations_used: int = 0
    messages_used: int = 0


def day_key(now: datetime) -> str:
    """The UTC day of `now` as `YYYYMMDD`."""
    return now.astimezone(UTC).strftime("%Y%m%d")


def resets_at(now: datetime) -> datetime:
    """The UTC midnight that ends the day of `now`."""
    today = now.astimezone(UTC).date()
    return datetime.combine(today + timedelta(days=1), time(0), tzinfo=UTC)


def remaining(limits: Limits, usage: Usage) -> tuple[int, int]:
    """Conversations and messages left, never negative.

    Usage above a limit happens when a visitor loses the boost during the day.
    """
    return (
        max(limits.conversations - usage.conversations_used, 0),
        max(limits.messages - usage.messages_used, 0),
    )


def consume(limits: Limits, usage: Usage, new_conversation: bool) -> Usage | None:
    """The usage after one more message, or `None` when a limit refuses it.

    A message always costs one message; one that opens a conversation also costs one
    conversation. Both limits are checked before anything is counted.
    """
    conversations_left, messages_left = remaining(limits, usage)
    if messages_left < 1 or (new_conversation and conversations_left < 1):
        return None
    return Usage(
        conversations_used=usage.conversations_used + int(new_conversation),
        messages_used=usage.messages_used + 1,
    )
