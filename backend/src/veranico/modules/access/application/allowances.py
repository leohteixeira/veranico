"""The visitor's daily allowance for the live agent."""

from datetime import datetime, timedelta

from veranico.modules.access.application.ports import AllowanceStore, SpendCeilings
from veranico.modules.access.contracts import Admission, Allowance, VisitorRef
from veranico.modules.access.domain import allowance as rules
from veranico.modules.access.domain.allowance import Limits, Usage
from veranico.shared.kernel.clock import Clock

# The usage document outlives its day by this long, so hashes do not accumulate.
_KEPT_AFTER_RESET = timedelta(days=1)


class Allowances:
    def __init__(
        self,
        store: AllowanceStore,
        ceilings: SpendCeilings,
        clock: Clock,
        *,
        limits: Limits,
        boosted_limits: Limits,
    ) -> None:
        self._store = store
        self._ceilings = ceilings
        self._clock = clock
        self._limits = {False: limits, True: boosted_limits}

    async def allowance(self, visitor: VisitorRef) -> Allowance:
        """What the visitor has left today. Never consumes."""
        now = self._clock.now()
        usage = await self._store.usage(visitor.ip_hash, rules.day_key(now))
        return self._view(visitor, usage, now)

    async def admit_message(self, visitor: VisitorRef, new_conversation: bool) -> Admission:
        """Admit one message of the visitor, consuming the allowance when it is admitted.

        The spend ceilings come first: a message a ceiling would refuse leaves the
        allowance untouched. The day key and `resets_at` come from one reading of the clock.
        """
        now = self._clock.now()
        day = rules.day_key(now)
        ceiling = await self._ceilings.reached()
        if ceiling is not None:
            usage = await self._store.usage(visitor.ip_hash, day)
            return Admission(
                allowed=False, reason=ceiling, allowance=self._view(visitor, usage, now)
            )
        usage, admitted = await self._store.consume(
            visitor.ip_hash,
            day,
            limits=self._limits[visitor.boosted],
            new_conversation=new_conversation,
            expires_at=rules.resets_at(now) + _KEPT_AFTER_RESET,
        )
        return Admission(
            allowed=admitted,
            reason="ok" if admitted else "visitor_allowance",
            allowance=self._view(visitor, usage, now),
        )

    def _view(self, visitor: VisitorRef, usage: Usage, now: datetime) -> Allowance:
        conversations_left, messages_left = rules.remaining(self._limits[visitor.boosted], usage)
        return Allowance(
            conversations_left=conversations_left,
            messages_left=messages_left,
            resets_at=rules.resets_at(now),
            boosted=visitor.boosted,
        )
