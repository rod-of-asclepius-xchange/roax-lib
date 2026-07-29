"""Selective disclosure: building the two envelope shapes (specification section 10).

A disclosed copy carries, for each revealed leaf: its path as **structured segments**, its
leaf index, its type tag, its value, **the leaf's own salt**, and its RFC 9162 audit path.

> **Normative:** a disclosed copy MUST carry the salt of every leaf it reveals and **MUST
> NOT carry the salt of any withheld leaf** (specification section 10).

That prohibition is what makes the whole scheme work, and its failure mode is dangerous
because of its shape rather than its difficulty: a disclosed copy that shipped every salt
would **still verify correctly against the root**, because salts do not change any leaf
hash.
It would look valid to every check a verifier runs while leaking every withheld field.
:func:`disclosed_copy` therefore builds the ``leaves`` array from the revealed set alone
and never emits a ``salts`` member, which makes a withheld leaf's salt unrepresentable
rather than merely prohibited.

The minimum-disclosure floor is applied here too, so an unusable copy is not produced in
the first place.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .errors import ErrorCode, RoaxError
from .hashes import DEFAULT_HASH_ALG, get_hash
from .leaf import CANON
from .path import Segment, display_path, encode_path, segments_to_json
from .profiles import Profile
from .record import RESERVED_V1, BuiltRecord, RecordIdentity
from .tree import audit_path
from .value import BYTES, DECIMAL, INTEGER, STRING, VALUELESS_TAGS

__all__ = ["full_copy", "disclosed_copy"]


def _envelope_head(
    identity: RecordIdentity, built: BuiltRecord, hash_alg: str, reserved_set: str
) -> dict[str, Any]:
    head: dict[str, Any] = {
        "canon": CANON,
        "hashAlg": hash_alg,
        "recordType": identity.record_type,
        "schemaVersion": identity.schema_version,
        "recordId": identity.record_id,
        "root": built.root.hex(),
        "leafCount": built.leaf_count,
        "issuer": {"id": identity.issuer_id},
    }
    if identity.issuer_key_id is not None:
        head["issuer"]["keyId"] = identity.issuer_key_id
    if reserved_set != RESERVED_V1 and identity.type_map_id is not None:
        head["typeMap"] = {"id": identity.type_map_id}
    # `recordType` is placed before `root` above only for readability; the envelope is
    # JSON and member order carries no meaning, because nothing here is hashed over the
    # serialized envelope (specification section 13.2).
    return head


def _carrier_value(tag: int, value: Any) -> Any:
    """The envelope's carrier form for a leaf value.

    `BYTES` travels as lowercase hex in the envelope, which is what
    `schemas/envelope-1.0.json` pins, and is distinct from the RFC 4648 base64 the
    *record* carries for the same field (specification section 6.3).

    `STRING`, `INTEGER` and `DECIMAL` travel as a plain :class:`str`, and that conversion
    is not cosmetic.
    A record leaf at tag 3 or 4 holds a :class:`~roax_canon.jsonio.JsonNumber`, whose
    purpose is to keep the literal verbatim, and `schemas/envelope-1.0.json` pins this
    carrier to ``"type": "string"`` because a JSON number here would be read back through
    a float by any ordinary consumer and ``0.010`` would become ``0.01`` (specification
    section 6.4).
    The emitted **bytes** are unchanged either way, since `JsonNumber` subclasses
    :class:`str` and therefore already serializes as a JSON string; what this closes is
    the in-memory hand-off, where the carrier would otherwise still be a `JsonNumber` and
    :func:`roax_canon.verify.verify_envelope` would reject an envelope this module had
    just built.
    The value has already passed :func:`roax_canon.value.encode_value` at these tags by
    the time a :class:`~roax_canon.record.BuiltRecord` exists, so it is a string here.
    """
    if tag == BYTES:
        return bytes(value).hex()
    if tag in (STRING, INTEGER, DECIMAL):
        return str(value)
    return value


def full_copy(
    record: Any,
    identity: RecordIdentity,
    built: BuiltRecord,
    *,
    hash_alg: str = DEFAULT_HASH_ALG,
    reserved_set: str = RESERVED_V1,
) -> dict[str, Any]:
    """A full copy: the whole record plus the salt of **every** leaf.

    Without rule 1 of specification section 7.3 a full copy is not verifiable at all:
    ``leafHash`` needs the leaf's salt and the record body carries none, so a verifier
    would have no route to any leaf hash and therefore none to the root.

    Carrying every salt discloses nothing extra, because a full copy already reveals every
    value at every path and a salt is only useful for confirming a value you do not have.
    """
    envelope = _envelope_head(identity, built, hash_alg, reserved_set)
    envelope["record"] = record
    envelope["salts"] = [
        {"segments": segments_to_json(leaf.path), "salt": salt.hex()}
        for leaf, salt in zip(built.leaves, built.salts)
    ]
    return envelope


def disclosed_copy(
    reveal: Sequence[Sequence[Segment]],
    identity: RecordIdentity,
    built: BuiltRecord,
    *,
    profile: Profile | None = None,
    hash_alg: str = DEFAULT_HASH_ALG,
    reserved_set: str = RESERVED_V1,
    include_display_path: bool = True,
) -> dict[str, Any]:
    """A disclosed copy revealing exactly ``reveal`` and nothing else.

    ``profile`` enforces the minimum-disclosure floor at construction time.
    Passing ``None`` skips it, which is correct only for building a deliberately
    non-conforming fixture; a verifier rejects such a copy either way.

    The display path is emitted for humans when ``include_display_path`` is set.
    It is display only and is never an input to anything a verifier computes
    (specification section 5.2).
    """
    wanted = [tuple(path) for path in reveal]
    encoded_wanted = {encode_path(path) for path in wanted}

    if profile is not None:
        for floor_path in profile.floor(reserved_set=reserved_set):
            if encode_path(floor_path) not in encoded_wanted:
                raise RoaxError(
                    ErrorCode.MINIMUM_DISCLOSURE_FLOOR,
                    f"{display_path(floor_path)!r} is non-redactable for "
                    f"{profile.record_type!r} (specification section 10.2)",
                )

    hasher = get_hash(hash_alg)
    leaves_out: list[dict[str, Any]] = []
    for encoded in sorted(encoded_wanted):
        try:
            index = built.encoded_paths.index(encoded)
        except ValueError:
            raise RoaxError(
                ErrorCode.MINIMUM_DISCLOSURE_FLOOR,
                "requested disclosure of a path this record has no leaf at",
            ) from None
        leaf = built.leaves[index]
        entry: dict[str, Any] = {"segments": segments_to_json(leaf.path)}
        if include_display_path:
            entry["displayPath"] = display_path(leaf.path)
        entry["index"] = index
        entry["tag"] = leaf.tag
        if leaf.tag not in VALUELESS_TAGS:
            entry["value"] = _carrier_value(leaf.tag, leaf.value)
        entry["salt"] = built.salts[index].hex()
        entry["auditPath"] = [
            node.hex() for node in audit_path(index, built.leaf_hashes, hasher=hasher)
        ]
        leaves_out.append(entry)

    envelope = _envelope_head(identity, built, hash_alg, reserved_set)
    envelope["disclosure"] = {"mode": "selective", "leaves": leaves_out}
    # No `salts` member, ever. See the module docstring.
    return envelope


def downgrade(full: Mapping[str, Any], reveal: Sequence[Sequence[Segment]]) -> None:
    """Not implemented, deliberately.

    > **Operationally:** a holder downgrading a full copy to a disclosed copy MUST drop the
    > ``salts`` array and emit, on each revealed leaf, only that leaf's own salt
    > (specification section 7.3).

    Doing that by editing an existing envelope is the shape of the mistake, because the
    thing being removed is the thing that leaks.
    Rebuild with :func:`disclosed_copy` from the :class:`~roax_canon.record.BuiltRecord`
    instead, which cannot emit a withheld salt because it never sees a request for one.
    """
    raise NotImplementedError(
        "rebuild with disclosed_copy() rather than stripping a full copy"
    )
