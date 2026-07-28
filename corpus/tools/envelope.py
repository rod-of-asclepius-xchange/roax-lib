"""Envelope verification for implementation A: sections 7.3, 10, 10.2, 11 and 11.2.

This is the part of the protocol JSON Schema cannot express, which is exactly why classes 13 to
17 exist. `verify` returns (accepted, reason); a rejection always carries a stable reason code,
because specification section 12.2 requires an unknown profile or algorithm to fail closed
"with a stated reason, and NEVER default to a guess".
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import roax_ref as ref  # noqa: E402

# Section 10.2: each profile declares a set of non-redactable paths, and a disclosed copy that
# omits any of them MUST be rejected. Transcribed from docs/profiles/, one row per document.
# The four reserved paths of section 11.2 are the floor every profile carries; roax.issuer.keyId
# is committed but OPTIONAL to disclose and MUST NOT be added here, because requiring it would
# permanently bind an anchored record to the key it was issued under.
PROFILE_FLOORS = {
    # docs/profiles/fhir.md section 5
    "hl7.fhir.bundle": ["resourceType"],
    # docs/profiles/pdt-healthcert.md section 4
    "sg.gov.moh.pdt-healthcert": ["version", "type", "validFrom"],
    # docs/profiles/recovery-healthcert.md section 4
    "sg.gov.moh.recovery-healthcert": ["version", "type", "validFrom", "validUntil"],
    # docs/profiles/vaccination-healthcert.md section 4
    "sg.gov.moh.vaccination-healthcert": ["validFrom", "notarisationMetadata.reference"],
    # The corpus-only profile. Not in the docs/profiles/ registry; see synthetic_records.py.
    "org.roax.corpus.synthetic": ["marker"],
}

# Section 7.4, H3: a verifier MUST reject any hashAlg absent from its OWN configured allow-list.
# Poseidon-BN254 is registered in the envelope schema but ROAX-CANON/1 defines no construction
# for it, so a verifier of v1 records allows SHA-256 and nothing else.
ALLOWED_HASH_ALGS = ("SHA-256",)

RESERVED_FLOOR = list(ref.RESERVED_DISCLOSURE_FLOOR)


# An envelope is read with the SAME literal-preserving parser a record is, because section 7.3
# says so: a full copy carries record numbers in their original JSON form, so an implementation
# that reads the envelope through a float-based parser destroys the very literals it is about to
# recompute the root from. These accessors therefore work on the RecordMap/NumberLiteral model
# rather than on plain dicts.


def _has(node, key) -> bool:
    if isinstance(node, ref.RecordMap):
        return any(k == key for k, _ in node.items)
    return isinstance(node, dict) and key in node


def _get(node, key, default=None):
    if isinstance(node, ref.RecordMap):
        for k, v in node.items:
            if k == key:
                return v
        return default
    if isinstance(node, dict):
        return node.get(key, default)
    return default


def _int(node) -> int:
    if isinstance(node, ref.NumberLiteral):
        return int(node.text)
    if isinstance(node, bool) or not isinstance(node, int):
        raise ref.RoaxError("envelope-field-not-an-integer", repr(node))
    return node


def _segments(node):
    """Decode a segments array from the envelope model into the implementation's form."""
    out = []
    for seg in node or []:
        if _has(seg, "key"):
            out.append({"key": _get(seg, "key")})
        elif _has(seg, "index"):
            out.append({"index": _int(_get(seg, "index"))})
        else:
            raise ref.RoaxError("segment-malformed", "")
    return out


def _segments_key(segments):
    """A comparison key over DECODED segments. Never a rendered display string (section 5.2)."""
    return tuple(("k", ref.nfc(s["key"])) if "key" in s else ("i", s["index"]) for s in segments)


def _floor_for(record_type):
    profile = PROFILE_FLOORS.get(record_type)
    if profile is None:
        return None
    return [[{"key": p}] for p in RESERVED_FLOOR] + [[{"key": p}] for p in profile]


def verify(envelope, type_maps, record_loader=None):
    """Verify one envelope. Returns (accepted: bool, reason: str).

    `type_maps` maps recordType to a ref.TypeMap; `record_loader` resolves a full copy's record
    body when the envelope references one by file. A full copy carries its record inline, so the
    loader is only used by the fixtures that keep the body out of the envelope.
    """
    try:
        return _verify(envelope, type_maps, record_loader)
    except ref.RoaxError as exc:
        return False, exc.code


def _verify(envelope, type_maps, record_loader):
    for field in ("canon", "hashAlg", "recordType", "schemaVersion", "recordId", "root",
                  "leafCount", "issuer"):
        if not _has(envelope, field):
            return False, "envelope-missing-field"

    if _get(envelope, "canon") != ref.CANON:
        return False, "canon-unknown"
    hash_alg = _get(envelope, "hashAlg")
    if hash_alg not in ALLOWED_HASH_ALGS:
        # Section 7.4 H3. Stated reason, never a default.
        return False, "hash-alg-not-allowed"

    if _has(envelope, "masterSalt"):
        # Section 7.3 rule 3. masterSalt MUST NEVER appear in any envelope, full or disclosed.
        return False, "master-salt-in-envelope"

    has_record = _has(envelope, "record")
    has_disclosure = _has(envelope, "disclosure")
    if has_record and has_disclosure:
        return False, "record-and-disclosure-both-present"
    if not has_record and not has_disclosure:
        return False, "neither-record-nor-disclosure"

    record_type = _get(envelope, "recordType")
    floor = _floor_for(record_type)
    if floor is None:
        # Section 12.2: an unknown profile MUST fail closed, with a stated reason.
        return False, "profile-unknown"

    root = bytes.fromhex(_get(envelope, "root"))
    issuer = _get(envelope, "issuer")
    identity = {
        "record_type": record_type,
        "schema_version": _get(envelope, "schemaVersion"),
        "record_id": _get(envelope, "recordId"),
        "issuer_id": _get(issuer, "id"),
        "issuer_key_id": _get(issuer, "keyId"),
    }

    if has_record:
        return _verify_full(envelope, hash_alg, root, identity, type_maps, record_loader)
    return _verify_disclosed(envelope, hash_alg, root, floor)


def _verify_full(envelope, hash_alg, root, identity, type_maps, record_loader):
    if not _has(envelope, "salts"):
        # Section 7.3 rule 1. Without it a full copy has no route to any leaf hash.
        return False, "full-copy-without-salts"

    type_map = type_maps.get(identity["record_type"])
    if type_map is None:
        return False, "type-map-missing"

    body = _get(envelope, "record")
    if record_loader is not None and _has(body, "$recordFile"):
        body = record_loader(_get(body, "$recordFile"))

    leaf_count = _int(_get(envelope, "leafCount"))
    salt_entries = _get(envelope, "salts")

    # The reserved-namespace guard, the duplicate-key rejection and the fail-closed type-map
    # lookup all live inside build_tree, so this call is what makes class 15's reject row fire
    # BEFORE anything is compared against the root.
    _computed, leaves, _salts, _hashes = ref.build_tree(
        hash_alg, body, type_map, _ordering_only_master_salt(), **identity
    )

    if len(salt_entries) != leaf_count:
        # Section 11.1: the derived count and the declared one disagreeing MUST be a rejection,
        # not a warning and not a silent preference for either value.
        return False, "salts-length-not-leaf-count"
    if len(leaves) != leaf_count:
        return False, "leaf-count-mismatch"

    supplied = {}
    for entry in salt_entries:
        supplied[_segments_key(_segments(_get(entry, "segments")))] = \
            bytes.fromhex(_get(entry, "salt"))
    if len(supplied) != len(leaves):
        return False, "salts-duplicate-path"

    rebuilt = []
    for leaf in leaves:
        key = _segments_key(leaf.segments)
        if key not in supplied:
            return False, "salt-missing-for-leaf"
        rebuilt.append(ref.leaf_hash(hash_alg, leaf.segments, leaf.tag, leaf.value, supplied[key]))

    if ref.mth(hash_alg, rebuilt) != root:
        return False, "root-mismatch"
    return True, "ok"


def _ordering_only_master_salt():
    """A full copy carries per-leaf salts, so no master salt is needed to REBUILD one.

    Decision D4 is OPEN and this verifier must work under either answer, so it never derives a
    salt for verification: every salt is read from the `salts` array. This value only feeds the
    ordering pass inside build_tree, and leaf order is a function of paths alone.
    """
    return b"\x00" * 32


def _verify_disclosed(envelope, hash_alg, root, floor):
    if _has(envelope, "salts"):
        # Section 7.3 and 10.1: `salts` alongside `disclosure` is what would make a withheld
        # leaf's salt representable at all. Reject rather than repair.
        return False, "disclosed-copy-carries-salts"

    disclosure = _get(envelope, "disclosure")
    if _get(disclosure, "mode") != "selective":
        return False, "disclosure-mode-unknown"
    leaves = _get(disclosure, "leaves")
    if not leaves:
        return False, "disclosure-empty"

    tree_size = _int(_get(envelope, "leafCount"))
    seen_paths = set()
    seen_index = set()
    for entry in leaves:
        for field in ("segments", "index", "tag", "salt", "auditPath"):
            if not _has(entry, field):
                return False, "disclosed-leaf-missing-field"
        tag = _int(_get(entry, "tag"))
        empty_tag = tag in (ref.TAG_NULL, ref.TAG_EMPTY_ARRAY, ref.TAG_EMPTY_OBJECT)
        if empty_tag and _has(entry, "value"):
            return False, "disclosed-leaf-value-present-for-empty-tag"
        if not empty_tag and not _has(entry, "value"):
            # A leaf NAMED with its value withheld, while its salt ships anyway. This is the
            # shape of the class 17 leak: it looks like a disclosure and is not one.
            return False, "disclosed-leaf-named-without-value"

        segments = _segments(_get(entry, "segments"))
        key = _segments_key(segments)
        if key in seen_paths:
            return False, "disclosed-leaf-duplicate-path"
        seen_paths.add(key)
        index = _int(_get(entry, "index"))
        if index in seen_index:
            return False, "disclosed-leaf-duplicate-index"
        seen_index.add(index)

        value = _get(entry, "value")
        if isinstance(value, ref.NumberLiteral):
            # A numeric carrier is a canonical numeric STRING, never a JSON number: a JSON
            # number here would already have been through a float in most parsers.
            return False, "disclosed-leaf-numeric-carrier"

        # Section 10 step 1: recompute the leaf from its fields. A caller-supplied leaf hash is
        # never trusted, which is dogtag's most expensive scar (merkle.rs:86-91).
        leaf = ref.leaf_hash(hash_alg, segments, tag, value, bytes.fromhex(_get(entry, "salt")))
        path = [bytes.fromhex(h) for h in _get(entry, "auditPath")]
        if not ref.verify_inclusion(hash_alg, leaf, index, tree_size, path, root):
            return False, "inclusion-proof-failed"

    # Section 10.2, the minimum-disclosure floor.
    for required in floor:
        if _segments_key(required) not in seen_paths:
            return False, "minimum-disclosure-floor"
    return True, "ok"
