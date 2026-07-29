"""A JSON reader that does not destroy the record (specification sections 3.2 and 6.4).

> **Normative:** implementations MUST NOT parse record numbers through any floating-point
> type (specification section 6.4).

Python's :mod:`json` violates that by default in three separate ways, and each has to be
closed explicitly:

1. ``parse_float`` defaults to :class:`float`, so ``0.010`` becomes ``0.01`` and
   ``9223372036854775807`` becomes ``9223372036854776000`` before any of this
   specification's rules run.
2. ``parse_constant`` defaults to producing ``float("nan")`` and ``float("inf")``, so
   ``NaN``, ``Infinity`` and ``-Infinity`` are *accepted*, which specification section
   3.2 forbids.
3. The default object hook is :class:`dict`, which silently keeps the last of a set of
   duplicate keys.
   Specification section 3.2 requires the duplicate to be REJECTED, and the
   OpenAttestation audit (section 9.8) demonstrates the concrete harm of resolving it
   quietly.

There is a fourth hazard that is specific to the obvious fix.
Passing ``parse_int=str, parse_float=str`` preserves the literal correctly and then
collapses the JSON number ``5`` and the JSON string ``"5"`` into the same Python value.
That matters because the type map is keyed on the observed JSON kind (specification
section 4.2), so a collapsed representation resolves the wrong tag.
`corpus/fixtures/records/typed-scalars.json` is built to catch exactly this: it carries
``{"counts": {"integer": 5, "decimal": 0.010, "text": "5"}}`` and the map binds
``counts.integer`` at kind ``number`` and ``counts.text`` at kind ``string``.
:class:`JsonNumber` is the distinct carrier that keeps the two apart, so
:func:`json_kind` reads the Python type and never re-inspects the text.
"""

from __future__ import annotations

import json
from typing import Any

from .errors import ErrorCode, InputError
from .text import has_unpaired_surrogate

__all__ = ["JsonNumber", "loads", "load_file", "json_kind", "as_int"]


class JsonNumber(str):
    """A JSON numeric literal, carried verbatim as text.

    A subclass of :class:`str` so the literal is trivially available, and a *distinct*
    type so that a JSON number is never confused with a JSON string.
    Both distinctions are load-bearing: the first is specification section 6.4, the second
    is the type-map lookup key of specification section 4.2.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"JsonNumber({str.__repr__(self)})"


def _reject_constant(name: str) -> Any:
    raise InputError(
        ErrorCode.NON_FINITE_NUMBER,
        f"{name} is not an admissible value (specification section 3.2)",
    )


def _pairs_hook(pairs: list[tuple[str, Any]]) -> dict:
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise InputError(
                ErrorCode.DUPLICATE_KEY,
                f"duplicate object member name {key!r}",
            )
        seen.add(key)
    return dict(pairs)


def _check_surrogates(node: Any, where: str) -> None:
    """Reject unpaired surrogates at the input boundary (specification section 3.2).

    A JSON text may carry ``\\ud800`` as an escape, and Python's decoder produces a lone
    surrogate in the resulting :class:`str` without complaint.
    Left alone, it would survive normalization and only fail at UTF-8 encoding, which is
    after the reserved-namespace guard of specification section 11.2 has already run.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if has_unpaired_surrogate(key):
                raise InputError(
                    ErrorCode.UNPAIRED_SURROGATE,
                    f"object member name at {where} carries an unpaired surrogate",
                )
            _check_surrogates(value, f"{where}/{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _check_surrogates(item, f"{where}/{i}")
    elif isinstance(node, str) and not isinstance(node, JsonNumber):
        if has_unpaired_surrogate(node):
            raise InputError(
                ErrorCode.UNPAIRED_SURROGATE,
                f"string value at {where} carries an unpaired surrogate",
            )


def loads(text: str | bytes) -> Any:
    """Parse JSON text, preserving numeric literals and rejecting what section 3.2 lists.

    Accepts :class:`str` or :class:`bytes`.
    Bytes are decoded as strict UTF-8, so an invalid sequence is a rejection rather than a
    replacement character.
    """
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InputError(ErrorCode.MALFORMED_JSON, f"not valid UTF-8: {exc}") from exc
    try:
        parsed = json.loads(
            text,
            parse_int=JsonNumber,
            parse_float=JsonNumber,
            parse_constant=_reject_constant,
            object_pairs_hook=_pairs_hook,
        )
    except InputError:
        raise
    except json.JSONDecodeError as exc:
        raise InputError(ErrorCode.MALFORMED_JSON, str(exc)) from exc
    _check_surrogates(parsed, "")
    return parsed


def load_file(path: str) -> Any:
    """Read and parse a file with :func:`loads`."""
    with open(path, "rb") as handle:
        return loads(handle.read())


def json_kind(node: Any) -> str:
    """The observed JSON kind, as the type map keys on (specification section 4.2).

    ``bool`` is tested before ``JsonNumber`` because Python's :class:`bool` is a subclass
    of :class:`int`; the ordering is defensive rather than reachable, since this reader
    never produces a bare :class:`int`.
    """
    if node is None:
        return "null"
    if isinstance(node, bool):
        return "boolean"
    if isinstance(node, JsonNumber):
        return "number"
    if isinstance(node, str):
        return "string"
    if isinstance(node, dict):
        return "object"
    if isinstance(node, list):
        return "array"
    if isinstance(node, (int, float)):
        # Reachable only if a caller hands in a Python-native structure rather than one
        # this reader produced. A float here has already lost the literal, so it is a
        # rejection rather than a coercion.
        raise InputError(
            ErrorCode.NON_FINITE_NUMBER,
            "record numbers must be carried as JsonNumber, not as a Python numeric type "
            "(specification section 6.4)",
        )
    raise InputError(ErrorCode.MALFORMED_JSON, f"not an admissible value: {node!r}")


def as_int(value: Any, *, field: str) -> int:
    """Read an envelope field that is genuinely an integer count or index.

    The whole envelope is read through :func:`loads` so that a full copy's ``record``
    keeps its literals (specification section 7.3), which means ``leafCount`` and
    ``index`` arrive as :class:`JsonNumber` too.
    They are counts rather than record values, so converting them here is correct; doing
    it by an explicit call keeps that decision visible.
    """
    if isinstance(value, bool) or not isinstance(value, (JsonNumber, int)):
        raise InputError(ErrorCode.ENVELOPE_SHAPE, f"{field} must be an integer")
    if isinstance(value, JsonNumber):
        from .numbers import INTEGER_GRAMMAR

        if INTEGER_GRAMMAR.match(value) is None:
            raise InputError(ErrorCode.ENVELOPE_SHAPE, f"{field} must be an integer")
        return int(value)
    return value
