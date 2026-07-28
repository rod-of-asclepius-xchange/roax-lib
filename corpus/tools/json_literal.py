"""Literal-preserving JSON reader for implementation A.

Specification section 6.4: implementations MUST NOT parse record numbers through any
floating-point type. Python's mechanism is `json.loads` with `parse_int` and `parse_float`
hooks, which receive the verbatim source text of the literal, plus `object_pairs_hook`, which
receives the key/value pairs in document order and WITH duplicates intact so the flattener can
reject them (section 3.2).

Implementation B uses a different mechanism - a hand-written scanner - on purpose. Two readings
of the same bytes through two unrelated parsers is most of what the cross-check is worth.

Nothing here ever writes a record back out. Envelope fixtures splice the record's ORIGINAL
bytes rather than re-serializing them, because a re-serializer is one more place a number can
be destroyed and there is no reason to build one.
"""

from __future__ import annotations

import json

from roax_ref import NumberLiteral, RecordMap, RoaxError


def _reject_constant(text: str):
    # Section 3.2: NaN, Infinity and -Infinity MUST be rejected at the input boundary. Python's
    # json accepts all three by default, so this hook is load-bearing rather than decorative.
    raise RoaxError("non-finite-number", text)


def loads(text: str):
    """Parse JSON text into the record model roax_ref.flatten consumes."""
    return json.loads(
        text,
        parse_int=NumberLiteral,
        parse_float=NumberLiteral,
        parse_constant=_reject_constant,
        object_pairs_hook=RecordMap,
    )


def load_file(path) -> tuple:
    """Return (parsed record, original text). The text is what an envelope fixture splices."""
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    return loads(text), text
