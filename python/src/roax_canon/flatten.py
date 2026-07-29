"""Flattening a record into typed leaves (specification section 3.3).

::

    flatten(node, path):
      if node is a map and is empty:        emit (path, typeTag(path, "object"), -)
      if node is a map and is non-empty:    for each key k: flatten(node[k], path ‖ KEY(k))
      if node is an array and is empty:     emit (path, typeTag(path, "array"), -)
      if node is an array and is non-empty: for each index i: flatten(node[i], path ‖ INDEX(i))
      otherwise:                            emit (path, typeTag(path, jsonKind(node)), node)

Map iteration order is irrelevant, because leaves are sorted by encoded path in
specification section 9.
That is deliberate: it is what lets a Go implementation work despite Go randomizing map
iteration order, and it removes the class of bug OpenAttestation inherits from JavaScript
key enumeration.

An empty container is a leaf so that removing it changes the root.
Empty array, empty object and explicit null are **three distinct leaves**, which is a
departure from dogtag, where `crates/dogtag-standard-rs/src/flatten.rs:96-115` collapses
all three to ``TypedScalar::Null``.
"""

from __future__ import annotations

from typing import Any, Sequence

from .errors import ErrorCode, InputError, RoaxError
from .jsonio import json_kind
from .leaf import Leaf
from .path import Index, Key, Segment, display_path
from .text import nfc
from .typemap import TypeResolver
from .value import (
    BLOB_REF,
    BYTES,
    EMPTY_ARRAY,
    EMPTY_OBJECT,
    TAG_NAMES,
    decode_base64_canonical,
)

__all__ = ["RESERVED_KEY_PREFIX", "check_reserved_namespace", "flatten"]

#: Specification section 11.2: the reserved ASCII prefix, including the dot.
#: A key named ``roax`` or ``roaxX``, with no dot, collides with nothing and is accepted.
RESERVED_KEY_PREFIX = "roax."


def check_reserved_namespace(segments: Sequence[Segment]) -> None:
    """The reserved-namespace guard (specification section 11.2).

    > **Normative:** no record-supplied path may have, as its **first segment**, a `KEY`
    > whose NFC-normalized key begins with the ASCII prefix ``roax.``.

    Three ways to get this wrong, all closed here:

    * it is not a test against a rendered display path, and this function never builds one
      (specification section 5.2);
    * it applies to the **first** segment only, because every reserved path is a single
      segment, so ``[KEY("a"), KEY("roax.foo")]`` differs from every reserved path in
      segment count and cannot collide;
    * it compares the **NFC-normalized** key, not the bytes as received, because section
      6.1 normalizes keys before they are hashed and a check on the raw bytes is checking
      a different string from the one that gets committed.

    The specification states honestly that the third is currently unobservable, since no
    character normalizes into ``roax.``.
    It is implemented anyway, for the reason it gives: this guard and the hashing path
    must reason about the same string.
    """
    if not segments:
        return
    first = segments[0]
    if not isinstance(first, Key):
        return
    if nfc(first.value, where="first path segment").startswith(RESERVED_KEY_PREFIX):
        raise InputError(
            ErrorCode.RESERVED_NAMESPACE,
            f"record-supplied first segment {first.value!r} is in the reserved "
            f"{RESERVED_KEY_PREFIX!r} namespace (specification section 11.2)",
        )


def _coerce_record_value(tag: int, node: Any, segments: Sequence[Segment]) -> Any:
    """Turn a record scalar into the carrier :func:`encode_value` expects.

    The only conversion is base64: a field bound as `BYTES` carries base64 text in the
    record and the encoded value is the decoded bytes (specification section 6.3), which
    is why the canonical base64 form is pinned there rather than left to be discovered.
    A field bound as `STRING` over that same text is hashed as the text, so no base64 rule
    enters its digest.
    """
    if tag == BYTES:
        if isinstance(node, (bytes, bytearray)):
            return bytes(node)
        if isinstance(node, str):
            return decode_base64_canonical(node)
        raise RoaxError(
            ErrorCode.ENVELOPE_SHAPE,
            f"{display_path(segments)}: BYTES binding needs base64 text or bytes",
        )
    if tag == BLOB_REF:
        raise RoaxError(
            ErrorCode.BLOB_REF_NOT_DECLARED,
            f"{display_path(segments)}: no version-1 profile declares tag 8 BLOB_REF "
            f"(specification section 6.5)",
        )
    return node


def flatten(
    record: Any,
    resolver: TypeResolver,
    *,
    authorize_empty_containers: bool = True,
) -> list[Leaf]:
    """Flatten a record into typed leaves, failing closed on any unresolved path.

    ``authorize_empty_containers`` selects between two readings of specification section
    3.3, and the default is the one the specification text states.

    * ``True``: an empty container's tag is taken from the type map, so `EMPTY_ARRAY` and
      `EMPTY_OBJECT` are emitted "only when the exact selected map authorizes that
      structured path and observed kind under section 4.2", and an unauthorized empty
      container fails closed.
      Section 3.3 gives the reason: assigning tags 6 or 7 before map resolution would let
      an unknown empty issuer extension bypass decision D7's fail-closed rule.
    * ``False``: an empty container is tagged structurally, without consulting the map.

    **The committed conformance corpus requires ``False`` and this is a real divergence,
    reported rather than smoothed over.**
    `corpus/type-maps/org.roax.corpus.synthetic.json` binds ``a.b`` only at kind ``null``
    and ``a.**`` only at kind ``string``, yet `corpus/fixtures/records/structure-empty-
    array.json` and `structure-empty-object.json` carry ``a.b`` as ``[]`` and ``{}`` and
    the class-5 vectors assert a root for each.
    Under the section 3.3 rule those two records fail closed and have no root at all.
    The corpus predates the type-map artifact work that added that sentence, so the
    divergence is one of vintage rather than of reading, and specification section 1.1
    makes the specification govern.
    :mod:`roax_canon.corpus` passes ``False`` with that citation attached; every other
    caller gets the specification's rule.
    """
    leaves: list[Leaf] = []

    def walk(node: Any, segments: tuple[Segment, ...]) -> None:
        kind = json_kind(node)

        if kind == "object":
            if not node:
                leaves.append(Leaf(segments, _container_tag(segments, "object"), None))
                return
            for key, child in node.items():
                child_path = segments + (Key(key),)
                if len(child_path) == 1:
                    check_reserved_namespace(child_path)
                walk(child, child_path)
            return

        if kind == "array":
            if not node:
                leaves.append(Leaf(segments, _container_tag(segments, "array"), None))
                return
            for i, child in enumerate(node):
                walk(child, segments + (Index(i),))
            return

        tag = resolver.resolve(segments, kind)
        if tag in (EMPTY_ARRAY, EMPTY_OBJECT):
            raise RoaxError(
                ErrorCode.TYPE_MAP_REJECTED,
                f"{display_path(segments)}: map binds a scalar to "
                f"{TAG_NAMES[tag]}, which only a container may carry",
            )
        leaves.append(Leaf(segments, tag, _coerce_record_value(tag, node, segments)))

    def _container_tag(segments: tuple[Segment, ...], kind: str) -> int:
        structural = EMPTY_OBJECT if kind == "object" else EMPTY_ARRAY
        if not authorize_empty_containers:
            return structural
        tag = resolver.resolve(segments, kind)
        if tag != structural:
            raise RoaxError(
                ErrorCode.TYPE_MAP_REJECTED,
                f"{display_path(segments)}: map binds an empty {kind} to "
                f"{TAG_NAMES.get(tag, tag)} rather than {TAG_NAMES[structural]}",
            )
        return structural

    walk(record, ())

    if not leaves:
        raise InputError(
            ErrorCode.EMPTY_RECORD,
            "a record that contributes zero leaves of its own MUST be rejected at "
            "issuance (specification section 3.3)",
        )
    return leaves
