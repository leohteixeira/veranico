"""Money in a tool result as the model reads it: the centavos and their text (SPEC 9.3, 13).

A model that formats integer centavos itself slips into the other locale's separators, so
every `Money` value of a result (`{"amount_cents": <int>, "currency": "BRL"}`) is given to the
model with a `display` field, the amount written for the conversation's locale with centavos
shown. The model copies it. This is the model-facing copy only: the stored result, the
`tool_finished` event and the grounding sources are unchanged, and the text is grounded by
construction because it is laid out from the same digits.
"""

from collections.abc import Mapping

from veranico.shared.kernel.ids import Locale
from veranico.shared.kernel.money import format_money


def with_money_display(result: Mapping[str, object], locale: Locale) -> dict[str, object]:
    """A copy of `result` with a `display` text beside the centavos of every `Money` in it."""
    copied = {key: _walk(value, locale) for key, value in result.items()}
    amount = result.get("amount_cents")
    if type(amount) is int and result.get("currency") == "BRL":
        copied["display"] = format_money(amount, locale)
    return copied


def _walk(node: object, locale: Locale) -> object:
    if isinstance(node, Mapping):
        return with_money_display(node, locale)
    if isinstance(node, list | tuple):
        return [_walk(item, locale) for item in node]
    return node
