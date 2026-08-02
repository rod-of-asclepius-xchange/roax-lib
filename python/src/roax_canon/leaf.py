"""Leaf construction (specification section 8).

::

    leafHash(path, tag, value, salt) = H(
          0x00                              // RFC 9162 leaf domain byte
        ‖ u32be(len(DOMAIN)) ‖ DOMAIN       // DOMAIN = "ROAX-CANON/1/" ‖ hashAlg
        ‖ u32be(len(P))      ‖ P            // P = encodePath(path)
        ‖ tag                               // one byte
        ‖ u32be(len(salt))   ‖ salt         // 16 bytes
        ‖ u64be(len(V))      ‖ V            // V = encoded value bytes (section 6)
    )

**There is exactly one leaf-preimage builder in this package, and it is
:func:`leaf_hash`.**
dogtag records the cost of the alternative plainly, at `dogtag-mono-repo`
``AGENTS.md:1747-1751``: "A second preimage builder is the drift".
Since decision D4 was ruled D4b there is no salt preimage either, so this is the only
one left in the design.

`DOMAIN` is algorithm-qualified.
``hashAlg`` is **not** a leaf and must never become one: a leaf is hashed under the
algorithm it names, so it cannot bind it (specification section 7.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .errors import ErrorCode, RoaxError
from .hashes import DEFAULT_HASH_ALG, HashAlgorithm, get_hash
from .path import Segment, encode_path
from .value import VALUELESS_TAGS, encode_value

__all__ = ["CANON", "SALT_BYTES", "domain_string", "Leaf", "leaf_hash"]

#: Specification section 1: the canonicalization version string.
CANON = "ROAX-CANON/1"

#: Specification section 7 pins the salt length at exactly 16 bytes, which is the
#: 128-bit entropy floor.
SALT_BYTES = 16


#: Leaf ordering, selected per record (specification section 9).
#:
#: Two first-class options, exactly as decision B makes ZK-friendly and non-ZK hashes both
#: first-class and selectable per record; the amended decision D5 rules ordering the same kind
#: of axis. ``path`` is the DEFAULT, and it is the same default in all five libraries because
#: section 9 makes that normative: a default differing between implementations would be the
#: silent divergence this project exists to prevent.
ORDERING_PATH = "path"
ORDERING_HASH = "hash"
DEFAULT_ORDERING = ORDERING_PATH

#: The domain suffix each ordering contributes to ``DOMAIN`` (specification sections 8 and 9).
#:
#: The asymmetry is a stated compatibility rule rather than an accident, and section 9.5 argues
#: it: ``path`` contributes the EMPTY string so that a path-ordered record's domain string is
#: byte-identical to what ``ROAX-CANON/1`` specified before this axis existed. Read the suffix
#: from this table; never derive it from the ordering's name.
ORDERING_DOMAIN_SUFFIX = {ORDERING_PATH: "", ORDERING_HASH: "/hash"}


def check_ordering(ordering: str) -> str:
    """Fail closed on an ordering this version does not define.

    This is H3 of specification section 9.5 at its narrowest: an unregistered ordering is
    refused rather than approximated by the default.
    """
    if ordering not in ORDERING_DOMAIN_SUFFIX:
        raise RoaxError(
            ErrorCode.ORDERING_NOT_DEFINED,
            f"ROAX-CANON/1 defines no leaf ordering named {ordering!r}",
        )
    return ordering


def domain_string(
    hash_alg: str = DEFAULT_HASH_ALG, ordering: str = DEFAULT_ORDERING
) -> bytes:
    """``"ROAX-CANON/1/" + hashAlg + ORD`` as ASCII (specification sections 7, 7.4, 8 and 9.5).

    Not a bare ``"ROAX-CANON/1"``, and algorithm-qualified AND ordering-qualified.
    One string with one length prefix: ``ORD`` is part of the domain rather than a component
    of its own.
    """
    return f"{CANON}/{hash_alg}{ORDERING_DOMAIN_SUFFIX[check_ordering(ordering)]}".encode("ascii")


@dataclass(frozen=True, slots=True)
class Leaf:
    """One ``(path, typeTag, value)`` triple.

    ``value`` is the carrier value in the form :func:`~roax_canon.value.encode_value`
    expects, and is ``None`` for the tags that carry none.
    The salt is deliberately *not* a member: it is drawn per leaf at issuance and stored
    alongside, and keeping it out of this structure makes it impossible to build a leaf
    whose salt travelled with it by accident.
    """

    path: tuple
    tag: int
    value: Any = None

    def __post_init__(self) -> None:
        if self.tag in VALUELESS_TAGS and self.value is not None:
            raise RoaxError(
                ErrorCode.ENVELOPE_SHAPE,
                "tags NULL, EMPTY_ARRAY and EMPTY_OBJECT carry no value",
            )


def _u32be(n: int) -> bytes:
    return n.to_bytes(4, "big", signed=False)


def _u64be(n: int) -> bytes:
    return n.to_bytes(8, "big", signed=False)


def leaf_hash(
    segments: Sequence[Segment],
    tag: int,
    value: Any,
    salt: bytes,
    *,
    hash_alg: str = DEFAULT_HASH_ALG,
    hasher: HashAlgorithm | None = None,
    ordering: str = DEFAULT_ORDERING,
) -> bytes:
    """The 32-byte leaf hash.

    ``ordering`` reaches this preimage ONLY through ``DOMAIN`` (specification section 9.5,
    H1), which is why a leaf is ordering-sensitive even though it carries no tree: a copy
    issued under one ordering and verified under the other fails here rather than at the
    tree.

    Every variable-length component is length-prefixed, so no two distinct
    ``(path, tag, salt, value)`` tuples share a preimage.

    The salt length is checked rather than assumed.
    A short salt still produces a verifiable leaf while silently removing the only
    defence a withheld low-entropy field has against a dictionary search
    (specification sections 7 and 10.1), so this is one of the few places where a
    permissive read would be invisible.
    """
    if not isinstance(salt, (bytes, bytearray)):
        raise RoaxError(ErrorCode.SALT_LENGTH, "salt must be bytes")
    if len(salt) != SALT_BYTES:
        raise RoaxError(
            ErrorCode.SALT_LENGTH,
            f"ROAX-CANON/1 pins the salt at {SALT_BYTES} bytes, got {len(salt)}",
        )

    h = hasher if hasher is not None else get_hash(hash_alg)
    domain = domain_string(h.name, ordering)
    encoded_path = encode_path(segments)
    encoded_value = encode_value(tag, value)

    preimage = b"".join(
        (
            b"\x00",
            _u32be(len(domain)),
            domain,
            _u32be(len(encoded_path)),
            encoded_path,
            bytes((tag,)),
            _u32be(len(salt)),
            bytes(salt),
            _u64be(len(encoded_value)),
            encoded_value,
        )
    )
    return h(preimage)
