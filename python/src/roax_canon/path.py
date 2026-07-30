"""Path segments and the length-prefixed structured encoding (specification section 5).

There are no reserved characters and no escaping.
A key may contain ``.``, ``[`` or ``]`` and a key may be the empty string; the length
prefixes keep every such case provably distinct with no rejection rule at all
(specification section 5.1).

**The display path is never hashed** (specification section 5.2).
:func:`display_path` exists for humans and for disclosure requests.
Nothing in this package parses one, and :func:`encode_path` accepts segments only, so
the section 5.2 trap is unreachable through this API rather than merely discouraged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence, Union

from .errors import ErrorCode, PathError
from .text import nfc, utf8

__all__ = [
    "Key",
    "Index",
    "Segment",
    "Path",
    "MAX_INDEX_EXCLUSIVE",
    "encode_path",
    "display_path",
    "segments_from_json",
    "segments_to_json",
]

#: Specification section 5: array indices are 0-based and MUST be < 2^32.
MAX_INDEX_EXCLUSIVE = 2**32


@dataclass(frozen=True, slots=True)
class Key:
    """A map member. ``value`` is the key as received, before NFC."""

    value: str


@dataclass(frozen=True, slots=True)
class Index:
    """An array position. 0-based."""

    value: int


Segment = Union[Key, Index]
Path = tuple  # tuple[Segment, ...]; spelled loosely so the alias stays usable at runtime


def _u32be(n: int) -> bytes:
    return n.to_bytes(4, "big", signed=False)


def encode_path(segments: Sequence[Segment]) -> bytes:
    """The structured encoding that enters a hash preimage.

    ``u32be(count) ‖ per segment: KEY -> 0x01 ‖ u32be(len(utf8(NFC(k)))) ‖ utf8(NFC(k)),
    INDEX -> 0x02 ‖ u32be(i)``.

    An index that cannot be represented in 32 bits is an error rather than a truncation
    (specification section 5).
    """
    out = bytearray(_u32be(len(segments)))
    for position, seg in enumerate(segments):
        if isinstance(seg, Key):
            encoded = utf8(nfc(seg.value, where=f"path segment {position}"))
            out += b"\x01" + _u32be(len(encoded)) + encoded
        elif isinstance(seg, Index):
            if not isinstance(seg.value, int) or isinstance(seg.value, bool):
                raise PathError(
                    ErrorCode.INDEX_OUT_OF_32_BIT_RANGE,
                    f"array index at segment {position} is not an integer",
                )
            if seg.value < 0 or seg.value >= MAX_INDEX_EXCLUSIVE:
                raise PathError(
                    ErrorCode.INDEX_OUT_OF_32_BIT_RANGE,
                    f"array index {seg.value} is outside [0, 2^32)",
                )
            out += b"\x02" + _u32be(seg.value)
        else:
            raise PathError(
                ErrorCode.INDEX_OUT_OF_32_BIT_RANGE,
                f"segment {position} is neither Key nor Index: {seg!r}",
            )
    return bytes(out)


def display_path(segments: Sequence[Segment]) -> str:
    """The human-readable rendering, `a.b[0].c`.

    Display only.
    It MUST NOT enter any hash preimage and MUST NOT be parsed back into segments
    (specification section 5.2).
    """
    parts: list[str] = []
    for seg in segments:
        if isinstance(seg, Index):
            parts.append(f"[{seg.value}]")
        else:
            parts.append(seg.value if not parts else f".{seg.value}")
    return "".join(parts)


def segments_from_json(items: Any) -> tuple[Segment, ...]:
    """Read the `{"key": ...}` / `{"index": ...}` carrier the envelope and corpus use.

    An index arrives as :class:`~roax_canon.jsonio.JsonNumber` when the document was read
    through the literal-preserving reader, which it must be so that a full copy's
    ``record`` survives (specification section 7.3).
    An array index is a count rather than a record value, so it is converted here; doing
    it by an explicit call keeps the distinction visible.

    **Every shape here is attacker-controlled** (specification section 11.3), so the
    carrier is validated rather than trusted: this is the one choke point both an
    envelope's ``salts`` entries and its disclosed leaves reach, and an unvalidated member
    that reaches :func:`encode_path` raises out of a verifier instead of rejecting.
    A `KEY` segment must be a genuine JSON string for the same reason
    :func:`~roax_canon.jsonio.is_json_string` exists: ``{"key": 5}`` would otherwise carry
    a :class:`~roax_canon.jsonio.JsonNumber` and encode byte-identically to
    ``{"key": "5"}``.
    """
    from .jsonio import as_int, is_json_string

    if not isinstance(items, (list, tuple)):
        raise PathError(
            ErrorCode.ENVELOPE_SHAPE,
            f"a path is carried as an array of segments, got {type(items).__name__}",
        )

    out: list[Segment] = []
    for raw in items:
        if not isinstance(raw, dict) or len(raw) != 1:
            raise PathError(
                ErrorCode.ENVELOPE_SHAPE,
                f"path segment must be exactly one of key or index: {raw!r}",
            )
        if "key" in raw:
            if not is_json_string(raw["key"]):
                raise PathError(
                    ErrorCode.ENVELOPE_SHAPE,
                    f"a KEY segment is carried as a JSON string, got {raw['key']!r}",
                )
            out.append(Key(raw["key"]))
        elif "index" in raw:
            out.append(Index(as_int(raw["index"], field="path segment index")))
        else:
            raise PathError(
                ErrorCode.INDEX_OUT_OF_32_BIT_RANGE,
                f"path segment must be exactly one of key or index: {raw!r}",
            )
    return tuple(out)


def segments_to_json(segments: Sequence[Segment]) -> list[dict]:
    """Write the same carrier back out."""
    out: list[dict] = []
    for seg in segments:
        if isinstance(seg, Key):
            out.append({"key": seg.value})
        else:
            out.append({"index": seg.value})
    return out
