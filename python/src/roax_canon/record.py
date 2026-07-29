"""The reserved leaves, the union, the ordering and the root.

**The leaf set is not the record alone** (specification section 3.3)::

    leaves(envelope, record) = reservedLeaves(envelope) U flatten(record, [])

The union is formed **before** the sort, so reserved and record leaves are ordered
together by encoded path and are indistinguishable to the tree function.
An implementation that flattens the record only produces a different root.

**Each reserved path is a SINGLE `KEY` segment carrying the literal dotted string**
(specification section 11.2).
``roax.recordType`` is one segment ``KEY("roax.recordType")``, not two.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .errors import ErrorCode, InputError, RoaxError
from .flatten import flatten
from .hashes import DEFAULT_HASH_ALG, get_hash
from .leaf import SALT_BYTES, Leaf, leaf_hash
from .path import Key, Segment, display_path, encode_path
from .text import nfc
from .tree import merkle_tree_head
from .typemap import TypeResolver
from .value import STRING

__all__ = [
    "RESERVED_V1",
    "RESERVED_V2",
    "RecordIdentity",
    "reserved_leaves",
    "order_leaves",
    "SaltSource",
    "MappingSalts",
    "PositionalSalts",
    "draw_salt",
    "build_tree",
    "issue",
    "normalized_equal",
    "BuiltRecord",
]

#: The reserved leaf set `schemas/envelope-1.0.json` governs: four always-emitted leaves
#: plus the one conditional leaf.
#: This is what the committed conformance corpus was built against.
RESERVED_V1 = "envelope-1.0"

#: The reserved leaf set `schemas/envelope-2.0.json` governs, which adds
#: ``roax.typeMap.id`` as a fifth always-emitted leaf (specification sections 4.2 and
#: 11.2).
#: No committed corpus vector exercises it; `AGENTS.md` records closing that difference as
#: corpus-rebuild work.
RESERVED_V2 = "envelope-2.0"


@dataclass(frozen=True, slots=True)
class RecordIdentity:
    """The envelope fields that are committed inside the root.

    ``issuer_key_id`` is the one conditional leaf: **an absent ``issuer.keyId`` emits no
    leaf**, and it MUST NOT be emitted as a NULL leaf or as an empty string, because those
    are three different roots and only one of them can be right (specification section
    11.2).

    ``type_map_id`` is always emitted under :data:`RESERVED_V2` and is absent under
    :data:`RESERVED_V1`.
    """

    record_type: str
    schema_version: str
    record_id: str
    issuer_id: str
    issuer_key_id: str | None = None
    type_map_id: str | None = None


def reserved_leaves(identity: RecordIdentity, *, reserved_set: str = RESERVED_V1) -> list[Leaf]:
    """The fixed reserved leaf set (specification section 11.2, table).

    Every reserved leaf is tag 2 STRING, so every value is normalized to NFC and encoded
    per section 6.1 like any other string.
    """
    if reserved_set not in (RESERVED_V1, RESERVED_V2):
        raise RoaxError(ErrorCode.ENVELOPE_SHAPE, f"unknown reserved leaf set {reserved_set!r}")

    out = [
        Leaf((Key("roax.recordType"),), STRING, identity.record_type),
        Leaf((Key("roax.schemaVersion"),), STRING, identity.schema_version),
    ]
    if reserved_set == RESERVED_V2:
        if identity.type_map_id is None:
            raise RoaxError(
                ErrorCode.ENVELOPE_SHAPE,
                "roax.typeMap.id is always emitted under the envelope 2.0 reserved set",
            )
        out.append(Leaf((Key("roax.typeMap.id"),), STRING, identity.type_map_id))
    out.append(Leaf((Key("roax.recordId"),), STRING, identity.record_id))
    out.append(Leaf((Key("roax.issuer.id"),), STRING, identity.issuer_id))
    if identity.issuer_key_id is not None:
        out.append(Leaf((Key("roax.issuer.keyId"),), STRING, identity.issuer_key_id))
    return out


def order_leaves(leaves: Iterable[Leaf]) -> list[tuple[bytes, Leaf]]:
    """Order leaves by ascending ``encodePath`` bytes, plain unsigned byte comparison.

    Sorting encoded paths sorts by (segment count, then segment kind, then key length,
    then key bytes), so the resulting order is a deterministic total order and is **not**
    alphabetical (specification section 5.3).

    Paths are unique by construction, so the order is total and tie-free, and a duplicate
    is a defect rather than a tie to break.
    The one reachable way to produce one is two record keys that differ only in Unicode
    normalization form: they are distinct JSON member names and the same path once NFC is
    applied (specification section 6.1).
    """
    pairs = [(encode_path(leaf.path), leaf) for leaf in leaves]
    pairs.sort(key=lambda pair: pair[0])
    for i in range(1, len(pairs)):
        if pairs[i][0] == pairs[i - 1][0]:
            raise InputError(
                ErrorCode.DUPLICATE_PATH,
                f"two leaves share the encoded path {display_path(pairs[i][1].path)!r}; "
                f"keys differing only in normalization form collapse under NFC",
            )
    return pairs


def draw_salt() -> bytes:
    """One salt: 16 bytes from a CSPRNG, drawn independently (specification section 7).

    There is no derivation, no key derivation function, no master secret and no preimage
    (ruled decision D4b).

    :mod:`secrets` is Python's CSPRNG interface and is what the 128-bit entropy floor
    requires.
    :mod:`random` would satisfy every check in this library and every conformance vector
    while silently removing the only defence a withheld low-entropy leaf has, so it is
    named here rather than left to a reader's judgement.
    """
    return secrets.token_bytes(SALT_BYTES)


class SaltSource:
    """Where a leaf's salt comes from.

    Verification never regenerates a salt; it reads the salt that travelled with the leaf
    (specification section 7.3).
    """

    def salt_for(self, encoded_path: bytes, leaf: Leaf) -> bytes:  # pragma: no cover
        raise NotImplementedError


class MappingSalts(SaltSource):
    """Salts addressed by their leaf's structured path, as the ``salts`` array carries them."""

    def __init__(self, by_path: dict[bytes, bytes]) -> None:
        self._by_path = by_path

    def salt_for(self, encoded_path: bytes, leaf: Leaf) -> bytes:
        try:
            return self._by_path[encoded_path]
        except KeyError:
            raise RoaxError(
                ErrorCode.SALT_MISSING_FOR_LEAF,
                f"no salt for leaf {display_path(leaf.path)!r}",
            ) from None


class PositionalSalts(SaltSource):
    """Salts paired by position in encoded-path order.

    Specification section 7.2 rejects this pairing **for an envelope**, because it makes
    salt-to-leaf pairing depend on the reader reproducing the section 9 sort before it can
    read the salts at all.
    In a corpus vector reproducing that sort IS the thing under test, so the same property
    that makes it dangerous in an envelope makes it valid there.
    Nothing in this package emits it.
    """

    def __init__(self, salts: Sequence[bytes]) -> None:
        self._salts = list(salts)
        self._next = 0

    def salt_for(self, encoded_path: bytes, leaf: Leaf) -> bytes:
        if self._next >= len(self._salts):
            raise RoaxError(
                ErrorCode.SALT_MISSING_FOR_LEAF,
                f"positional salt set exhausted at {display_path(leaf.path)!r}",
            )
        salt = self._salts[self._next]
        self._next += 1
        return salt


@dataclass(frozen=True, slots=True)
class BuiltRecord:
    """The result of committing a record: the ordered leaves, their hashes and the root."""

    leaves: tuple[Leaf, ...]
    encoded_paths: tuple[bytes, ...]
    salts: tuple[bytes, ...]
    leaf_hashes: tuple[bytes, ...]
    root: bytes

    @property
    def leaf_count(self) -> int:
        return len(self.leaves)

    def index_of(self, segments: Sequence[Segment]) -> int:
        """The leaf index for a path, or raise."""
        target = encode_path(segments)
        for i, encoded in enumerate(self.encoded_paths):
            if encoded == target:
                return i
        raise RoaxError(
            ErrorCode.SALT_MISSING_FOR_LEAF, f"no leaf at {display_path(segments)!r}"
        )


def build_tree(
    record: Any,
    identity: RecordIdentity,
    resolver: TypeResolver,
    salts: SaltSource,
    *,
    hash_alg: str = DEFAULT_HASH_ALG,
    reserved_set: str = RESERVED_V1,
    authorize_empty_containers: bool = True,
) -> BuiltRecord:
    """Flatten, union, order, hash and merklize.

    This is the whole of steps (A) through (D) of specification section 3.1.
    """
    hasher = get_hash(hash_alg)
    record_leaves = flatten(
        record, resolver, authorize_empty_containers=authorize_empty_containers
    )
    all_leaves = record_leaves + reserved_leaves(identity, reserved_set=reserved_set)
    ordered = order_leaves(all_leaves)

    encoded_paths = tuple(pair[0] for pair in ordered)
    leaves = tuple(pair[1] for pair in ordered)
    drawn = tuple(salts.salt_for(path, leaf) for path, leaf in zip(encoded_paths, leaves))
    hashes = tuple(
        leaf_hash(leaf.path, leaf.tag, leaf.value, salt, hasher=hasher)
        for leaf, salt in zip(leaves, drawn)
    )
    root = merkle_tree_head(hashes, hasher=hasher)
    return BuiltRecord(leaves, encoded_paths, drawn, hashes, root)


def issue(
    record: Any,
    identity: RecordIdentity,
    resolver: TypeResolver,
    *,
    hash_alg: str = DEFAULT_HASH_ALG,
    reserved_set: str = RESERVED_V1,
) -> BuiltRecord:
    """Commit a record, drawing one independent CSPRNG salt per leaf.

    Salts are generated by the protocol, not supplied by the issuing institution
    (specification section 7).
    """

    class _Fresh(SaltSource):
        def salt_for(self, encoded_path: bytes, leaf: Leaf) -> bytes:
            return draw_salt()

    return build_tree(
        record,
        identity,
        resolver,
        _Fresh(),
        hash_alg=hash_alg,
        reserved_set=reserved_set,
    )


def normalized_equal(a: str, b: str) -> bool:
    """Compare two identity strings the way a committed STRING leaf compares.

    A STRING leaf commits its NFC-normalized form (specification section 6.1), so binding
    an outer envelope field to a reserved leaf must normalize **both** sides or the check
    is comparing a different string from the one the root committed.
    """
    return nfc(a, where="identity field") == nfc(b, where="identity field")
