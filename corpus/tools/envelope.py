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
#
# Every path is written as SEGMENTS, never in the display notation docs/profiles/ prints. The
# profile documents write `notarisationMetadata.reference`, and reading that as one key is the
# section 5.2 trap: no real record has a leaf whose key is that dotted string, so the floor
# would look enforced and match nothing. Segments make the mistake unrepresentable rather than
# merely corrected. Reserved paths are the one case that IS a single dotted key (section 11.2).
PROFILE_FLOORS = {
    # docs/profiles/fhir.md section 5
    "hl7.fhir.bundle": [[{"key": "resourceType"}]],
    # docs/profiles/pdt-healthcert.md section 4
    "sg.gov.moh.pdt-healthcert": [[{"key": "version"}], [{"key": "type"}],
                                  [{"key": "validFrom"}]],
    # docs/profiles/recovery-healthcert.md section 4
    "sg.gov.moh.recovery-healthcert": [[{"key": "version"}], [{"key": "type"}],
                                       [{"key": "validFrom"}], [{"key": "validUntil"}]],
    # docs/profiles/vaccination-healthcert.md section 4. `notarisationMetadata.reference` is TWO
    # segments.
    "sg.gov.moh.vaccination-healthcert": [[{"key": "validFrom"}],
                                          [{"key": "notarisationMetadata"}, {"key": "reference"}]],
    # The corpus-only profile. Not in the docs/profiles/ registry; see synthetic_records.py.
    "org.roax.corpus.synthetic": [[{"key": "marker"}]],
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
    # A reserved path IS a single KEY segment carrying the literal dotted name (section 11.2).
    # A profile path is already segments.
    return [[{"key": p}] for p in RESERVED_FLOOR] + [list(p) for p in profile]


def verify(envelope, type_maps):
    """Verify one envelope. Returns (accepted: bool, reason: str).

    `type_maps` maps recordType to a ref.TypeMap. A full copy carries its record body inline, so
    there is nothing to resolve by reference.
    """
    try:
        return _verify(envelope, type_maps)
    except ref.RoaxError as exc:
        return False, exc.code


def _verify(envelope, type_maps):
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
        # Section 7.3 rule 3: no envelope may carry any value from which the salt of an
        # undisclosed leaf could be obtained. Decision D4 is ruled D4b, so no such value exists
        # in the design and this check is vacuous today - kept because rule 3 binds any future
        # revision that reintroduces a derived salt, and because a seed added to an envelope
        # would hand every holder the ability to recompute every withheld leaf's salt in a copy
        # that still verified. Class 17 carries the matching vector.
        return False, "master-salt-in-envelope"

    has_record = _has(envelope, "record")
    has_disclosure = _has(envelope, "disclosure")
    if has_record and has_disclosure:
        return False, "record-and-disclosure-both-present"
    if not has_record and not has_disclosure:
        return False, "neither-record-nor-disclosure"

    record_type = _get(envelope, "recordType")
    if _floor_for(record_type) is None:
        # Section 12.2: an unknown profile MUST fail closed, with a stated reason. This is the
        # verifier's OWN allow-list and has the same shape as ALLOWED_HASH_ALGS above: it decides
        # whether this verifier can proceed at all, not which policy to enforce on a copy it can.
        # The floor itself is a policy and is selected further down, from the record type the
        # root commits rather than from this field.
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
        return _verify_full(envelope, hash_alg, root, identity, type_maps)
    return _verify_disclosed(envelope, hash_alg, root, identity)


def _verify_full(envelope, hash_alg, root, identity, type_maps):
    if not _has(envelope, "salts"):
        # Section 7.3 rule 1. Without it a full copy has no route to any leaf hash.
        return False, "full-copy-without-salts"

    type_map = type_maps.get(identity["record_type"])
    if type_map is None:
        return False, "type-map-missing"

    body = _get(envelope, "record")
    leaf_count = _int(_get(envelope, "leafCount"))
    salt_entries = _get(envelope, "salts")

    # The reserved-namespace guard, the duplicate-key rejection and the fail-closed type-map
    # lookup all live inside ordered_leaves, so this call is what makes class 15's reject row
    # fire BEFORE anything is compared against the root.
    #
    # ordered_leaves rather than build_tree: a full copy carries the salt of every leaf, so a
    # verifier needs the leaf ORDER and never a salt it did not read from the envelope. Under
    # the deleted D4a construction this had to call build_tree with a dummy master salt purely
    # to reach the ordering pass, which is exactly the awkwardness the split removed.
    leaves = ref.ordered_leaves(body, type_map, **identity)

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


def _verify_disclosed(envelope, hash_alg, root, identity):
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
    revealed = {}
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
        # Recorded only once the proof holds. A leaf value is authority when it is committed to
        # the root and not a moment earlier.
        revealed[key] = value

    # Section 11.3: fields outside the root are hints and NEVER authority. The identity is
    # therefore established against the leaves section 11.2 commits BEFORE any outer field is
    # used to select anything. Selecting the floor first and validating the field afterwards is
    # trust-then-verify - the shape of the dogtag scar section 11.3 records - and it is safe only
    # by accident of the current rules. pdt's floor is a strict subset of recovery's, so a
    # recovery copy relabelled pdt withholds `validUntil` with every proof still verifying
    # against the genuine root; both orders reject it, only this one rejects it by construction.
    for reserved, outer in (
        (ref.RESERVED_RECORD_TYPE, identity["record_type"]),
        (ref.RESERVED_SCHEMA_VERSION, identity["schema_version"]),
        (ref.RESERVED_RECORD_ID, identity["record_id"]),
        (ref.RESERVED_ISSUER_ID, identity["issuer_id"]),
    ):
        committed = revealed.get(_segments_key([{"key": reserved}]))
        if not isinstance(committed, str) or not isinstance(outer, str):
            # A copy withholding one of these has not said what it IS, so no floor can be chosen
            # for it. That is this code rather than `minimum-disclosure-floor`, which would claim
            # a floor was selected and then failed. It is why the reserved half of the floor
            # below is unreachable: absence is caught here first.
            return False, "outer-identity-mismatch"
        # NFC on BOTH sides. Each of these leaves is a STRING and is therefore committed
        # normalized (section 6.1), so the raw outer bytes are not what the root binds - the
        # same rule the segment keys above are already compared under. No corpus identity value
        # is non-ASCII, so this is unobservable across the shipped vectors either way.
        if ref.nfc(committed) != ref.nfc(outer):
            return False, "outer-identity-mismatch"

    # Section 10.2, the minimum-disclosure floor, selected from the record type the ROOT commits
    # and not from the envelope field. The binding above has just proved the two equal, so this
    # is the same floor either way - taking it from the leaf is what makes that a property of
    # the code rather than of the order these lines happen to sit in.
    committed_type = ref.nfc(revealed[_segments_key([{"key": ref.RESERVED_RECORD_TYPE}])])
    floor = _floor_for(committed_type)
    if floor is None:
        # Unreachable today: the gate in `_verify` already rejected an outer type absent from
        # PROFILE_FLOORS, and the binding proved this leaf NFC-equal to it. It stays because it
        # is what lets the lookup above read the LEAF; deleting it invites a future reader to
        # pass the outer field here instead and quietly restore the trust-then-verify shape.
        return False, "profile-unknown"
    for required in floor:
        if _segments_key(required) not in seen_paths:
            return False, "minimum-disclosure-floor"
    return True, "ok"
