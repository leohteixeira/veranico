"""In-process cache of per-cell grids (SPEC 5.8), bounded, least recently used out first.

The bound matters: dragging the timeline asks for one grid per season and the agent tries
index definitions, so an unbounded cache would grow for as long as the process lives.
It is used from the event loop only, so it needs no lock.
"""

from collections import OrderedDict
from collections.abc import Hashable

from veranico.modules.pricing.contracts import CellGrid


class CellCache:
    def __init__(self, max_entries: int) -> None:
        if max_entries < 1:
            raise ValueError("the cell cache needs room for at least one entry")
        self._max_entries = max_entries
        self._entries: OrderedDict[Hashable, CellGrid] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: Hashable) -> CellGrid | None:
        grid = self._entries.get(key)
        if grid is not None:
            self._entries.move_to_end(key)
        return grid

    def put(self, key: Hashable, grid: CellGrid) -> None:
        self._entries[key] = grid
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()
