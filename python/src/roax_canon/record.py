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

from copy import deepcopy
import secrets
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .errors import ErrorCode, InputError, RoaxError
from .flatten import flatten
from .hashes import DEFAULT_HASH_ALG, get_hash
from .jsonio import is_json_string, is_record_type_string, is_uri_string
from .leaf import (
    DEFAULT_ORDERING,
    SALT_BYTES,
    Leaf,
    check_ordering,
    leaf_hash,
)
from .path import Key, Segment, display_path, encode_path
from .text import nfc
from .tree import merkle_tree_head
from .typemap import DisplayPatternTypeMap, TypeResolver
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
#: plus the conditional ones section 11.2 states.
#: This is what the committed conformance corpus was built against.
RESERVED_V1 = "envelope-1.0"

#: The reserved leaf set `schemas/envelope-2.0.json` governs, which adds
#: ``roax.typeMap.id`` as a fifth always-emitted leaf (specification sections 4.2 and
#: 11.2).
#: No committed corpus vector exercises it; `AGENTS.md` records closing that difference as
#: corpus-rebuild work.
#: The constant and :func:`reserved_leaves` retain this structural model for an eventual
#: artifact-aware implementation.
#: :func:`build_tree` and :func:`issue` reject it today because specification section 4.2
#: requires exact structured-path DFA selection by a reproduced content ID, which this
#: package does not implement.
RESERVED_V2 = "envelope-2.0"


@dataclass(frozen=True, slots=True)
class RecordIdentity:
    """The envelope fields that are committed inside the root.

    ``issuer_key_id`` is a conditional leaf: **an absent ``issuer.keyId`` emits no
    leaf**, and it MUST NOT be emitted as a NULL leaf or as an empty string, because those
    are three different roots and only one of them can be right (specification section
    11.2).

    ``type_map_id`` is required when :func:`reserved_leaves` models
    :data:`RESERVED_V2` and is absent from :data:`RESERVED_V1`.
    ``type_map_version`` travels beside it because the envelope's ``typeMap`` member carries
    both, and an issuance that committed the identifier without presenting the member would
    emit a copy its own verifier rejects for ``outer-identity-mismatch``.
    Both are therefore REQUIRED TOGETHER at emission and
    :func:`roax_canon.disclose.full_copy` fails closed without either, because
    `schemas/envelope-1.0.json` requires ``id`` and ``version`` together whenever ``typeMap``
    is present; they stay optional here so :data:`RESERVED_V1` needs neither.
    It is NOT a leaf and is not committed: the content ID transitively binds every artifact
    byte, including that version (specification section 12.1).
    """

    record_type: str
    schema_version: str
    record_id: str
    issuer_id: str
    issuer_key_id: str | None = None
    type_map_id: str | None = None
    type_map_version: str | None = None
    #: The record's leaf ordering, committed at ``roax.ordering`` (specification section 11.2).
    #:
    #: The SECOND conditional reserved leaf. It is emitted only when the ordering is not the
    #: default ``path``; a path-ordered record emits NO ordering leaf and must not emit
    #: ``"path"``, a NULL or an empty string in its place, because those are different roots
    #: and only one can be right. The conditionality is the same ``ROAX-CANON/1``
    #: compatibility rule that gives ``path`` an empty domain suffix, and section 11.2 argues
    #: it rather than leaving it to be reverse-engineered.
    #:
    #: THIS LEAF IS NOT AUTHORITY. It is written from the ordering supplied here and is never
    #: read back to select one: a verifier takes the ordering from the anchoring registry
    #: (section 9.5, H2). Section 11.2 argues why committing it is not section 7.4's rejected
    #: ``roax.hashAlg`` leaf under a new name - weak hash algorithms exist so that leaf enabled
    #: a downgrade, whereas both orderings are equally strong, so this one is redundant rather
    #: than dangerous and what it buys is committed issuer intent.
    ordering: str = DEFAULT_ORDERING

    def __post_init__(self) -> None:
        """Reject a JSON-number carrier anywhere an identity requires a string.

        :class:`~roax_canon.jsonio.JsonNumber` subclasses :class:`str`, so annotations
        and a bare ``isinstance(value, str)`` check both accept it.
        That would let issuance emit an envelope whose own verifier rejects even though
        the reserved STRING leaf hashes to the same bytes (specification sections 6.4,
        11.2 and 11.3).
        """
        required = (
            ("record_type", self.record_type),
            ("schema_version", self.schema_version),
            ("record_id", self.record_id),
            ("issuer_id", self.issuer_id),
        )
        optional = (
            ("issuer_key_id", self.issuer_key_id),
            ("type_map_id", self.type_map_id),
            ("type_map_version", self.type_map_version),
        )
        for field_name, value in required:
            if not is_json_string(value):
                raise RoaxError(
                    ErrorCode.ENVELOPE_SHAPE,
                    f"RecordIdentity.{field_name} must be a genuine JSON string",
                )
            if field_name in ("schema_version", "record_id") and not value:
                raise RoaxError(
                    ErrorCode.ENVELOPE_SHAPE,
                    f"RecordIdentity.{field_name} must not be empty",
                )
            if field_name == "record_type" and not is_record_type_string(value):
                raise RoaxError(
                    ErrorCode.ENVELOPE_SHAPE,
                    "RecordIdentity.record_type must be a lowercase reverse-DNS profile name",
                )
            if field_name == "issuer_id" and not is_uri_string(value):
                raise RoaxError(
                    ErrorCode.ENVELOPE_SHAPE,
                    "RecordIdentity.issuer_id must be an absolute URI",
                )
        for field_name, value in optional:
            if value is not None and not is_json_string(value):
                raise RoaxError(
                    ErrorCode.ENVELOPE_SHAPE,
                    f"RecordIdentity.{field_name} must be a genuine JSON string when present",
                )


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
    if check_ordering(identity.ordering) != DEFAULT_ORDERING:
        out.append(Leaf((Key("roax.ordering"),), STRING, identity.ordering))
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
class _FrozenObject:
    items: tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class _FrozenArray:
    items: tuple[Any, ...]


def _freeze_record(node: Any) -> Any:
    """Recursively remove every mutable container from an internal record snapshot."""
    if isinstance(node, dict):
        return _FrozenObject(tuple((key, _freeze_record(value)) for key, value in node.items()))
    if isinstance(node, list):
        return _FrozenArray(tuple(_freeze_record(value) for value in node))
    return node


def _thaw_record(node: Any) -> Any:
    """Rebuild ordinary JSON containers while preserving scalar carrier types."""
    if isinstance(node, _FrozenObject):
        return {key: _thaw_record(value) for key, value in node.items}
    if isinstance(node, _FrozenArray):
        return [_thaw_record(value) for value in node.items]
    return node


def _bind_builtin_resolver(identity: RecordIdentity, resolver: TypeResolver) -> None:
    """Bind the built-in map's declared scope to the identity being committed."""
    if not isinstance(resolver, DisplayPatternTypeMap):
        return
    disagreements = []
    if resolver.record_type != identity.record_type:
        disagreements.append(f"recordType {resolver.record_type!r} != {identity.record_type!r}")
    if resolver.schema_version != identity.schema_version:
        disagreements.append(
            f"schemaVersion {resolver.schema_version!r} != {identity.schema_version!r}"
        )
    if disagreements:
        raise RoaxError(
            ErrorCode.TYPE_MAP_REJECTED,
            f"{resolver.source}: type-map metadata does not match the record identity: "
            + "; ".join(disagreements)
            + " (specification sections 4.2 and 12.1)",
        )


@dataclass(frozen=True, slots=True)
class BuiltRecord:
    """A commitment together with the exact context from which it was issued.

    Envelope construction derives the original record, identity, hash algorithm and
    reserved leaf set from this object.
    It accepts no replacement context, because mixing independently safe values from two
    issuances can produce an envelope whose own verifier rejects at outer-identity
    binding (specification sections 10 and 11.3).

    The private record snapshot recursively replaces mutable containers, and
    :meth:`record_copy` reconstructs fresh JSON containers for each caller.
    That preserves :class:`~roax_canon.jsonio.JsonNumber` while preventing mutation of
    the caller's record, or of one emitted full copy, from changing a later envelope.
    """

    leaves: tuple[Leaf, ...]
    encoded_paths: tuple[bytes, ...]
    salts: tuple[bytes, ...]
    leaf_hashes: tuple[bytes, ...]
    root: bytes
    identity: RecordIdentity
    hash_alg: str
    reserved_set: str
    _record_snapshot: Any = field(repr=False, compare=False)

    @property
    def leaf_count(self) -> int:
        return len(self.leaves)

    def record_copy(self) -> Any:
        """Return an isolated copy of the exact record committed into this root."""
        return _thaw_record(self._record_snapshot)

    def index_of(self, segments: Sequence[Segment]) -> int:
        """The leaf index for a path, or raise."""
        target = encode_path(segments)
        for i, encoded in enumerate(self.encoded_paths):
            if encoded == target:
                return i
        raise RoaxError(ErrorCode.SALT_MISSING_FOR_LEAF, f"no leaf at {display_path(segments)!r}")


def _tree_order(
    ordering: str,
    encoded_paths: tuple[bytes, ...],
    leaves: tuple[Leaf, ...],
    salts: tuple[bytes, ...],
    hashes: tuple[bytes, ...],
) -> tuple[tuple[bytes, ...], tuple[Leaf, ...], tuple[bytes, ...], tuple[bytes, ...]]:
    """Reorder from salt-assignment order into TREE order (specification section 9).

    ``path`` is the identity, because salt-assignment order already is ``encodePath`` order.
    ``hash`` sorts by ascending leaf-hash bytes.

    A leaf's INDEX is its position in the tree, because that is what a disclosed copy carries
    and what an audit path is drawn against, so every parallel tuple is reordered together.

    Equal leaf hashes are REJECTED rather than tie-broken. Paths are unique already and every
    variable component of the section 8 preimage is length-prefixed, so two equal hashes over
    distinct paths are a collision; breaking the tie by path would absorb evidence of a broken
    hash into a well-defined tree and hand back a root, which section 9 forbids by name.
    """
    if check_ordering(ordering) == DEFAULT_ORDERING:
        return encoded_paths, leaves, salts, hashes
    if len(set(hashes)) != len(hashes):
        raise RoaxError(
            ErrorCode.LEAF_HASH_COLLISION,
            "two leaves of this record have the same leaf hash; paths are unique, so this is a "
            "hash collision rather than a tie to break",
        )
    order = sorted(range(len(hashes)), key=lambda i: hashes[i])
    return (
        tuple(encoded_paths[i] for i in order),
        tuple(leaves[i] for i in order),
        tuple(salts[i] for i in order),
        tuple(hashes[i] for i in order),
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
    ordering: str | None = None,
) -> BuiltRecord:
    """Flatten, union, order, hash and merklize.

    This is the whole of steps (A) through (D) of specification section 3.1.

    ``ordering`` defaults to the identity's, which itself defaults to ``path``. Passing it
    explicitly is an override, and a value disagreeing with the identity is refused rather
    than silently preferred: the identity is what decides whether ``roax.ordering`` is
    committed, so two sources disagreeing would emit a leaf naming one ordering while the
    tree used the other.
    """
    if ordering is None:
        ordering = identity.ordering
    elif check_ordering(ordering) != identity.ordering:
        raise RoaxError(
            ErrorCode.ORDERING_NOT_DEFINED,
            f"ordering {ordering!r} disagrees with the identity's {identity.ordering!r}; "
            f"the identity decides whether roax.ordering is committed, so the two cannot differ",
        )
    # RESERVED_V2 IS PERMITTED HERE, and the refusal that used to sit at this line was a
    # defect rather than a conservative choice.
    #
    # It read "envelope 2.0 issuance requires exact structured-path DFA artifact loading and
    # content-ID reproduction", and that is false FOR ISSUANCE. An issuer knows which
    # artifact it used; the content ID is a caller input, not something to be reproduced from
    # fetched bytes. Content-ID reproduction is a VERIFIER's obligation when it selects a map
    # from candidate bytes (specification section 10), and it is still unimplemented here.
    #
    # The refusal made this package unable to issue any record the CURRENT specification
    # admits: section 11.2 marks `roax.typeMap.id` emitted ALWAYS, so every conforming
    # issuance commits it. The cost was invisible until conformance corpus class 20 asked an
    # implementation to produce an envelope rather than only to verify one - at which point
    # this package refused to issue with the leaf while another refused to issue without it,
    # and both had passed every vector in the file.
    if not isinstance(record, dict):
        raise RoaxError(
            ErrorCode.ENVELOPE_SHAPE,
            "a full-copy record must be a JSON object " "(schemas/envelope-1.0.json:118-120)",
        )
    _bind_builtin_resolver(identity, resolver)
    record_snapshot = deepcopy(record)
    hasher = get_hash(hash_alg)
    record_leaves = flatten(
        record_snapshot,
        resolver,
        authorize_empty_containers=authorize_empty_containers,
    )
    all_leaves = record_leaves + reserved_leaves(identity, reserved_set=reserved_set)
    # SALT-ASSIGNMENT order, which is ascending encodePath under BOTH orderings (specification
    # section 9). It cannot be tree order under `hash`: a leaf hash is computed over its salt,
    # so pairing salts in tree order would be circular and unimplementable.
    assigned = order_leaves(all_leaves)

    assigned_paths = tuple(pair[0] for pair in assigned)
    assigned_leaves = tuple(pair[1] for pair in assigned)
    assigned_salts = tuple(
        salts.salt_for(path, leaf) for path, leaf in zip(assigned_paths, assigned_leaves)
    )
    assigned_hashes = tuple(
        leaf_hash(leaf.path, leaf.tag, leaf.value, salt, hasher=hasher, ordering=ordering)
        for leaf, salt in zip(assigned_leaves, assigned_salts)
    )
    encoded_paths, leaves, drawn, hashes = _tree_order(
        ordering, assigned_paths, assigned_leaves, assigned_salts, assigned_hashes
    )
    root = merkle_tree_head(hashes, hasher=hasher)
    return BuiltRecord(
        leaves=leaves,
        encoded_paths=encoded_paths,
        salts=drawn,
        leaf_hashes=hashes,
        root=root,
        identity=identity,
        hash_alg=hasher.name,
        reserved_set=reserved_set,
        _record_snapshot=_freeze_record(record_snapshot),
    )


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
