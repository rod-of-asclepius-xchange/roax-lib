"""Envelope fixtures for classes 14, 15 and 17, and the vectors that point at them.

Class 14 (the minimum-disclosure floor) and class 17 (a disclosed copy must not leak a withheld
leaf's salt) are properties of an ENVELOPE, so they need envelopes rather than leaves. Class 14
needs no type map at all: a disclosed copy carries each revealed leaf's tag explicitly, and a
verifier recomputes the leaf hash from the fields it was given. Only the two full-copy rows of
class 17 and the class 15 guard rows need a record, and those use the synthetic profile.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import envelope as env  # noqa: E402
import roax_ref as ref  # noqa: E402
import synthetic_records as syn  # noqa: E402
from corpus_plan import (  # noqa: E402
    ISSUER_ID,
    ISSUER_KEY_ID,
    MASTER_SALT_A,
    RECORD_ID_A,
    SYNTHETIC_RECORD_TYPE,
    SYNTHETIC_SCHEMA_VERSION,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.dirname(HERE)
ENVELOPE_DIR = os.path.join(CORPUS_DIR, "fixtures", "envelopes")
RECORD_DIR = os.path.join(CORPUS_DIR, "fixtures", "records")

# Profiles class 14 is exercised against, with the schemaVersion each profile document declares
# and a plausible value for every path in its floor. The values are corpus-authored: nothing
# here reproduces a reference sample.
FLOOR_PROFILES = [
    ("hl7.fhir.bundle", "4.0.1", {"resourceType": "Bundle"}),
    ("sg.gov.moh.pdt-healthcert", "2.0",
     {"version": "pdt-healthcert-v2.0", "type": "PCR", "validFrom": "2026-07-28T00:00:00Z"}),
    ("sg.gov.moh.recovery-healthcert", "2.0",
     {"version": "rec-healthcert-v2.0", "type": "PCR", "validFrom": "2026-07-28T00:00:00Z",
      "validUntil": "2026-10-28T00:00:00Z"}),
    ("sg.gov.moh.vaccination-healthcert", "1.0",
     {"validFrom": "2026-07-28T00:00:00Z", "notarisationMetadata.reference": "urn:uuid:notary-1"}),
]

# Leaves present in every class 14 tree but never in its floor, so that a disclosed copy is a
# genuine subset and the withheld ones have something to withhold.
WITHHELD_LEAVES = [
    (["id"], "TEST001"),
    (["fhirVersion"], "4.0.1"),
    (["patient", "birthDate"], "1965-08-09"),
    (["patient", "gender"], "female"),
]


def _identity(record_type, schema_version, key_id):
    return {
        "record_type": record_type,
        "schema_version": schema_version,
        "record_id": RECORD_ID_A,
        "issuer_id": ISSUER_ID,
        "issuer_key_id": key_id,
    }


def _floor_tree(hash_alg, record_type, schema_version, floor_values, key_id):
    """Build a tree from an explicit leaf set. Returns ordered leaves, salts, hashes and root."""
    leaves = ref.reserved_leaves(record_type, schema_version, RECORD_ID_A, ISSUER_ID, key_id)
    for path, value in floor_values.items():
        leaves.append(ref.Leaf([{"key": path}], ref.TAG_STRING, value))
    for segments, value in WITHHELD_LEAVES:
        leaves.append(ref.Leaf([{"key": k} for k in segments], ref.TAG_STRING, value))

    encoded = sorted(((ref.encode_path(leaf.segments), leaf) for leaf in leaves),
                     key=lambda pair: pair[0])
    ordered = [leaf for _, leaf in encoded]
    salts = [ref.derive_salt(hash_alg, bytes.fromhex(MASTER_SALT_A), RECORD_ID_A, leaf.segments)
             for leaf in ordered]
    hashes = [ref.leaf_hash(hash_alg, leaf.segments, leaf.tag, leaf.value, salt)
              for leaf, salt in zip(ordered, salts)]
    return ordered, salts, hashes, ref.mth(hash_alg, hashes)


def _base_envelope(record_type, schema_version, root, leaf_count, key_id):
    issuer = {"id": ISSUER_ID}
    if key_id is not None:
        issuer["keyId"] = key_id
    return {
        "canon": ref.CANON,
        "hashAlg": "SHA-256",
        "recordType": record_type,
        "schemaVersion": schema_version,
        "recordId": RECORD_ID_A,
        "root": root.hex(),
        "leafCount": leaf_count,
        "issuer": issuer,
    }


def _disclosed_leaf(hash_alg, ordered, salts, index):
    leaf = ordered[index]
    entry = {
        "segments": leaf.segments,
        "displayPath": ref.display_path(leaf.segments),
        "index": index,
        "tag": leaf.tag,
    }
    if leaf.tag not in (ref.TAG_NULL, ref.TAG_EMPTY_ARRAY, ref.TAG_EMPTY_OBJECT):
        entry["value"] = leaf.value
    entry["salt"] = salts[index].hex()
    entry["auditPath"] = [h.hex() for h in ref.inclusion_path(hash_alg, index, _hashes_cache[id(ordered)])]
    return entry


_hashes_cache = {}


def _write(name, envelope):
    os.makedirs(ENVELOPE_DIR, exist_ok=True)
    path = os.path.join(ENVELOPE_DIR, name + ".json")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n")
    return "corpus/fixtures/envelopes/" + name + ".json"


def _write_text(name, text):
    os.makedirs(ENVELOPE_DIR, exist_ok=True)
    path = os.path.join(ENVELOPE_DIR, name + ".json")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return "corpus/fixtures/envelopes/" + name + ".json"


def _vector(name, cls, file_path, expect_accept, _intent):
    """One envelope vector. `reason` is filled in by `build_envelope_fixtures` with the CODE the
    verifier actually returned, never with the prose describing what the fixture is for.

    That matters more than it looks. `guard-reject-reserved-collision` carries a placeholder
    root, because a record whose key collides with a reserved path cannot be hashed at all. An
    implementation that never runs the reserved-namespace guard rejects it on `root-mismatch`
    and would pass a vector that only asserted a boolean. The reason is what proves the guard
    ran, and class 15's reject rows are the whole subject of the class.
    """
    return {
        "name": name,
        "class": cls,
        "envelopeFile": file_path,
        "expectAccept": expect_accept,
    }


def build_floor_vectors(hash_alg):
    """Class 14. One accept per profile, one accept for the keyId edge, one reject per floor path."""
    out = []
    for record_type, schema_version, floor_values in FLOOR_PROFILES:
        ordered, salts, hashes, root = _floor_tree(
            hash_alg, record_type, schema_version, floor_values, ISSUER_KEY_ID
        )
        _hashes_cache[id(ordered)] = hashes
        by_path = {ref.display_path(leaf.segments): i for i, leaf in enumerate(ordered)}

        floor_paths = list(env.RESERVED_FLOOR) + list(floor_values)
        # Everything in the floor plus roax.issuer.keyId, which the record committed.
        full_set = floor_paths + [ref.RESERVED_ISSUER_KEY_ID]

        def make(name, paths, cls, expect, reason, tamper=None):
            envelope = _base_envelope(record_type, schema_version, root, len(ordered), ISSUER_KEY_ID)
            envelope["disclosure"] = {
                "mode": "selective",
                "leaves": [_disclosed_leaf(hash_alg, ordered, salts, by_path[p]) for p in paths],
            }
            if tamper:
                tamper(envelope)
            return _vector(name, cls, _write(name, envelope), expect, reason)

        slug = record_type.replace(".", "-")
        out.append(make(
            f"floor-{slug}-complete", full_set, 14, True,
            "carries every non-redactable path the profile declares, plus roax.issuer.keyId",
        ))
        # The upper edge of the floor. roax.issuer.keyId is committed inside the root but
        # OPTIONAL to disclose: requiring it would permanently bind an anchored record to the
        # key it was issued under, which specification section 12.2 rules out. Without this
        # vector an implementation that over-tightens the floor to every reserved path passes
        # class 14 while breaking key rotation, and nothing else in the corpus would catch it.
        out.append(make(
            f"floor-{slug}-omits-issuer-key-id", floor_paths, 14, True,
            "omits roax.issuer.keyId, which is committed but OPTIONAL to disclose",
        ))
        for omitted in floor_paths:
            remaining = [p for p in full_set if p != omitted]
            out.append(make(
                f"floor-{slug}-omits-{omitted.replace('.', '-')}", remaining, 14, False,
                f"omits the non-redactable path {omitted}",
            ))
    return out


def build_salt_leak_vectors(hash_alg):
    """Class 17. The violation VERIFIES against the root, so only these rows catch it."""
    record_type, schema_version, floor_values = FLOOR_PROFILES[2]
    ordered, salts, hashes, root = _floor_tree(
        hash_alg, record_type, schema_version, floor_values, ISSUER_KEY_ID
    )
    _hashes_cache[id(ordered)] = hashes
    by_path = {ref.display_path(leaf.segments): i for i, leaf in enumerate(ordered)}
    revealed = list(env.RESERVED_FLOOR) + list(floor_values)
    withheld_index = by_path["patient.birthDate"]

    def disclosed():
        envelope = _base_envelope(record_type, schema_version, root, len(ordered), ISSUER_KEY_ID)
        envelope["disclosure"] = {
            "mode": "selective",
            "leaves": [_disclosed_leaf(hash_alg, ordered, salts, by_path[p]) for p in revealed],
        }
        return envelope

    out = []
    out.append(_vector(
        "salt-leak-exact-revealed-set", 17,
        _write("salt-leak-exact-revealed-set", disclosed()), True,
        "carries the salt of every leaf it reveals and of no other leaf",
    ))

    # "The same copy with one withheld leaf's salt added." The envelope schema forbids a `salts`
    # array here, so the only shape this can take is a disclosure entry that NAMES a leaf and
    # ships its salt while withholding its value. That is the leak wearing a disclosure's
    # clothes, and it is the row a naive verifier - one that skips entries with no value - lets
    # through while every other check still passes.
    leaky = disclosed()
    named_only = _disclosed_leaf(hash_alg, ordered, salts, withheld_index)
    del named_only["value"]
    leaky["disclosure"]["leaves"].append(named_only)
    out.append(_vector(
        "salt-leak-named-leaf-without-value", 17,
        _write("salt-leak-named-leaf-without-value", leaky), False,
        "ships a withheld leaf's salt under an entry that names the leaf but withholds its value",
    ))

    with_salts = disclosed()
    with_salts["salts"] = [
        {"segments": leaf.segments, "salt": salt.hex()} for leaf, salt in zip(ordered, salts)
    ]
    out.append(_vector(
        "salt-leak-disclosed-copy-with-salts-array", 17,
        _write("salt-leak-disclosed-copy-with-salts-array", with_salts), False,
        "a disclosed copy carrying the full-copy `salts` array, which would leak every withheld salt",
    ))

    with_master = disclosed()
    with_master["masterSalt"] = MASTER_SALT_A
    out.append(_vector(
        "salt-leak-disclosed-copy-with-master-salt", 17,
        _write("salt-leak-disclosed-copy-with-master-salt", with_master), False,
        "masterSalt MUST NEVER appear in any envelope, full or disclosed (section 7.3 rule 3)",
    ))

    out.extend(_full_copy_salt_vectors(hash_alg))
    return out


def _full_copy_salt_vectors(hash_alg):
    """The two count relationships JSON Schema cannot express, on a real full copy."""
    type_map = syn.synthetic_type_map()
    import json_literal
    record, record_text = json_literal.load_file(os.path.join(RECORD_DIR, "typed-scalars.json"))
    root, ordered, salts, _hashes = ref.build_tree(
        hash_alg, record, type_map, bytes.fromhex(MASTER_SALT_A),
        SYNTHETIC_RECORD_TYPE, SYNTHETIC_SCHEMA_VERSION, RECORD_ID_A, ISSUER_ID,
    )
    salt_entries = [{"segments": leaf.segments, "salt": salt.hex()}
                    for leaf, salt in zip(ordered, salts)]

    def full(name, entries, leaf_count, expect, reason, cls=17):
        envelope = _base_envelope(SYNTHETIC_RECORD_TYPE, SYNTHETIC_SCHEMA_VERSION, root,
                                  leaf_count, None)
        envelope["record"] = "@@RECORD@@"
        envelope["salts"] = entries
        text = json.dumps(envelope, indent=2, ensure_ascii=False)
        # The record body is spliced in as its ORIGINAL bytes. Re-serializing it here would put
        # a JSON number through a Python float on the way, which is the one thing section 6.4
        # forbids without exception.
        indented = "\n".join(
            ("  " + line) if i else line
            for i, line in enumerate(record_text.rstrip("\n").splitlines())
        )
        text = text.replace('"@@RECORD@@"', indented) + "\n"
        return _vector(name, cls, _write_text(name, text), expect, reason)

    # `docs/conformance-corpus.md` class 17 lists the omitted-leaf row and the wrong-length row
    # separately because they are two different failures. Building the first as `salts[:-1]`
    # with the declared leafCount unchanged would collapse them: both would stop at the length
    # comparison and the leaf-without-a-salt path would never run. So the omitted-leaf fixture
    # keeps the array at the right LENGTH and repoints one entry at a path that is not in the
    # tree, which is also the realistic shape of the bug.
    stray = [dict(e) for e in salt_entries]
    stray[-1] = {"segments": [{"key": "notALeafInThisTree"}], "salt": stray[-1]["salt"]}
    duplicated = [dict(e) for e in salt_entries]
    duplicated[-1] = {"segments": duplicated[0]["segments"], "salt": duplicated[-1]["salt"]}

    return [
        full("full-copy-complete-salts", salt_entries, len(ordered), True,
             "a full copy carrying the salt of every leaf of the union"),
        full("full-copy-salts-omit-one-leaf", stray, len(ordered), False,
             "one leaf of the union has no salt, so it has no route to a hash"),
        full("full-copy-salts-duplicate-path", duplicated, len(ordered), False,
             "two salt entries address the same path, so one leaf is unsalted while the count "
             "still matches"),
        full("full-copy-salts-length-not-leaf-count", salt_entries, len(ordered) + 1, False,
             "leafCount disagrees with the derived count, which section 11.1 makes a rejection"),
    ]


def build_guard_vectors(hash_alg):
    """Class 15. The guard runs on a whole record, so these are full copies."""
    import json_literal

    type_map = syn.synthetic_type_map()
    out = []
    cases = [
        ("guard-accept-bare-roax", "guard-bare-roax.json", True,
         "an ordinary record field named roax collides with no reserved path"),
        ("guard-accept-roax-x", "guard-roax-x.json", True,
         "roaxX is a different key entirely"),
        ("guard-accept-nested-roax-dotted", "guard-nested-roax-dotted.json", True,
         "the guard applies to the FIRST segment only, and this path differs in segment count"),
        ("guard-accept-kelvin-key", "guard-kelvin-key.json", True,
         "a first-segment key that changes under NFC and still does not begin with roax."),
        ("guard-reject-reserved-collision", "guard-reserved-collision.json", False,
         "a record key that IS a reserved path"),
    ]
    for name, fixture, expect, reason in cases:
        record, record_text = json_literal.load_file(os.path.join(RECORD_DIR, fixture))
        envelope = {
            "canon": ref.CANON,
            "hashAlg": "SHA-256",
            "recordType": SYNTHETIC_RECORD_TYPE,
            "schemaVersion": SYNTHETIC_SCHEMA_VERSION,
            "recordId": RECORD_ID_A,
            "root": "0" * 64,
            "leafCount": 5,
            "issuer": {"id": ISSUER_ID},
        }
        if expect:
            root, ordered, salts, _h = ref.build_tree(
                hash_alg, record, type_map, bytes.fromhex(MASTER_SALT_A),
                SYNTHETIC_RECORD_TYPE, SYNTHETIC_SCHEMA_VERSION, RECORD_ID_A, ISSUER_ID,
            )
            envelope["root"] = root.hex()
            envelope["leafCount"] = len(ordered)
            envelope["salts"] = [{"segments": leaf.segments, "salt": salt.hex()}
                                 for leaf, salt in zip(ordered, salts)]
        else:
            # A rejected record has no root at all, so the envelope carries a placeholder and
            # the guard must fire before anything is hashed. An implementation that checks the
            # root first reports the wrong reason and fails this vector for the right one.
            envelope["salts"] = [{"segments": [{"key": p}], "salt": "0" * 32}
                                 for p in list(env.RESERVED_FLOOR) + ["marker"]]
        envelope["record"] = "@@RECORD@@"
        ordered_keys = ["canon", "hashAlg", "recordType", "schemaVersion", "recordId", "root",
                        "leafCount", "issuer", "record", "salts"]
        envelope = {k: envelope[k] for k in ordered_keys if k in envelope}
        text = json.dumps(envelope, indent=2, ensure_ascii=False)
        indented = "\n".join(
            ("  " + line) if i else line
            for i, line in enumerate(record_text.rstrip("\n").splitlines())
        )
        text = text.replace('"@@RECORD@@"', indented) + "\n"
        out.append(_vector(name, 15, _write_text(name, text), expect, reason))
    return out


def build_algorithm_vectors(hash_alg):
    """Sections 7.4 H3 and 12.2: unknown algorithm and unknown profile fail closed.

    Tagged class 11, and the choice is worth stating. `docs/conformance-corpus.md` has no class
    for "an unknown algorithm or profile fails closed", but specification section 12.2 says of
    the unknown-profile rule that it "is the same rule section 4.2 applies to an unknown path,
    applied one level up" - and section 4.2 is exactly what class 11 tests. Filing these under
    class 14 instead would have inflated the disclosure floor's count with vectors that are not
    about the floor.
    """
    record_type, schema_version, floor_values = FLOOR_PROFILES[2]
    ordered, salts, hashes, root = _floor_tree(
        hash_alg, record_type, schema_version, floor_values, None
    )
    _hashes_cache[id(ordered)] = hashes
    by_path = {ref.display_path(leaf.segments): i for i, leaf in enumerate(ordered)}
    revealed = list(env.RESERVED_FLOOR) + list(floor_values)

    def disclosed(**overrides):
        envelope = _base_envelope(record_type, schema_version, root, len(ordered), None)
        envelope["disclosure"] = {
            "mode": "selective",
            "leaves": [_disclosed_leaf(hash_alg, ordered, salts, by_path[p]) for p in revealed],
        }
        envelope.update(overrides)
        return envelope

    return [
        _vector("algorithm-sha-256-accepted", 11,
                _write("algorithm-sha-256-accepted", disclosed()), True,
                "SHA-256 is the only algorithm ROAX-CANON/1 defines a construction for"),
        _vector("algorithm-poseidon-fails-closed", 11,
                _write("algorithm-poseidon-fails-closed",
                       disclosed(hashAlg="Poseidon-BN254")), False,
                "Poseidon-BN254 is registered but unparameterized, so a v1 verifier's allow-list "
                "excludes it and it fails closed with a stated reason (section 7.4 H3)"),
        _vector("profile-unknown-fails-closed", 11,
                _write("profile-unknown-fails-closed",
                       disclosed(recordType="com.example.not-a-profile")), False,
                "an unknown profile MUST fail closed with a stated reason and never default "
                "to a guess (section 12.2)"),
    ]


def build_envelope_fixtures(hash_alg):
    out = []
    out.extend(build_floor_vectors(hash_alg))
    out.extend(build_guard_vectors(hash_alg))
    out.extend(build_salt_leak_vectors(hash_alg))
    out.extend(build_algorithm_vectors(hash_alg))

    # Every fixture is RUN here with implementation A before it reaches the corpus, and the
    # reason code it returns becomes the vector's assertion. A fixture whose verdict does not
    # match its vector is a corpus defect and fails the build.
    type_maps = {SYNTHETIC_RECORD_TYPE: syn.synthetic_type_map()}
    import json_literal
    for vec in out:
        path = os.path.join(CORPUS_DIR, os.path.relpath(vec["envelopeFile"], "corpus"))
        with open(path, "r", encoding="utf-8") as handle:
            envelope = json_literal.loads(handle.read())
        accepted, reason = env.verify(envelope, type_maps)
        if accepted != vec["expectAccept"]:
            raise SystemExit(
                f"corpus defect: {vec['name']} expected accept={vec['expectAccept']} "
                f"but implementation A said {accepted} ({reason})"
            )
        vec["reason"] = reason
    return out
