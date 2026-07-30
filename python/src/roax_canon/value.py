"""Type tags and value encoding (specification section 6).

The tag comes from the schema, never from the JSON literal's syntax
(specification section 4).
Nothing in this module inspects a literal to decide what it is; it is told the tag and
encodes accordingly, and it rejects a value that does not fit the tag it was given.
"""

from __future__ import annotations

import re
from typing import Any

from .errors import ErrorCode, GrammarError, InputError
from .numbers import canonical_decimal, canonical_integer
from .text import nfc, utf8

__all__ = [
    "NULL",
    "BOOL",
    "STRING",
    "INTEGER",
    "DECIMAL",
    "BYTES",
    "EMPTY_ARRAY",
    "EMPTY_OBJECT",
    "BLOB_REF",
    "TAG_NAMES",
    "VALUELESS_TAGS",
    "BlobRef",
    "encode_value",
    "decode_base64_canonical",
]

NULL = 0
BOOL = 1
STRING = 2
INTEGER = 3
DECIMAL = 4
BYTES = 5
EMPTY_ARRAY = 6
EMPTY_OBJECT = 7
BLOB_REF = 8

TAG_NAMES = {
    NULL: "NULL",
    BOOL: "BOOL",
    STRING: "STRING",
    INTEGER: "INTEGER",
    DECIMAL: "DECIMAL",
    BYTES: "BYTES",
    EMPTY_ARRAY: "EMPTY_ARRAY",
    EMPTY_OBJECT: "EMPTY_OBJECT",
    BLOB_REF: "BLOB_REF",
}

#: The tags whose encoded value is empty and which therefore carry no value at all.
#: Specification section 6.1, and the envelope schema's conditional on `disclosedLeaf`.
VALUELESS_TAGS = frozenset({NULL, EMPTY_ARRAY, EMPTY_OBJECT})

# RFC 4648 section 4: the standard alphabet, with padding and no line wrapping.
# Anchored \A and \Z rather than ^ and $, because Python's $ also matches before a
# trailing newline and a wrapped line is exactly what this pin forbids.
_BASE64_CANONICAL = re.compile(
    r"\A(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}=={1}|[A-Za-z0-9+/]{3}={1})?\Z"
)
_BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


class BlobRef:
    """The value carrier for tag 8 (specification section 6.5).

    Registered and selected by no version-1 profile.
    The carrier form is pinned here so it does not have to be retrofitted after five
    independent implementations exist; the *prohibition* lives one layer up, in the record
    and envelope paths, which reject a map binding a path to tag 8 and an envelope
    carrying a tag-8 leaf.
    """

    __slots__ = ("blob_byte_length", "blob_digest")

    def __init__(self, blob_byte_length: str | int, blob_digest: bytes) -> None:
        length = str(blob_byte_length)
        # The length is a hash-preimage input, so it travels as a canonical integer
        # string for the same reason every other number in this design does.
        self.blob_byte_length = int(canonical_integer(length))
        if self.blob_byte_length < 0:
            raise GrammarError(ErrorCode.INTEGER_GRAMMAR, "blobByteLength must not be negative")
        if not isinstance(blob_digest, (bytes, bytearray)):
            raise GrammarError(ErrorCode.ENVELOPE_SHAPE, "blobDigest must be bytes")
        self.blob_digest = bytes(blob_digest)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, BlobRef)
            and other.blob_byte_length == self.blob_byte_length
            and other.blob_digest == self.blob_digest
        )

    def __hash__(self) -> int:
        return hash((self.blob_byte_length, self.blob_digest))


def decode_base64_canonical(text: str) -> bytes:
    """Decode base64 in the one form `ROAX-CANON/1` pins (specification section 6.3).

    RFC 4648 section 4: the standard alphabet, with padding, and no line wrapping.
    Rejects the URL-safe alphabet of RFC 4648 section 5, absent or excess padding, any
    line break or other character outside the alphabet, and a final quantum whose unused
    bits are non-zero, which RFC 4648 section 3.5 identifies as the non-canonical case.

    Python's :func:`base64.b64decode` with ``validate=True`` closes the alphabet and the
    length, and does **not** close the trailing-bits case, so that check is explicit here.
    """
    if not isinstance(text, str):
        raise GrammarError(ErrorCode.BASE64_NOT_CANONICAL, "base64 input must be a string")
    if _BASE64_CANONICAL.match(text) is None:
        raise GrammarError(
            ErrorCode.BASE64_NOT_CANONICAL,
            "not RFC 4648 section 4 base64 with padding and no line wrapping",
        )
    if len(text) % 4 != 0:
        raise GrammarError(ErrorCode.BASE64_NOT_CANONICAL, "base64 length is not a multiple of 4")

    if text.endswith("=="):
        # One byte in the final quantum: the second character carries 2 significant bits
        # and 4 unused ones, which RFC 4648 section 3.5 requires to be zero.
        if _BASE64_ALPHABET.index(text[-3]) & 0x0F:
            raise GrammarError(
                ErrorCode.BASE64_NOT_CANONICAL, "non-zero unused bits in the final quantum"
            )
    elif text.endswith("="):
        # Two bytes in the final quantum: the third character carries 4 significant bits
        # and 2 unused ones.
        if _BASE64_ALPHABET.index(text[-2]) & 0x03:
            raise GrammarError(
                ErrorCode.BASE64_NOT_CANONICAL, "non-zero unused bits in the final quantum"
            )

    import base64

    return base64.b64decode(text, validate=True)


def _u32be(n: int) -> bytes:
    return n.to_bytes(4, "big", signed=False)


def _u64be(n: int) -> bytes:
    return n.to_bytes(8, "big", signed=False)


def encode_value(tag: int, value: Any = None) -> bytes:
    """The encoded value bytes for a tag (specification section 6.1).

    ============  ====================================================
    Tag           Encoded value bytes
    ============  ====================================================
    0 NULL        empty
    1 BOOL        ``0x01`` if true, ``0x00`` if false
    2 STRING      ``utf8(NFC(s))``
    3 INTEGER     ASCII canonical integer
    4 DECIMAL     ASCII canonical decimal
    5 BYTES       the bytes themselves
    6 EMPTY_ARRAY empty
    7 EMPTY_OBJECT empty
    8 BLOB_REF    ``u64be(len) ‖ u32be(len(digest)) ‖ digest``
    ============  ====================================================
    """
    if tag in VALUELESS_TAGS:
        if value is not None:
            raise GrammarError(
                ErrorCode.ENVELOPE_SHAPE,
                f"tag {TAG_NAMES[tag]} carries no value (specification section 6.1)",
            )
        return b""

    if tag == BOOL:
        if not isinstance(value, bool):
            raise GrammarError(ErrorCode.ENVELOPE_SHAPE, "BOOL value must be a boolean")
        return b"\x01" if value else b"\x00"

    if tag == STRING:
        if not isinstance(value, str):
            raise GrammarError(ErrorCode.ENVELOPE_SHAPE, "STRING value must be a string")
        return utf8(nfc(value, where="STRING value"))

    if tag == INTEGER:
        return canonical_integer(value).encode("ascii")

    if tag == DECIMAL:
        return canonical_decimal(value).encode("ascii")

    if tag == BYTES:
        if not isinstance(value, (bytes, bytearray)):
            raise GrammarError(ErrorCode.ENVELOPE_SHAPE, "BYTES value must be bytes")
        return bytes(value)

    if tag == BLOB_REF:
        if not isinstance(value, BlobRef):
            raise GrammarError(ErrorCode.ENVELOPE_SHAPE, "BLOB_REF value must be a BlobRef")
        return _u64be(value.blob_byte_length) + _u32be(len(value.blob_digest)) + value.blob_digest

    raise InputError(ErrorCode.ENVELOPE_SHAPE, f"unknown type tag {tag!r}")
