"""Envelope verification (specification sections 10 and 11).

**Anything outside the root is attacker-controlled** (specification section 11.3).
Fields outside the root are hints and never authority.
:class:`VerifierConfig` is where authority actually lives: the anchored root, the anchored
algorithm and the algorithm allow-list all come from the verifier, never from the
document, and each of the three is compared here.
The registry it names is carried for a caller and is compared against nothing, because
this package reads no chain; see :class:`VerifierConfig`.

Attacker control is also why :func:`verify_envelope` returns a result for every input.
Each member shape it depends on is checked explicitly, and the broad ``except`` there is a
backstop for a shape nobody anticipated rather than the mechanism.

The order of the disclosed-copy checks is derived rather than chosen, and
`corpus/README.md` measures both halves of it:

1. every disclosed leaf is recomputed and its inclusion proof checked against the root;
2. the outer ``recordType``, ``schemaVersion``, ``recordId`` and ``issuer.id`` are bound
   to the reserved leaves the root commits;
3. the floor is selected from the **committed** ``roax.recordType`` leaf and enforced.

Section 11.3 says a field outside the root is never authority, so authority has to be
established before an outer field is used to **select** anything.
Choosing the floor from the envelope's ``recordType`` and validating it afterwards is
trust-then-verify, which is the shape of the dogtag ``documentStore`` scar section 11.3
records.
Enforcing the floor before the binding fails exactly 16 of the corpus's 54 envelope
vectors; sourcing the floor from the outer field rather than the leaf fails none, because
step 2 has just proved them NFC-equal, so that half is a clarity convention rather than a
corpus-enforced requirement and is written the safe way anyway.

**Step 1 is the one that is not optional.**
A verifier never accepts a caller-supplied leaf hash; it recomputes one from the disclosed
path, tag, value and salt.
Specification section 11.1 records why in full: RFC 9162 section 2.1.3.2 takes the tree
size as an input, so an attacker controlling ``leafCount`` controls the shape the verifier
rebuilds, and on an 8-leaf tree an internal node presented as a leaf with a forged size of
2 verifies against the genuine root.
``leafCount`` is therefore **not** authenticated in a disclosed copy and is used for
nothing here beyond being the tree size RFC 9162 requires as an input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import ErrorCode, RoaxError
from .hashes import DEFAULT_HASH_ALG, get_hash
from .jsonio import as_int, is_json_string
from .flatten import RESERVED_KEY_PREFIX
from .leaf import CANON, SALT_BYTES, leaf_hash
from .path import Key, Segment, display_path, encode_path, segments_from_json
from .profiles import DEFAULT_PROFILES, ProfileRegistry
from .record import (
    RESERVED_V1,
    RESERVED_V2,
    MappingSalts,
    RecordIdentity,
    build_tree,
    normalized_equal,
)
from .text import nfc
from .tree import verify_inclusion
from .typemap import TypeResolver
from .value import BLOB_REF, BYTES, DECIMAL, INTEGER, STRING, TAG_NAMES, VALUELESS_TAGS

__all__ = ["VerifierConfig", "VerificationResult", "verify_envelope"]

#: Every object `schemas/envelope-1.0.json` closes with ``additionalProperties: false``,
#: mirrored here so the closure holds at each depth rather than at the top level alone.
#: The top-level set alone is not the defence it looks like: every nested object below is
#: dereferenced by named key, so an extra member one level down is silently ignored, and a
#: `disclosure` carrying its own `salts` array or an `issuer` carrying a `masterSalt`
#: delivers the salt of an undisclosed leaf in an envelope that verifies correctly - the
#: exact leak specification section 7.3 rule 3 forbids, one layer beneath where
#: :data:`_SEED_MEMBERS` was being scanned for it.
_TOP_LEVEL_MEMBERS = frozenset(
    {
        "canon",
        "hashAlg",
        "recordType",
        "schemaVersion",
        "typeMap",
        "recordId",
        "root",
        "leafCount",
        "issuer",
        "anchor",
        "disclosure",
        "record",
        "salts",
    }
)
_ISSUER_MEMBERS = frozenset({"id", "keyId"})
_TYPE_MAP_MEMBERS = frozenset({"id", "version"})
_ANCHOR_MEMBERS = frozenset({"chainId", "registry", "anchoredAt", "txHash"})
_DISCLOSURE_MEMBERS = frozenset({"mode", "leaves"})
_SALT_ENTRY_MEMBERS = frozenset({"segments", "salt"})
_DISCLOSED_LEAF_MEMBERS = frozenset(
    {"segments", "displayPath", "index", "tag", "value", "salt", "auditPath"}
)

# `schemas/envelope-1.0.json` pins a BYTES leaf value to this form. Anchored \A and \Z
# rather than ^ and $, because Python's $ also matches before a trailing newline.
_HEX_CARRIER = re.compile(r"\A([0-9a-f]{2})*\Z")

_REQUIRED_MEMBERS = (
    "canon",
    "hashAlg",
    "recordType",
    "schemaVersion",
    "recordId",
    "root",
    "leafCount",
    "issuer",
)

#: Any envelope member from which a withheld leaf's salt could be obtained.
#: Specification section 7.3 rule 3 forbids one, and under ruled decision D4b no such
#: value exists to carry, which is what makes the rule cheap.
#: It is retained rather than deleted because it binds any future revision that
#: reintroduces a derived salt: adding a seed would hand every holder the ability to
#: recompute every withheld leaf's salt, in an envelope that still verified correctly.
_SEED_MEMBERS = ("masterSalt", "salt", "seed", "saltSeed", "kdfKey")

#: The reserved paths whose committed leaf is bound to an outer envelope field.
#: ``roax.issuer.keyId`` is deliberately absent: it is the one conditional leaf, and an
#: absent one emits no leaf at all (specification section 11.2).
_IDENTITY_BINDINGS_V1 = (
    ("roax.recordType", ("recordType",)),
    ("roax.schemaVersion", ("schemaVersion",)),
    ("roax.recordId", ("recordId",)),
    ("roax.issuer.id", ("issuer", "id")),
)
_IDENTITY_BINDINGS_V2 = _IDENTITY_BINDINGS_V1 + (("roax.typeMap.id", ("typeMap", "id")),)


@dataclass(frozen=True, slots=True)
class VerifierConfig:
    """What the verifier itself is configured with.

    ``anchored_root`` and ``anchored_hash_alg`` are what the verifier's own anchoring
    registry records.
    Specification section 7.4 H2 requires ``hashAlg`` to be taken from there and never
    from the envelope; H3 requires rejecting any algorithm absent from
    ``hash_alg_allow_list``, which closes the retired-algorithm case the registry alone
    does not.

    ``registry_address`` and ``registry_chain_id`` name the registry this verifier reads.
    **Neither is consulted by any check in this module**, and both are carried for a caller
    that does read a registry.
    Not comparing them is the correct behaviour rather than an omission: specification
    section 11.3 makes an envelope's ``anchor`` block a routing hint that is never
    authority, so an envelope naming a different registry is not a rejection - the verifier
    simply reads its own and never the one the document names.

    ``resolvers`` supplies a type map per ``recordType`` for **full copies only**.
    A disclosed copy under `schemas/envelope-1.0.json` has no exact map it can select.
    That schema does carry a top-level ``typeMap`` object, but it is OPTIONAL there and
    ``roax.typeMap.id`` is not one of that version's committed reserved leaves, so its
    value is outside the root and is a hint rather than authority (specification section
    11.3, and that member's own description in the schema).
    The section 4.2 binding that makes it selectable arrived with
    `schemas/envelope-2.0.json`, which requires the member and commits the leaf; see
    :func:`verify_envelope`.
    """

    profiles: ProfileRegistry = DEFAULT_PROFILES
    hash_alg_allow_list: tuple[str, ...] = (DEFAULT_HASH_ALG,)
    resolvers: Mapping[str, TypeResolver] = field(default_factory=dict)
    reserved_set: str = RESERVED_V1
    anchored_root: bytes | None = None
    anchored_hash_alg: str | None = None
    registry_address: str | None = None
    registry_chain_id: int | None = None
    authorize_empty_containers: bool = True


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Accepted or not, and why.

    ``reason`` is ``"ok"`` on acceptance and a stable rejection code otherwise.
    The reason is not decoration: several envelopes are rejectable for more than one
    cause, so a boolean alone would pass an implementation that never ran the check the
    case is about (`corpus/README.md`).
    """

    accepted: bool
    reason: str
    detail: str = ""

    def __bool__(self) -> bool:
        return self.accepted


def _reject(code: str, detail: str = "") -> VerificationResult:
    return VerificationResult(False, code, detail)


def _check_members(obj: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
    """Reject a seed member and then any member the envelope schema does not declare.

    The seed scan precedes the closure and skips a name the object legitimately declares,
    and both halves of that are load-bearing.
    Preceding it is what keeps `salt-leak-disclosed-copy-with-master-salt.json` reporting
    `master-salt-in-envelope` rather than a generic unknown-member error, which is the
    reason that vector exists.
    Skipping a declared name is what lets the same scan run over a `salts` entry and a
    disclosed leaf, where ``salt`` is the member being asked for rather than a leak.
    """
    for seed in _SEED_MEMBERS:
        if seed in obj and seed not in allowed:
            raise RoaxError(
                ErrorCode.MASTER_SALT_IN_ENVELOPE,
                f"{where} carries {seed!r}; no envelope may carry any value from which "
                f"the salt of an undisclosed leaf could be obtained "
                f"(specification section 7.3, rule 3)",
            )
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise RoaxError(ErrorCode.ENVELOPE_SHAPE, f"unknown {where} members {unknown}")


def _hexbytes(text: Any, *, field_name: str, size: int) -> bytes:
    # `is_json_string` and not `isinstance(text, str)`: every hex field this reads is pinned
    # to "type": "string" by `schemas/envelope-1.0.json`, and `JsonNumber` subclasses `str`
    # so an all-digit even-length numeric literal would otherwise satisfy both tests here
    # while any consumer re-reading the same bytes with a stdlib parser destroys them
    # (specification section 6.4).
    if not is_json_string(text) or len(text) != size * 2:
        raise RoaxError(ErrorCode.ENVELOPE_SHAPE, f"{field_name} must be {size * 2} hex characters")
    if any(ch not in "0123456789abcdef" for ch in text):
        raise RoaxError(ErrorCode.ENVELOPE_SHAPE, f"{field_name} must be lowercase hex")
    return bytes.fromhex(text)


def verify_envelope(
    envelope: Mapping[str, Any], config: VerifierConfig | None = None
) -> VerificationResult:
    """Verify a full copy or a disclosed copy.

    The envelope MUST have been read through :func:`roax_canon.jsonio.loads`.
    A full copy carries the record in its original JSON form, so the parser requirement of
    specification section 6.4 applies to the **envelope**, not only to a bare record: an
    implementation that reads a full copy through a float-based parser destroys the very
    literals it is about to recompute the root from.
    """
    cfg = config or VerifierConfig()
    try:
        return _verify(envelope, cfg)
    except RoaxError as exc:
        return _reject(exc.code, exc.detail)
    except (TypeError, ValueError, AttributeError, KeyError, IndexError, RecursionError) as exc:
        # A backstop, and deliberately not the mechanism: every member shape this module
        # depends on is checked explicitly above, and each of those checks carries the
        # reason code the case is about. This clause exists because specification section
        # 11.3 makes everything outside the root attacker-controlled, so a shape nobody
        # anticipated MUST still leave this function returning a result rather than
        # raising into a verifier service. It is placed after the `RoaxError` clause so a
        # real rejection keeps its own code.
        #
        # `RecursionError` is named explicitly because it is a `RuntimeError` and so is
        # caught by none of the others: `flatten.walk` and `jsonio._check_surrogates` both
        # recurse once per nesting level of an attacker-supplied full-copy `record`, and a
        # depth is as attacker-controlled as a shape.
        return _reject(
            ErrorCode.ENVELOPE_SHAPE,
            f"malformed envelope member ({type(exc).__name__})",
        )


def _verify(env: Mapping[str, Any], cfg: VerifierConfig) -> VerificationResult:
    # --- Shape. ------------------------------------------------------------------
    if not isinstance(env, Mapping):
        return _reject(ErrorCode.ENVELOPE_SHAPE, "envelope is not an object")

    _check_members(env, _TOP_LEVEL_MEMBERS, "envelope")

    for required in _REQUIRED_MEMBERS:
        if required not in env:
            return _reject(ErrorCode.ENVELOPE_SHAPE, f"missing envelope member {required!r}")

    if env["canon"] != CANON:
        return _reject(ErrorCode.CANON_MISMATCH, f"canon is {env['canon']!r}, not {CANON!r}")

    has_record = "record" in env
    has_disclosure = "disclosure" in env
    if has_record == has_disclosure:
        return _reject(
            ErrorCode.ENVELOPE_SHAPE,
            "exactly one of `record` and `disclosure` MUST be present "
            "(specification section 11.1)",
        )
    if has_disclosure and "salts" in env:
        return _reject(
            ErrorCode.DISCLOSED_COPY_CARRIES_SALTS,
            "`salts` is forbidden alongside `disclosure`; an envelope carrying both MUST "
            "be rejected rather than repaired (specification section 7.3)",
        )
    if has_record and "salts" not in env:
        return _reject(
            ErrorCode.ENVELOPE_SHAPE,
            "a full copy MUST carry the salt of every leaf (specification section 7.3)",
        )

    # --- Authority the verifier holds, before anything the document says. --------
    hash_alg = env["hashAlg"]
    if hash_alg not in cfg.hash_alg_allow_list:
        return _reject(
            ErrorCode.HASH_ALG_NOT_ALLOWED,
            f"{hash_alg!r} is not on this verifier's allow-list "
            f"(specification section 7.4, H3)",
        )
    if cfg.anchored_hash_alg is not None and hash_alg != cfg.anchored_hash_alg:
        return _reject(
            ErrorCode.HASH_ALG_NOT_ALLOWED,
            f"envelope names {hash_alg!r}; the anchoring registry records "
            f"{cfg.anchored_hash_alg!r} (specification section 7.4, H2)",
        )
    hasher = get_hash(hash_alg)

    record_type = env["recordType"]
    profile = cfg.profiles.get(record_type)
    if profile is None:
        return _reject(
            ErrorCode.PROFILE_UNKNOWN,
            f"{record_type!r} is not a registered profile; an unknown profile MUST fail "
            f"closed (specification section 12.2)",
        )

    root = _hexbytes(env["root"], field_name="root", size=hasher.digest_size)
    if cfg.anchored_root is not None and root != cfg.anchored_root:
        return _reject(
            ErrorCode.ROOT_MISMATCH,
            "the envelope's root is not the root the anchoring registry records "
            "(specification section 11.3)",
        )
    leaf_count = as_int(env["leafCount"], field="leafCount")

    issuer = env["issuer"]
    if not isinstance(issuer, Mapping) or "id" not in issuer:
        return _reject(ErrorCode.ENVELOPE_SHAPE, "issuer.id is required")
    _check_members(issuer, _ISSUER_MEMBERS, "issuer")

    # The outer identity members become reserved STRING leaves under specification section
    # 11.2 and are bound to them under section 11.3, so each MUST be a genuine JSON string
    # before either of those runs. `is_json_string` and not `isinstance(x, str)`, because
    # `JsonNumber` subclasses `str` so the literal survives, which means the JSON number
    # 1.0 would otherwise commit a `schemaVersion` leaf byte-identical to the JSON string
    # "1.0" that `schemas/envelope-1.0.json` requires.
    #
    # The site is chosen: after the issuer shape check it covers a full copy and a
    # disclosed copy at once, and before it would preempt the `canon-mismatch`,
    # `hash-alg-not-allowed`, `profile-unknown` and `root-mismatch` precedence the corpus
    # fixtures pin. `recordType` is deliberately still allowed to reach the profile lookup
    # above first, so `profile-unknown-fails-closed` keeps its reason.
    for member in ("recordType", "schemaVersion", "recordId"):
        if not is_json_string(env[member]):
            return _reject(ErrorCode.ENVELOPE_SHAPE, f"{member} must be a JSON string")
    if not is_json_string(issuer["id"]):
        return _reject(ErrorCode.ENVELOPE_SHAPE, "issuer.id must be a JSON string")
    if "keyId" in issuer and not is_json_string(issuer["keyId"]):
        return _reject(ErrorCode.ENVELOPE_SHAPE, "issuer.keyId must be a JSON string")
    type_map = env.get("typeMap")
    if type_map is not None:
        if not isinstance(type_map, Mapping):
            return _reject(ErrorCode.ENVELOPE_SHAPE, "`typeMap` must be an object")
        _check_members(type_map, _TYPE_MAP_MEMBERS, "typeMap")
        if "id" in type_map and not is_json_string(type_map["id"]):
            return _reject(ErrorCode.ENVELOPE_SHAPE, "typeMap.id must be a JSON string")

    # `anchor` is closed although no check in this module dereferences it. Being unread is
    # what makes it a carrier: an unclosed routing hint is somewhere a producer can park a
    # withheld leaf's salt with nothing ever looking at it (specification sections 7.3 and
    # 11.3).
    anchor = env.get("anchor")
    if anchor is not None:
        if not isinstance(anchor, Mapping):
            return _reject(ErrorCode.ENVELOPE_SHAPE, "`anchor` must be an object")
        _check_members(anchor, _ANCHOR_MEMBERS, "anchor")

    if has_record:
        return _verify_full_copy(env, cfg, hasher, root, leaf_count, record_type)
    return _verify_disclosed_copy(env, cfg, hasher, root, leaf_count)


# ---------------------------------------------------------------------------------
# Full copy
# ---------------------------------------------------------------------------------


def _verify_full_copy(env, cfg, hasher, root, leaf_count, record_type) -> VerificationResult:
    """Rebuild the whole tree from the record and its salts.

    The salts array is checked for self-consistency first, then against ``leafCount``,
    then against the leaf set.
    That precedence is what the corpus fixtures pin: an array with a duplicate entry also
    leaves a real leaf unsalted, and an array of the wrong length also disagrees with the
    derived leaf count, so an implementation that checked in another order would report a
    true but different cause.
    """
    salts_raw = env["salts"]
    if not isinstance(salts_raw, list):
        return _reject(ErrorCode.ENVELOPE_SHAPE, "`salts` must be an array")

    by_path: dict[bytes, bytes] = {}
    for entry in salts_raw:
        if not isinstance(entry, Mapping) or "segments" not in entry or "salt" not in entry:
            return _reject(ErrorCode.ENVELOPE_SHAPE, "each salts entry needs segments and salt")
        _check_members(entry, _SALT_ENTRY_MEMBERS, "salts entry")
        encoded = encode_path(segments_from_json(entry["segments"]))
        if encoded in by_path:
            return _reject(
                ErrorCode.SALTS_DUPLICATE_PATH,
                f"`salts` names {display_path(segments_from_json(entry['segments']))!r} "
                f"more than once",
            )
        by_path[encoded] = _hexbytes(entry["salt"], field_name="salt", size=SALT_BYTES)

    if len(salts_raw) != leaf_count:
        return _reject(
            ErrorCode.SALTS_LENGTH_NOT_LEAF_COUNT,
            f"`salts` has {len(salts_raw)} entries and `leafCount` is {leaf_count}; a full "
            f"copy carries one entry per leaf of the union (specification section 7.3)",
        )

    resolver = cfg.resolvers.get(record_type)
    if resolver is None:
        return _reject(
            ErrorCode.TYPE_UNRESOLVED,
            f"no type map configured for {record_type!r}; a full copy's record leaves "
            f"cannot be tagged without one (specification section 4.2)",
        )

    issuer = env["issuer"]
    type_map = env.get("typeMap") or {}
    identity = RecordIdentity(
        record_type=record_type,
        schema_version=env["schemaVersion"],
        record_id=env["recordId"],
        issuer_id=issuer["id"],
        issuer_key_id=issuer.get("keyId"),
        type_map_id=type_map.get("id"),
    )

    built = build_tree(
        env["record"],
        identity,
        resolver,
        MappingSalts(by_path),
        hash_alg=hasher.name,
        reserved_set=cfg.reserved_set,
        authorize_empty_containers=cfg.authorize_empty_containers,
    )

    if built.leaf_count != leaf_count:
        return _reject(
            ErrorCode.LEAF_COUNT_MISMATCH,
            f"derived {built.leaf_count} leaves and `leafCount` says {leaf_count}; a "
            f"disagreement MUST be a rejection (specification section 11.1)",
        )
    if built.root != root:
        return _reject(ErrorCode.ROOT_MISMATCH, "recomputed root does not match `root`")
    return VerificationResult(True, ErrorCode.OK)


# ---------------------------------------------------------------------------------
# Disclosed copy
# ---------------------------------------------------------------------------------

_RESERVED_TAG = STRING


#: The tags whose disclosed-copy ``value`` carrier is a JSON **string**.
#: `schemas/envelope-1.0.json` pins ``"type": "string"`` on the disclosed leaf's ``value``
#: for each of them, and specification section 6.4 is why for the two numeric ones: a JSON
#: number in the carrier is read back through a float by any ordinary consumer, and
#: ``0.010`` becomes ``0.01`` while this package still verifies the envelope, because the
#: literal happens to survive :class:`~roax_canon.jsonio.JsonNumber` on the way in.
#: Every other tag is absent for a reason: 1 `BOOL` carries a JSON boolean, 0 `NULL`,
#: 6 `EMPTY_ARRAY` and 7 `EMPTY_OBJECT` carry no value at all, and 8 `BLOB_REF` is
#: rejected before this is reached (specification section 6.5).
_STRING_CARRIER_TAGS = frozenset({STRING, INTEGER, DECIMAL, BYTES})


def _decode_carrier(tag: int, value: Any) -> Any:
    """Validate a disclosed leaf's ``value`` carrier and hand :func:`encode_value` what it
    expects.

    **The scope is exactly ``disclosure.leaves[].value`` and nothing else.**
    A full copy's ``record`` body carries record numbers in their original JSON form by
    specification section 7.3, and the flattener resolves those through the observed JSON
    kind, so the same test applied there would contradict the specification as well as
    every full-copy vector.
    :func:`roax_canon.value.encode_value` is the wrong site for the same reason: the
    record path legitimately hands it a :class:`~roax_canon.jsonio.JsonNumber` whenever a
    map binds kind ``number`` to tag 2, 3 or 4.

    :func:`~roax_canon.jsonio.is_json_string` and not ``isinstance(value, str)``, because
    `JsonNumber` subclasses :class:`str` so the literal survives, and that same
    subclassing is what carries a JSON number through every carrier boundary in this
    package undetected.

    `BYTES` is carried as lowercase hex, which is what `schemas/envelope-1.0.json` pins
    and is a different carrier from the RFC 4648 base64 the *record* uses for the same
    field (specification section 6.3).
    The hex test alone does not subsume the string test: an all-digit JSON number literal
    of even length matches `_HEX_CARRIER`.

    **No committed corpus vector reaches any of this.**
    No envelope fixture carries a non-string ``value`` at tags 2, 3 or 4, and no version-1
    profile binds `BYTES`, because the healthcert blob fields bind STRING and FHIR
    ``base64Binary`` is unresolved (specification section 6.3).
    The `BYTES` decoder exists because :func:`roax_canon.disclose.disclosed_copy` emits
    that carrier, and an encoder without a decoder is a round trip that does not close.
    """
    if tag not in _STRING_CARRIER_TAGS:
        return value
    if not is_json_string(value):
        raise RoaxError(
            ErrorCode.ENVELOPE_SHAPE,
            f"a {TAG_NAMES[tag]} leaf value is carried as a JSON string and never as a "
            f"JSON number (specification section 6.4)",
        )
    if tag != BYTES:
        return value
    if _HEX_CARRIER.match(value) is None:
        raise RoaxError(
            ErrorCode.ENVELOPE_SHAPE,
            "a BYTES leaf value is carried as an even-length lowercase hex string",
        )
    return bytes.fromhex(value)


def _verify_disclosed_copy(env, cfg, hasher, root, leaf_count) -> VerificationResult:
    """Check every disclosed leaf, bind the outer identity, then enforce the floor.

    The profile :func:`_verify` resolved from the outer ``recordType`` is deliberately not
    a parameter here. That lookup is still needed there, because an unregistered
    ``recordType`` MUST fail closed ahead of everything else and the corpus pins that
    precedence, but step 3 below re-derives the profile from the **committed**
    ``roax.recordType`` leaf and must keep doing so.
    """
    disclosure = env["disclosure"]
    if not isinstance(disclosure, Mapping) or disclosure.get("mode") != "selective":
        return _reject(ErrorCode.ENVELOPE_SHAPE, "disclosure.mode must be 'selective'")
    _check_members(disclosure, _DISCLOSURE_MEMBERS, "disclosure")
    leaves = disclosure.get("leaves")
    if not isinstance(leaves, list) or not leaves:
        return _reject(ErrorCode.ENVELOPE_SHAPE, "disclosure.leaves must be a non-empty array")

    # Step 1: recompute every disclosed leaf and prove it against the root.
    disclosed: dict[bytes, tuple[tuple[Segment, ...], int, Any]] = {}
    for raw in leaves:
        if not isinstance(raw, Mapping):
            return _reject(ErrorCode.ENVELOPE_SHAPE, "each disclosed leaf must be an object")
        for required in ("segments", "index", "tag", "salt", "auditPath"):
            if required not in raw:
                return _reject(ErrorCode.ENVELOPE_SHAPE, f"disclosed leaf missing {required!r}")
        _check_members(raw, _DISCLOSED_LEAF_MEMBERS, "disclosed leaf")

        segments = segments_from_json(raw["segments"])
        tag = as_int(raw["tag"], field="tag")
        if tag == BLOB_REF:
            return _reject(
                ErrorCode.BLOB_REF_NOT_DECLARED,
                "an envelope carrying a tag-8 leaf MUST be rejected until a profile "
                "declares the binding (specification section 6.5)",
            )
        has_value = "value" in raw
        if tag in VALUELESS_TAGS:
            if has_value:
                return _reject(
                    ErrorCode.ENVELOPE_SHAPE,
                    f"{display_path(segments)!r}: tag {tag} carries no value",
                )
        elif not has_value:
            return _reject(
                ErrorCode.DISCLOSED_LEAF_NAMED_WITHOUT_VALUE,
                f"{display_path(segments)!r} is named with a salt and no value; a verifier "
                f"recomputes a leaf hash from its fields and cannot recompute one it was "
                f"not given (specification section 10, step 2)",
            )

        # The reserved half of specification section 10 step 1: a reserved leaf's tag
        # comes from the fixed table in section 11.2, so it is checked here.
        #
        # THE RECORD-LEAF HALF IS NOT PERFORMABLE FOR THIS ENVELOPE VERSION, and that is
        # stated rather than skipped quietly. Step 1 checks a record leaf's tag against
        # "the exact selected map", and the map is selected by the content ID committed at
        # `roax.typeMap.id` under specification section 4.2. `schemas/envelope-1.0.json`
        # does carry an optional top-level `typeMap.id`, but that member sits outside the
        # root and this version commits no such leaf, so selecting on it would be trusting
        # an unauthenticated hint; a verifier that instead picked a map by `recordType`
        # alone would be resolving against an artifact the envelope never identified.
        if len(segments) == 1 and isinstance(segments[0], Key) and nfc(
            segments[0].value, where="disclosed leaf key"
        ).startswith(RESERVED_KEY_PREFIX):
            if tag != _RESERVED_TAG:
                return _reject(
                    ErrorCode.OUTER_IDENTITY_MISMATCH,
                    f"reserved leaf {segments[0].value!r} must be tag 2 STRING "
                    f"(specification section 11.2)",
                )

        value = _decode_carrier(tag, raw.get("value"))
        salt = _hexbytes(raw["salt"], field_name="salt", size=SALT_BYTES)
        computed = leaf_hash(segments, tag, value, salt, hasher=hasher)

        index = as_int(raw["index"], field="index")
        audit_path = raw["auditPath"]
        if not isinstance(audit_path, list):
            return _reject(ErrorCode.ENVELOPE_SHAPE, "`auditPath` must be an array")
        path = [
            _hexbytes(node, field_name="auditPath entry", size=hasher.digest_size)
            for node in audit_path
        ]
        if not verify_inclusion(computed, index, leaf_count, path, root, hasher=hasher):
            return _reject(
                ErrorCode.INCLUSION_PROOF_FAILED,
                f"{display_path(segments)!r} at index {index} does not prove against `root`",
            )
        encoded = encode_path(segments)
        if encoded in disclosed:
            # Paths are unique by construction in a tree (specification section 9), so two
            # entries at one path is a malformed copy rather than a redundant one.
            return _reject(
                ErrorCode.ENVELOPE_SHAPE,
                f"{display_path(segments)!r} is disclosed more than once",
            )
        disclosed[encoded] = (segments, tag, value)

    # Step 2: bind the outer identity to the reserved leaves the root commits.
    bindings = _IDENTITY_BINDINGS_V2 if cfg.reserved_set == RESERVED_V2 else _IDENTITY_BINDINGS_V1
    committed: dict[str, str] = {}
    for reserved_key, outer_path in bindings:
        encoded = encode_path((Key(reserved_key),))
        entry = disclosed.get(encoded)
        if entry is None:
            return _reject(
                ErrorCode.OUTER_IDENTITY_MISMATCH,
                f"{reserved_key} is not disclosed, so the outer field it authenticates "
                f"cannot be bound (specification sections 11.2 and 11.3)",
            )
        outer: Any = env
        for step in outer_path:
            outer = outer.get(step) if isinstance(outer, Mapping) else None
        leaf_value = entry[2]
        if not isinstance(outer, str) or not isinstance(leaf_value, str):
            return _reject(
                ErrorCode.OUTER_IDENTITY_MISMATCH,
                f"{reserved_key} and the envelope's {'.'.join(outer_path)} are not both strings",
            )
        # Compare under NFC on both sides: a STRING leaf commits its normalized form.
        if not normalized_equal(outer, leaf_value):
            return _reject(
                ErrorCode.OUTER_IDENTITY_MISMATCH,
                f"the envelope's {'.'.join(outer_path)} is {outer!r} and the committed "
                f"{reserved_key} leaf is {leaf_value!r}",
            )
        committed[reserved_key] = leaf_value

    # Step 3: select the floor from the COMMITTED recordType leaf, never from the outer
    # field. Step 2 has just proved the two NFC-equal, so no vector can tell them apart;
    # this puts the structural claim where a reader of the code can see it, and keeps a
    # later edit from quietly restoring the trust-then-verify shape.
    committed_type = committed["roax.recordType"]
    committed_profile = cfg.profiles.get(committed_type)
    if committed_profile is None:  # pragma: no cover - unreachable after step 2
        return _reject(ErrorCode.PROFILE_UNKNOWN, f"{committed_type!r} is not a registered profile")

    for floor_path in committed_profile.floor(reserved_set=cfg.reserved_set):
        if encode_path(floor_path) not in disclosed:
            return _reject(
                ErrorCode.MINIMUM_DISCLOSURE_FLOOR,
                f"{display_path(floor_path)!r} is non-redactable for "
                f"{committed_type!r} and is not disclosed (specification section 10.2)",
            )

    return VerificationResult(True, ErrorCode.OK)
