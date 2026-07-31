"""Envelope fixtures for classes 14, 15, 17, 18 and 20, and the vectors that point at them.

Class 14 (the minimum-disclosure floor) and class 17 (a disclosed copy must not leak a withheld
leaf's salt) are properties of an ENVELOPE, so they need envelopes rather than leaves. Class 14
needs no type map at all: a disclosed copy carries each revealed leaf's tag explicitly, and a
verifier recomputes the leaf hash from the fields it was given. Only the two full-copy rows of
class 17 and the class 15 guard rows need a record, and those use the synthetic profile.

Class 18's type-map binding rows and the `typemap-floor-*` half of class 14 are the first fixtures
here to carry a `typeMap` member at all, and class 20's four are a different kind of fixture
again: they are the copies a conforming implementation must REPRODUCE, not ones it merely reads.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import envelope as env  # noqa: E402
import fixture_io  # noqa: E402
import roax_ref as ref
import salt_sets  # noqa: E402
import synthetic_records as syn  # noqa: E402
from corpus_plan import (  # noqa: E402
    ISSUER_ID,
    ISSUER_KEY_ID,
    RECORD_ID_A,
    RECORD_ID_B,
    SYNTHETIC_RECORD_TYPE,
    SYNTHETIC_SCHEMA_VERSION,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.dirname(HERE)
ENVELOPE_DIR = os.path.join(CORPUS_DIR, "fixtures", "envelopes")

# Profiles class 14 is exercised against, with the schemaVersion each profile document declares
# and a plausible value for every path in its floor. The values are corpus-authored: nothing
# here reproduces a reference sample.
#
# Each floor path is SEGMENTS, matching `envelope.PROFILE_FLOORS`. The vaccination profile's
# `notarisationMetadata.reference` is two of them: writing it as one dotted key here is what
# made the whole family agree with a floor no real record could satisfy.
FLOOR_PROFILES = [
    ("hl7.fhir.bundle", "4.0.1",
     [([{"key": "resourceType"}], "Bundle")]),
    ("sg.gov.moh.pdt-healthcert", "2.0",
     [([{"key": "version"}], "pdt-healthcert-v2.0"),
      ([{"key": "type"}], "PCR"),
      ([{"key": "validFrom"}], "2026-07-28T00:00:00Z")]),
    ("sg.gov.moh.recovery-healthcert", "2.0",
     [([{"key": "version"}], "rec-healthcert-v2.0"),
      ([{"key": "type"}], "PCR"),
      ([{"key": "validFrom"}], "2026-07-28T00:00:00Z"),
      ([{"key": "validUntil"}], "2026-10-28T00:00:00Z")]),
    ("sg.gov.moh.vaccination-healthcert", "1.0",
     [([{"key": "validFrom"}], "2026-07-28T00:00:00Z"),
      ([{"key": "notarisationMetadata"}, {"key": "reference"}], "urn:uuid:notary-1")]),
]

# Leaves present in every class 14 tree but never in its floor, so that a disclosed copy is a
# genuine subset and the withheld ones have something to withhold.
WITHHELD_LEAVES = [
    ([{"key": "id"}], "TEST001"),
    ([{"key": "fhirVersion"}], "4.0.1"),
    ([{"key": "patient"}, {"key": "birthDate"}], "1965-08-09"),
    ([{"key": "patient"}, {"key": "gender"}], "female"),
]


def _path_key(segments):
    """A comparison key over structured segments. Never a rendered display string.

    `display_path` renders KEY("a.b") and KEY("a") -> KEY("b") identically, so an index keyed on
    it keeps working after the floor is fixed and hides the same bug one layer up (section 5.2).
    """
    return tuple(("k", ref.nfc(s["key"])) if "key" in s else ("i", s["index"]) for s in segments)


def _slug(segments):
    """A file-name token for a path. Naming only; nothing is ever resolved back through it."""
    return "-".join(s["key"].replace(".", "-") if "key" in s else str(s["index"])
                    for s in segments)


def _reserved_floor_paths():
    """The four reserved paths as segments. Each is ONE key carrying the dotted name (11.2)."""
    return [[{"key": p}] for p in env.RESERVED_FLOOR]


def _identity(record_type, schema_version, key_id):
    return {
        "record_type": record_type,
        "schema_version": schema_version,
        "record_id": RECORD_ID_A,
        "issuer_id": ISSUER_ID,
        "issuer_key_id": key_id,
    }


def _salts_for(name, ordered):
    """Draw under --draw-salts, otherwise read the committed set.

    Envelope fixtures CARRY their salts, and fixture_io compares a fixture byte for byte against
    the committed file, so these values have to be stable across builds. Under decision D4b they
    cannot be recomputed (spec section 7), so they are drawn once and committed exactly like
    every other salt set. Path-keyed: these records are hand-authored, so nothing third-party is
    enumerated and the self-describing carrier is the right one.
    """
    if salt_sets.drawing():
        doc = salt_sets.draw(name, ordered, "path")
    else:
        doc = salt_sets.load(name)
    return ref.salt_set_from_document(doc, ordered)


# The type-map identifiers the class 14 and class 18 binding fixtures carry.
#
# CORPUS-AUTHORED PLACEHOLDERS IN THE RIGHT FORM, and stated as such rather than left to be
# mistaken for artifact digests. `schemas/envelope-1.0.json` pins the shape to
# `^sha256:[0-9a-f]{64}$`, and these satisfy it by hashing a corpus-owned label rather than by
# being typed out, so nothing here is a hand-written expected value. Neither identifier addresses
# any published artifact, and no vector using them asks a verifier to fetch, resolve or reproduce
# a content ID: they assert the ONE thing a single envelope can evidence, which is that the
# identifier a copy presents is the identifier its root commits. The class 18 row that needs real
# candidate bytes - a content ID that does not reproduce the committed leaf - stays unbuilt for
# the reason docs/conformance-corpus.md class 18 records about the registry rows.
def _authored_type_map_id(label):
    return "sha256:" + ref.H("SHA-256", f"ROAX-CORPUS/type-map/{label}".encode("ascii")).hex()


TYPE_MAP_ID = _authored_type_map_id("committed")
TYPE_MAP_ID_OTHER = _authored_type_map_id("a-different-artifact")
TYPE_MAP_VERSION = "1.0.0"


def _floor_tree(hash_alg, record_type, schema_version, floor_entries, key_id, type_map_id=None):
    """Build a tree from an explicit leaf set.

    Returns ordered leaves, salts, hashes, root and an index from path key to leaf position.

    `type_map_id` commits roax.typeMap.id as a further reserved leaf. It is conditional here
    exactly as it is in `ref.reserved_leaves`: the 54 fixtures that predate the section 4.2
    binding were issued without one and must keep the roots they were issued with.
    """
    leaves = ref.reserved_leaves(record_type, schema_version, RECORD_ID_A, ISSUER_ID, key_id,
                                 type_map_id)
    for segments, value in list(floor_entries) + WITHHELD_LEAVES:
        leaves.append(ref.Leaf(list(segments), ref.TAG_STRING, value))

    encoded = sorted(((ref.encode_path(leaf.segments), leaf) for leaf in leaves),
                     key=lambda pair: pair[0])
    ordered = [leaf for _, leaf in encoded]
    # Named from what determines the leaf set, so two fixtures with different shapes never
    # share a set. A collision that slipped through anyway fails loudly at load with
    # salt-missing rather than pairing the wrong salt to a leaf. The leaf count carries the
    # type-map leaf's presence, so the type-map family gets its own sets without a further token.
    salt_name = "envelope-floor-%s-%s-%d" % (
        record_type, "with-key-id" if key_id is not None else "no-key-id", len(ordered)
    )
    salt_set = _salts_for(salt_name, ordered)
    salts = [salt_set.for_leaf(leaf.segments) for leaf in ordered]
    hashes = [ref.leaf_hash(hash_alg, leaf.segments, leaf.tag, leaf.value, salt)
              for leaf, salt in zip(ordered, salts)]
    index = {_path_key(leaf.segments): i for i, leaf in enumerate(ordered)}
    return ordered, salts, hashes, ref.mth(hash_alg, hashes), index


def _base_envelope(record_type, schema_version, root, leaf_count, key_id, type_map_id=None):
    issuer = {"id": ISSUER_ID}
    if key_id is not None:
        issuer["keyId"] = key_id
    envelope = {
        "canon": ref.CANON,
        "hashAlg": "SHA-256",
        "recordType": record_type,
        "schemaVersion": schema_version,
        "recordId": RECORD_ID_A,
    }
    if type_map_id is not None:
        # Ordered where schemas/envelope-1.0.json documents it, between schemaVersion and root.
        envelope["typeMap"] = {"id": type_map_id, "version": TYPE_MAP_VERSION}
    envelope["root"] = root.hex()
    envelope["leafCount"] = leaf_count
    envelope["issuer"] = issuer
    return envelope


def _disclosed_leaf(hash_alg, ordered, salts, hashes, index):
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
    entry["auditPath"] = [h.hex() for h in ref.inclusion_path(hash_alg, index, hashes)]
    return entry


# name -> the exact bytes emitted for that fixture. Every fixture is verified from this, never
# read back from disk: reading the file would make a hand edit agree with itself and leave check
# mode unable to fail. See fixture_io.
_generated = {}


def _emit(name, text):
    fixture_io.emit(os.path.join(ENVELOPE_DIR, name + ".json"), text)
    _generated[name] = text
    return "corpus/fixtures/envelopes/" + name + ".json"


def _write(name, envelope):
    return _emit(name, json.dumps(envelope, indent=2, ensure_ascii=False) + "\n")


def _write_text(name, text):
    return _emit(name, text)


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
    for record_type, schema_version, floor_entries in FLOOR_PROFILES:
        ordered, salts, hashes, root, by_path = _floor_tree(
            hash_alg, record_type, schema_version, floor_entries, ISSUER_KEY_ID
        )

        floor_paths = _reserved_floor_paths() + [segs for segs, _ in floor_entries]
        # Everything in the floor plus roax.issuer.keyId, which the record committed.
        full_set = floor_paths + [[{"key": ref.RESERVED_ISSUER_KEY_ID}]]

        def make(name, paths, cls, expect, reason, tamper=None):
            envelope = _base_envelope(record_type, schema_version, root, len(ordered), ISSUER_KEY_ID)
            envelope["disclosure"] = {
                "mode": "selective",
                "leaves": [_disclosed_leaf(hash_alg, ordered, salts, hashes, by_path[_path_key(p)])
                           for p in paths],
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
                f"floor-{slug}-omits-{_slug(omitted)}", remaining, 14, False,
                f"omits the non-redactable path {ref.display_path(omitted)}",
            ))
    return out


def build_identity_binding_vectors(hash_alg):
    """Class 14. The outer recordType is what SELECTS the floor, so it cannot select it alone.

    Specification section 11.3 states normatively that a field outside the root is a hint and
    never authority, and section 11.2 commits recordType, schemaVersion, recordId and issuer.id
    as leaves so that a disclosed copy can be checked against them. Nothing asserted that until
    these vectors: a verifier that reads the outer field and stops still passed every other
    class 14 row, because in those rows the two agree.

    The downgrade is concrete rather than theoretical. pdt's floor - version, type, validFrom -
    is a strict SUBSET of recovery's, which adds validUntil. So a holder of a recovery copy
    relabels the envelope as pdt, discloses exactly pdt's floor, and withholds the expiry. Every
    leaf hash is recomputed from the disclosed fields and every inclusion proof verifies against
    the genuine recovery root. docs/profiles/recovery-healthcert.md section 4 calls validUntil
    "the clearest single illustration of why the minimum-disclosure floor exists at all".
    """
    record_type, schema_version, floor_entries = FLOOR_PROFILES[2]
    ordered, salts, hashes, root, by_path = _floor_tree(
        hash_alg, record_type, schema_version, floor_entries, ISSUER_KEY_ID
    )

    pdt_type, _pdt_version, pdt_floor = FLOOR_PROFILES[1]
    pdt_paths = _reserved_floor_paths() + [segs for segs, _ in pdt_floor]

    def disclosed(name, paths, expect, reason, **overrides):
        envelope = _base_envelope(record_type, schema_version, root, len(ordered), ISSUER_KEY_ID)
        envelope["disclosure"] = {
            "mode": "selective",
            "leaves": [_disclosed_leaf(hash_alg, ordered, salts, hashes, by_path[_path_key(p)])
                       for p in paths],
        }
        envelope.update(overrides)
        return _vector(name, 18, _write(name, envelope), expect, reason)

    # CLASS 18, not 14. These four are the decision-D8 assertion: an outside-the-root field is a
    # hint and never authority (spec section 11.3), so a top-level identity field that disagrees
    # with the reserved leaf committed INSIDE the root must be rejected. They carried class 14
    # only because class 18 did not exist when they were written - the ruling that created it is
    # the same one that mandated a vector which FAILS an implementation trusting an outside field,
    # on the evidence that dogtag had the equivalent rule written down and shipped the bug anyway.
    # They are not floor vectors: the floor is about a disclosed copy OMITTING a non-redactable
    # path, and every one of these carries the whole floor precisely so it can fail only on the
    # binding.
    #
    # The whole recovery floor, so that these rows clear the floor and fail ONLY on the binding.
    # The accept side needs no vector of its own: all eight class 14 accepts already carry an
    # outer identity that agrees with its leaves, so a binding that over-tightens breaks them.
    full_set = _reserved_floor_paths() + [segs for segs, _ in floor_entries]

    return [
        disclosed(
            "identity-outer-record-type-downgrade", pdt_paths, False,
            "relabels a recovery copy as pdt to inherit pdt's shorter floor and withhold "
            "validUntil, with every inclusion proof still verifying against the genuine root",
            recordType=pdt_type,
        ),
        disclosed(
            "identity-outer-schema-version-mismatch", full_set, False,
            "an outer schemaVersion that disagrees with the roax.schemaVersion leaf",
            schemaVersion="9.9",
        ),
        disclosed(
            "identity-outer-record-id-mismatch", full_set, False,
            "an outer recordId that disagrees with the roax.recordId leaf",
            recordId=RECORD_ID_B,
        ),
        disclosed(
            "identity-outer-issuer-id-mismatch", full_set, False,
            "an outer issuer.id that disagrees with the roax.issuer.id leaf",
            issuer={"id": "did:web:not-the-issuer.invalid", "keyId": ISSUER_KEY_ID},
        ),
    ]


def build_salt_leak_vectors(hash_alg):
    """Class 17. The violation VERIFIES against the root, so only these rows catch it."""
    record_type, schema_version, floor_entries = FLOOR_PROFILES[2]
    ordered, salts, hashes, root, by_path = _floor_tree(
        hash_alg, record_type, schema_version, floor_entries, ISSUER_KEY_ID
    )
    revealed = _reserved_floor_paths() + [segs for segs, _ in floor_entries]
    withheld_index = by_path[_path_key([{"key": "patient"}, {"key": "birthDate"}])]

    def disclosed():
        envelope = _base_envelope(record_type, schema_version, root, len(ordered), ISSUER_KEY_ID)
        envelope["disclosure"] = {
            "mode": "selective",
            "leaves": [_disclosed_leaf(hash_alg, ordered, salts, hashes, by_path[_path_key(p)])
                       for p in revealed],
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
    named_only = _disclosed_leaf(hash_alg, ordered, salts, hashes, withheld_index)
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

    # A KNOWN member present with the WRONG JSON TYPE. `"salts": {}` is not an array, and an
    # implementation that reads a wrong-typed member as ABSENT has just switched its own
    # salt-leak guard off from outside: `verifyDisclosedCopy`'s check is "is `salts` present",
    # so a member that parses to nothing never trips it and the copy verifies while carrying a
    # `salts` object. **A guard that turns itself off on malformed input is worse than no guard,
    # because it reports safety it is not providing.**
    #
    # The row is cheap and the shape is general: the same reading applied to `typeMap` would
    # switch off the section 4.2 binding, and applied to `disclosure` or `record` it would change
    # which copy kind a verifier thinks it has. `schemas/envelope-1.0.json` types every one of
    # them, so the schema rejects this too - and that is the point of having both, since the
    # schema is not what runs inside a verifier.
    wrong_typed_salts = disclosed()
    wrong_typed_salts["salts"] = {}
    out.append(_vector(
        "salt-leak-disclosed-copy-with-wrong-typed-salts", 17,
        _write("salt-leak-disclosed-copy-with-wrong-typed-salts", wrong_typed_salts), False,
        "a disclosed copy whose `salts` member is present but is not an array, which a verifier "
        "reading it as absent would accept while carrying it",
    ))

    with_master = disclosed()
    with_master["masterSalt"] = "00" * 32  # any value; the field must not exist at all
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
    # The fixture text this build produced, not the file on disk. See fixture_io.
    record_text = syn.RECORD_FIXTURES["typed-scalars.json"]
    record = json_literal.loads(record_text)
    _identity = (SYNTHETIC_RECORD_TYPE, SYNTHETIC_SCHEMA_VERSION, RECORD_ID_A, ISSUER_ID)
    _ordered0 = ref.ordered_leaves(record, type_map, *_identity)
    root, ordered, salts, _hashes = ref.build_tree(
        hash_alg, record, type_map, _salts_for("envelope-full-copy-typed-scalars", _ordered0),
        *_identity,
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
        record_text = syn.RECORD_FIXTURES[fixture]
        record = json_literal.loads(record_text)
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
            _id2 = (SYNTHETIC_RECORD_TYPE, SYNTHETIC_SCHEMA_VERSION, RECORD_ID_A, ISSUER_ID)
            _ord2 = ref.ordered_leaves(record, type_map, *_id2)
            root, ordered, salts, _h = ref.build_tree(
                hash_alg, record, type_map, _salts_for("envelope-guard-" + name, _ord2), *_id2,
            )
            envelope["root"] = root.hex()
            envelope["leafCount"] = len(ordered)
            envelope["salts"] = [{"segments": leaf.segments, "salt": salt.hex()}
                                 for leaf, salt in zip(ordered, salts)]
        else:
            # A rejected record has no root at all, so the envelope carries a placeholder and
            # the guard must fire before anything is hashed. An implementation that checks the
            # root first reports the wrong reason and fails this vector for the right one.
            envelope["salts"] = [{"segments": p, "salt": "0" * 32}
                                 for p in _reserved_floor_paths() + [[{"key": "marker"}]]]
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
    record_type, schema_version, floor_entries = FLOOR_PROFILES[2]
    ordered, salts, hashes, root, by_path = _floor_tree(
        hash_alg, record_type, schema_version, floor_entries, None
    )
    revealed = _reserved_floor_paths() + [segs for segs, _ in floor_entries]

    def disclosed(**overrides):
        envelope = _base_envelope(record_type, schema_version, root, len(ordered), None)
        envelope["disclosure"] = {
            "mode": "selective",
            "leaves": [_disclosed_leaf(hash_alg, ordered, salts, hashes, by_path[_path_key(p)])
                       for p in revealed],
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


def build_type_map_binding_vectors(hash_alg):
    """Classes 14 and 18. The `roax.typeMap.id` binding, and who gets to trigger it.

    **These exist because no committed fixture carried a `typeMap` member**, so nothing in the
    corpus reached the binding of specification section 4.2 in either direction and an
    implementation could gate the whole check on that member without a single vector noticing.
    Gating it there is a real defect and was found by a human reading an implementation rather
    than by the suite: the member is supplied by the HOLDER, so a holder who deletes it and
    withholds the leaf produces a copy whose binding never runs and whose floor never asks, while
    every remaining inclusion proof stays genuine against the real root.

    The governing rule, and the reason this family is worth its fixtures:
    **a check whose execution is controlled by the party it constrains is not a check.**
    The trigger has to come from what is COMMITTED and never from what was PRESENTED.

    The verdicts are derived from the specification and not from any implementation's behaviour.
    Section 11.3 states that a field outside the root is a hint and never authority, section 11.2
    commits `roax.typeMap.id` as a reserved leaf and marks it mandatory to disclose, and section
    10.2 puts it in the floor of every profile. A copy whose outer member and committed leaf
    disagree - in either direction, including one side being absent - has therefore failed the
    binding before any floor is selected, which is why every reject row here carries
    `outer-identity-mismatch` and not `minimum-disclosure-floor`, exactly as the reserved half of
    the existing floor family does.

    **The both-absent case has no row here and needs none.** It is byte-indistinguishable from a
    legitimate envelope-1.0 copy issued before the binding existed, and the 34 committed floor
    fixtures ARE that shape, so an implementation that hard-rejects a copy lacking a type map
    already fails class 14. The upper edge is pinned; a row restating it would be inert.
    """
    out = []
    for record_type, schema_version, floor_entries in FLOOR_PROFILES:
        ordered, salts, hashes, root, by_path = _floor_tree(
            hash_alg, record_type, schema_version, floor_entries, ISSUER_KEY_ID, TYPE_MAP_ID
        )

        floor_paths = _reserved_floor_paths() + [[{"key": ref.RESERVED_TYPE_MAP_ID}]] \
            + [segs for segs, _ in floor_entries]
        full_set = floor_paths + [[{"key": ref.RESERVED_ISSUER_KEY_ID}]]

        def make(name, paths, cls, expect, reason, tamper=None, _rt=record_type,
                 _sv=schema_version, _root=root, _ordered=ordered, _salts=salts, _hashes=hashes,
                 _by_path=by_path):
            envelope = _base_envelope(_rt, _sv, _root, len(_ordered), ISSUER_KEY_ID, TYPE_MAP_ID)
            envelope["disclosure"] = {
                "mode": "selective",
                "leaves": [_disclosed_leaf(hash_alg, _ordered, _salts, _hashes,
                                           _by_path[_path_key(p)])
                           for p in paths],
            }
            if tamper:
                tamper(envelope)
            return _vector(name, cls, _write(name, envelope), expect, reason)

        slug = record_type.replace(".", "-")
        out.append(make(
            f"typemap-floor-{slug}-complete", full_set, 14, True,
            "carries the outer typeMap member, the committed roax.typeMap.id leaf and every "
            "other non-redactable path the profile declares",
        ))
        out.append(make(
            f"typemap-floor-{slug}-omits-roax-typeMap-id",
            [p for p in full_set if p != [{"key": ref.RESERVED_TYPE_MAP_ID}]], 14, False,
            "withholds roax.typeMap.id while the outer typeMap member still names one, which "
            "trips the binding before any floor is selected",
        ))

        # The two class 18 rows are built once, against the recovery tree, for the same reason
        # the existing identity family is: they are about the binding itself rather than about a
        # profile's floor, and a copy per profile would assert the same thing four times.
        if record_type != "sg.gov.moh.recovery-healthcert":
            continue

        def strip_type_map(envelope):
            del envelope["typeMap"]

        out.append(make(
            "identity-outer-type-map-id-mismatch", full_set, 18, False,
            "an outer typeMap.id that disagrees with the roax.typeMap.id leaf committed inside "
            "the root, with every inclusion proof still verifying",
            tamper=lambda e: e.__setitem__(
                "typeMap", {"id": TYPE_MAP_ID_OTHER, "version": TYPE_MAP_VERSION}),
        ))
        out.append(make(
            "identity-outer-type-map-member-stripped", full_set, 18, False,
            "the holder deletes the outer typeMap member while the root still commits "
            "roax.typeMap.id, so a verifier that gates the binding on that member never runs it",
            tamper=strip_type_map,
        ))
    return out


# Class 20's disclosure sets. The four reserved floor paths plus the synthetic profile's `marker`
# are what any accepted disclosed copy must carry; the rest are one leaf per carrier form.
# `a.hidden` and `roax.issuer.keyId` are in neither list, so the copy withholds two leaves and is
# a genuine selective disclosure rather than a full copy wearing one.
ROUND_TRIP_DISCLOSE = (
    [[{"key": p}] for p in ref.RESERVED_DISCLOSURE_FLOOR]
    + [[{"key": "marker"}]]
    + [[{"key": "a"}, {"key": "b"}]]              # 0 NULL - no value carrier at all
    + [[{"key": "flag"}]]                          # 1 BOOL - a JSON boolean
    + [[{"key": "counts"}, {"key": "text"}]]       # 2 STRING
    + [[{"key": "counts"}, {"key": "integer"}]]    # 3 INTEGER - a canonical STRING
    + [[{"key": "counts"}, {"key": "decimal"}]]    # 4 DECIMAL - a canonical STRING
    + [[{"key": "blob"}, {"key": "bytes"}]]        # 5 BYTES - lowercase HEX, not the base64
)


def build_round_trip_vectors(hash_alg):
    """Class 20. Issue, disclose, and verify the copy this build itself produced.

    **Every other class runs an implementation's VERIFIER against a third party's bytes.** Every
    committed envelope fixture was built by this generator, so nothing in the corpus ever ran an
    implementation's verifier against that implementation's own ISSUANCE output. An implementation
    could therefore emit disclosures its own verifier refused and still pass every vector - which
    is not hypothetical: it happened, and the corpus did not see it. Only a human reading the
    library did.

    So these vectors pin the PRODUCING side. A runner reads the record and the committed salt set,
    issues a full copy, discloses `disclosePaths` from that same commitment, compares BOTH
    envelopes it produced against the expected fixtures field by field, and then puts its own
    output through its own verifier and requires acceptance.

    **Pinned rather than behavioural**, unlike class 12. Class 12 must draw its own randomness
    because it is ABOUT randomness; nothing here is, so the salt set is a committed input and
    every field of both envelopes is fixed. A vector that only asserted "my verifier accepts my
    output" would be self-consistency, and a lax verifier would pass it while producing the same
    malformed copy. The static class 17 row `salt-leak-named-leaf-without-value` fails the lax
    verifier; these fail the lax producer. Neither closes the gap alone.
    """
    import json_literal

    type_map = syn.synthetic_type_map()
    record_text = syn.RECORD_FIXTURES["roundtrip-carriers.json"]
    record = json_literal.loads(record_text)

    out = []
    # BOTH vectors commit roax.typeMap.id, and that is a constraint on the class rather than a
    # choice. Specification section 11.2 marks that leaf ALWAYS emitted, so an ISSUANCE without
    # one is not something the current specification permits; `schemas/envelope-1.0.json` retains
    # the optional member for envelopes ALREADY ISSUED under it, which is what the other 54
    # fixtures are. A class-20 vector without a type map would therefore ask an implementation to
    # produce an envelope the specification forbids it to produce, and at least one library
    # refuses that at its issuance entry point - correctly. The two vectors vary the OTHER
    # reserved leaf instead.
    plans = [
        ("roundtrip-every-carrier-form", ISSUER_KEY_ID,
         "one leaf per disclosure carrier form, issued and then verified through this "
         "implementation's own verifier"),
        ("roundtrip-without-issuer-key-id", None,
         "the same round trip with issuer.keyId ABSENT, so the producer must emit NO leaf for it "
         "rather than a NULL leaf or an empty string - three different roots of which only one "
         "is right (specification section 11.2)"),
    ]
    for name, key_id, intent in plans:
        type_map_id = TYPE_MAP_ID
        identity = (SYNTHETIC_RECORD_TYPE, SYNTHETIC_SCHEMA_VERSION, RECORD_ID_A, ISSUER_ID,
                    key_id, type_map_id)
        ordered = ref.ordered_leaves(record, type_map, *identity)
        salt_set = _salts_for(name, ordered)
        root, ordered, salts, hashes = ref.build_tree(
            hash_alg, record, type_map, salt_set, *identity
        )
        by_path = {_path_key(leaf.segments): i for i, leaf in enumerate(ordered)}
        disclose = ROUND_TRIP_DISCLOSE + [[{"key": ref.RESERVED_TYPE_MAP_ID}]]

        full = _base_envelope(SYNTHETIC_RECORD_TYPE, SYNTHETIC_SCHEMA_VERSION, root,
                              len(ordered), key_id, type_map_id)
        full["record"] = "@@RECORD@@"
        full["salts"] = [{"segments": leaf.segments, "salt": salt.hex()}
                         for leaf, salt in zip(ordered, salts)]
        text = json.dumps(full, indent=2, ensure_ascii=False)
        # Spliced as its ORIGINAL bytes. Re-serializing would put a JSON number through a Python
        # float on the way, which section 6.4 forbids without exception.
        indented = "\n".join(("  " + line) if i else line
                             for i, line in enumerate(record_text.rstrip("\n").splitlines()))
        full_file = _write_text(name + "-full", text.replace('"@@RECORD@@"', indented) + "\n")

        disclosed = _base_envelope(SYNTHETIC_RECORD_TYPE, SYNTHETIC_SCHEMA_VERSION, root,
                                   len(ordered), key_id, type_map_id)
        # Sorted by LEAF INDEX rather than left in `disclosePaths` order. The specification fixes
        # no order for this array - each leaf carries its own index, so the order carries nothing -
        # and a class-20 runner has to COMPARE what it produced against this file. Leaving the
        # order to whatever the request happened to be would fail a conforming producer that
        # emitted the same leaves in another order, which is asserting something the
        # specification does not say. A runner sorts by index on both sides for the same reason.
        disclosed["disclosure"] = {
            "mode": "selective",
            "leaves": sorted(
                (_disclosed_leaf(hash_alg, ordered, salts, hashes, by_path[_path_key(p)])
                 for p in disclose),
                key=lambda entry: entry["index"],
            ),
        }
        disclosed_file = _write(name + "-disclosed", disclosed)

        vector = {
            "name": name,
            "class": 20,
            "recordType": SYNTHETIC_RECORD_TYPE,
            "schemaVersion": SYNTHETIC_SCHEMA_VERSION,
            "recordId": RECORD_ID_A,
            "issuerId": ISSUER_ID,
            "recordFile": "corpus/fixtures/records/roundtrip-carriers.json",
            "saltsFile": salt_sets.reference_for(name),
            "saltPairing": "path",
            "leafCount": len(ordered),
            "root": root.hex(),
            "disclosePaths": disclose,
            "expectedFullCopyFile": full_file,
            "expectedDisclosedCopyFile": disclosed_file,
            "expectSelfVerifies": True,
            "typeMap": {"id": type_map_id, "version": TYPE_MAP_VERSION},
            "intent": intent,
        }
        if key_id is not None:
            vector["issuerKeyId"] = key_id
        out.append(vector)
    return out


def verify_round_trip_fixtures(vectors):
    """Run implementation A's verifier over the two envelopes each class-20 vector produced.

    This is the generator half of the round trip. It is what makes `expectSelfVerifies` a claim
    the build has DISCHARGED for implementation A rather than an instruction handed to a reader:
    a fixture this generator emits and its own verifier refuses fails the build here, which is
    exactly the failure mode class 20 exists to make impossible to ship.
    """
    import json_literal
    type_maps = {SYNTHETIC_RECORD_TYPE: syn.synthetic_type_map()}
    for vec in vectors:
        for field in ("expectedFullCopyFile", "expectedDisclosedCopyFile"):
            name = os.path.basename(vec[field])[: -len(".json")]
            accepted, reason = env.verify(json_literal.loads(_generated[name]), type_maps)
            if not accepted:
                raise SystemExit(
                    f"corpus defect: {vec['name']} produced {vec[field]}, which this build's own "
                    f"verifier REFUSED ({reason}). That is the class 20 failure itself."
                )


def build_envelope_fixtures(hash_alg):
    # Every .json under ENVELOPE_DIR is produced here, so the directory can be set-compared and
    # a file left behind by a renamed vector is reported rather than sitting unreferenced.
    fixture_io.owns(ENVELOPE_DIR)
    out = []
    out.extend(build_floor_vectors(hash_alg))
    out.extend(build_identity_binding_vectors(hash_alg))
    out.extend(build_type_map_binding_vectors(hash_alg))
    out.extend(build_guard_vectors(hash_alg))
    out.extend(build_salt_leak_vectors(hash_alg))
    out.extend(build_algorithm_vectors(hash_alg))

    # Every fixture is RUN here with implementation A before it reaches the corpus, and the
    # reason code it returns becomes the vector's assertion. A fixture whose verdict does not
    # match its vector is a corpus defect and fails the build.
    #
    # What is verified is the bytes this build EMITTED, not the file on disk. Reading the file
    # back would let a hand-edited fixture be verified against itself and then be compared
    # against a corpus generated from that same edit, which is how `--check` used to pass on a
    # tampered fixture.
    type_maps = {SYNTHETIC_RECORD_TYPE: syn.synthetic_type_map()}
    import json_literal
    for vec in out:
        envelope = json_literal.loads(_generated[vec["name"]])
        accepted, reason = env.verify(envelope, type_maps)
        if accepted != vec["expectAccept"]:
            raise SystemExit(
                f"corpus defect: {vec['name']} expected accept={vec['expectAccept']} "
                f"but implementation A said {accepted} ({reason})"
            )
        vec["reason"] = reason
    return out
