"""The index definition as it travels in a query string (SPEC 11.2, contracts section 10).

An `IndexDefinition` is flattened to `index_type`, `window_start`, `window_end`, `trigger`
and `exit`, so the generated client types each parameter.
"""

from typing import Annotated

from fastapi import Depends, Query

from veranico.modules.pricing.contracts import IndexDefinition, IndexType, Window


def index_from_query(
    index_type: IndexType,
    window_start: Annotated[str, Query(description="First day of the window, MM-DD.")],
    window_end: Annotated[str, Query(description="Last day of the window, MM-DD.")],
    trigger: float,
    exit: float,  # the wire name of the parameter, fixed by the contract
) -> IndexDefinition:
    return IndexDefinition(
        index_type=index_type,
        window=Window(start=window_start, end=window_end),
        trigger=trigger,
        exit=exit,
    )


IndexQuery = Annotated[IndexDefinition, Depends(index_from_query)]
