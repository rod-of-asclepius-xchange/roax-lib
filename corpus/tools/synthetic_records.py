"""Synthetic record fixtures and their type map: classes 5, 11, 13 and 15.

These records are authored for the corpus. They are not derived from, and do not reproduce, any
reference sample. Their type map is authored too, and says so on every entry: the record was
written to match the map rather than the map inferred from the record, which is the opposite of
the syntactic inference specification section 4 forbids.

They carry the corpus-only `recordType` `org.roax.corpus.synthetic`, which is deliberately NOT
in the `docs/profiles/` registry. It exists so that structural vectors do not have to borrow a
real health authority's profile identifier, and a record MUST NOT be issued under it.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixture_io  # noqa: E402
import roax_ref as ref  # noqa: E402
from corpus_plan import (  # noqa: E402
    ISSUER_ID,
    MASTER_SALT_A,
    RECORD_ID_A,
    SYNTHETIC_RECORD_TYPE,
    SYNTHETIC_SCHEMA_VERSION,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.dirname(HERE)
RECORD_DIR = os.path.join(CORPUS_DIR, "fixtures", "records")
TYPE_MAP_DIR = os.path.join(CORPUS_DIR, "type-maps")

AUTHORED = "corpus fixture: authored declaration, not derived from any reference schema"

# U+212A KELVIN SIGN followed by "elvin". Its NFC form is ASCII "Kelvin".
KELVIN_KEY = "Kelvin"

SYNTHETIC_TYPE_MAP = {
    "typeMapVersion": "1.0.0",
    "recordType": SYNTHETIC_RECORD_TYPE,
    "schemaVersion": SYNTHETIC_SCHEMA_VERSION,
    "sourceSchemas": [{
        "path": "corpus/fixtures/records",
        "note": "Authored for the corpus. No reference schema was consulted and none is cited, "
                "because these records do not come from one.",
    }],
    "entries": [
        # Class 5. The three-way structural distinction: an explicit null is a NULL leaf, while
        # an empty array and an empty object get tags 6 and 7 from the flattener and never
        # consult this map at all.
        {"pattern": "a.b", "jsonKind": "null", "tag": ref.TAG_NULL, "source": AUTHORED},
        {"pattern": "marker", "jsonKind": "string", "tag": ref.TAG_STRING, "source": AUTHORED},

        # Class 13. Both FHIR entry layouts, so that the same clinical content under the two
        # shapes can be shown to produce different roots.
        {"pattern": "fhirBundle.resourceType", "jsonKind": "string", "tag": ref.TAG_STRING,
         "source": AUTHORED},
        {"pattern": "fhirBundle.entry[*].fullUrl", "jsonKind": "string", "tag": ref.TAG_STRING,
         "source": AUTHORED},
        {"pattern": "fhirBundle.entry[*].resourceType", "jsonKind": "string",
         "tag": ref.TAG_STRING, "source": AUTHORED},
        {"pattern": "fhirBundle.entry[*].gender", "jsonKind": "string", "tag": ref.TAG_STRING,
         "source": AUTHORED},
        {"pattern": "fhirBundle.entry[*].resource.resourceType", "jsonKind": "string",
         "tag": ref.TAG_STRING, "source": AUTHORED},
        {"pattern": "fhirBundle.entry[*].resource.gender", "jsonKind": "string",
         "tag": ref.TAG_STRING, "source": AUTHORED},

        # Class 15's accept rows. `roax` and `roaxX` are ordinary record keys: no reserved path
        # is the bare segment KEY("roax"), so neither collides with anything.
        {"pattern": "roax", "jsonKind": "string", "tag": ref.TAG_STRING, "source": AUTHORED},
        {"pattern": "roaxX.foo", "jsonKind": "string", "tag": ref.TAG_STRING, "source": AUTHORED},
        # [KEY("a"), KEY("roax.foo")] cannot be written as a display pattern, because display
        # notation reads the dot as a segment boundary and section 5 admits keys containing one.
        # `**` reaches it without the pattern language having to grow an escape. This limit is
        # recorded in corpus/README.md rather than worked around silently.
        {"pattern": "a.**", "jsonKind": "string", "tag": ref.TAG_STRING, "source": AUTHORED},
        # Both spellings of the Kelvin key, so that the vector does not depend on whether an
        # implementation normalizes a type-map pattern before matching it. The specification
        # does not say which, and the corpus must not decide it - see corpus/README.md.
        {"pattern": KELVIN_KEY, "jsonKind": "string", "tag": ref.TAG_STRING, "source": AUTHORED},
        {"pattern": "Kelvin", "jsonKind": "string", "tag": ref.TAG_STRING, "source": AUTHORED},

        # Scalars for the type-tag and numeric classes inside a whole record.
        {"pattern": "counts.integer", "jsonKind": "number", "tag": ref.TAG_INTEGER,
         "source": AUTHORED},
        {"pattern": "counts.decimal", "jsonKind": "number", "tag": ref.TAG_DECIMAL,
         "source": AUTHORED},
        {"pattern": "counts.text", "jsonKind": "string", "tag": ref.TAG_STRING, "source": AUTHORED},
        {"pattern": "flag", "jsonKind": "boolean", "tag": ref.TAG_BOOL, "source": AUTHORED},
    ],
}

# (fixture file name, record body). Written as JSON text so that no re-serializer ever touches a
# numeric literal.
RECORD_FIXTURES = {
    # Class 5: three siblings differing at exactly one path.
    "structure-empty-array.json": '{\n  "a": { "b": [] },\n  "marker": "structure"\n}\n',
    "structure-empty-object.json": '{\n  "a": { "b": {} },\n  "marker": "structure"\n}\n',
    "structure-explicit-null.json": '{\n  "a": { "b": null },\n  "marker": "structure"\n}\n',

    # Class 13: the vaccination healthcert's flattened pseudo-FHIR entry layout, against the
    # genuine FHIR layout with a nested `.resource`. Same clinical content, different paths,
    # and therefore a different root. Normalizing one into the other silently breaks every
    # commitment already made against the first.
    "entry-flattened.json": (
        '{\n'
        '  "fhirBundle": {\n'
        '    "resourceType": "Bundle",\n'
        '    "entry": [\n'
        '      {\n'
        '        "fullUrl": "urn:uuid:ca6f8564-0529-4454-9b6f-41456d5663c5",\n'
        '        "resourceType": "Patient",\n'
        '        "gender": "female"\n'
        '      }\n'
        '    ]\n'
        '  }\n'
        '}\n'
    ),
    "entry-normalized.json": (
        '{\n'
        '  "fhirBundle": {\n'
        '    "resourceType": "Bundle",\n'
        '    "entry": [\n'
        '      {\n'
        '        "fullUrl": "urn:uuid:ca6f8564-0529-4454-9b6f-41456d5663c5",\n'
        '        "resource": {\n'
        '          "resourceType": "Patient",\n'
        '          "gender": "female"\n'
        '        }\n'
        '      }\n'
        '    ]\n'
        '  }\n'
        '}\n'
    ),

    # Class 15 accept rows, as whole records so that the guard runs where it actually runs.
    "guard-bare-roax.json": '{\n  "roax": "an ordinary field",\n  "marker": "guard"\n}\n',
    "guard-roax-x.json": '{\n  "roaxX": { "foo": "ordinary" },\n  "marker": "guard"\n}\n',
    "guard-nested-roax-dotted.json": '{\n  "a": { "roax.foo": "ordinary" },\n  "marker": "guard"\n}\n',
    "guard-kelvin-key.json": '{\n  "\\u212Aelvin": "ordinary",\n  "marker": "guard"\n}\n',

    # Class 15 reject row: a record key that IS a reserved path.
    "guard-reserved-collision.json": '{\n  "roax.recordId": "squatted",\n  "marker": "guard"\n}\n',

    # A record exercising every scalar tag at once, so that class 7's discrimination is tested
    # through a whole tree and not only through isolated leaves.
    "typed-scalars.json": (
        '{\n'
        '  "counts": { "integer": 5, "decimal": 0.010, "text": "5" },\n'
        '  "flag": true,\n'
        '  "marker": "typed"\n'
        '}\n'
    ),
}

# (vector name, class, fixture file, issuerKeyId or None)
RECORD_VECTOR_PLAN = [
    ("record-structure-empty-array", 5, "structure-empty-array.json", None),
    ("record-structure-empty-object", 5, "structure-empty-object.json", None),
    ("record-structure-explicit-null", 5, "structure-explicit-null.json", None),
    ("record-entry-layout-flattened", 13, "entry-flattened.json", None),
    ("record-entry-layout-normalized", 13, "entry-normalized.json", None),
    ("record-guard-bare-roax", 15, "guard-bare-roax.json", None),
    ("record-guard-roax-x", 15, "guard-roax-x.json", None),
    ("record-guard-nested-roax-dotted", 15, "guard-nested-roax-dotted.json", None),
    ("record-guard-kelvin-key", 15, "guard-kelvin-key.json", None),
    ("record-typed-scalars", 7, "typed-scalars.json", None),
    ("record-typed-scalars-with-key-id", 7, "typed-scalars.json",
     "did:web:corpus.roax.invalid#key-1"),
]

# Class 11. Type-map assertions over the synthetic map, whose bindings are checkable by reading
# one short file. The MOH assertions are added by build_corpus from the derived maps.
SYNTHETIC_TYPE_MAP_VECTORS = [
    ("typemap-synthetic-integer", [{"key": "counts"}, {"key": "integer"}], "number", ref.TAG_INTEGER),
    ("typemap-synthetic-decimal", [{"key": "counts"}, {"key": "decimal"}], "number", ref.TAG_DECIMAL),
    ("typemap-synthetic-string", [{"key": "counts"}, {"key": "text"}], "string", ref.TAG_STRING),
    ("typemap-synthetic-bool", [{"key": "flag"}], "boolean", ref.TAG_BOOL),
    ("typemap-synthetic-null", [{"key": "a"}, {"key": "b"}], "null", ref.TAG_NULL),
    ("typemap-synthetic-bare-roax-key", [{"key": "roax"}], "string", ref.TAG_STRING),
]

SYNTHETIC_FAIL_CLOSED_VECTORS = [
    # The same path at a DIFFERENT observed JSON kind. The map is keyed by (pattern, jsonKind),
    # so binding `counts.integer` as a number says nothing about it arriving as a string, and
    # the fail-closed rule applies rather than a coercion.
    ("typemap-synthetic-wrong-kind", [{"key": "counts"}, {"key": "integer"}], "string"),
    ("typemap-synthetic-uncovered-path", [{"key": "counts"}, {"key": "notInTheMap"}], "string"),
    ("typemap-synthetic-uncovered-root", [{"key": "somethingElse"}], "string"),
]


def emit_fixtures():
    """Emit the record fixtures. Idempotent; the corpus build calls this first."""
    # Every .json under RECORD_DIR comes from RECORD_FIXTURES, so it can be set-compared and an
    # orphan left by a rename is detectable. TYPE_MAP_DIR is NOT declared: the three derived MOH
    # maps there belong to build_type_maps.py.
    fixture_io.owns(RECORD_DIR)
    for name, text in RECORD_FIXTURES.items():
        fixture_io.emit(os.path.join(RECORD_DIR, name), text)
    fixture_io.emit(os.path.join(TYPE_MAP_DIR, SYNTHETIC_RECORD_TYPE + ".json"),
                    json.dumps(SYNTHETIC_TYPE_MAP, indent=2, ensure_ascii=False) + "\n")


def synthetic_type_map():
    return ref.TypeMap(SYNTHETIC_TYPE_MAP)


def build_record_vectors():
    import json_literal

    emit_fixtures()
    type_map = synthetic_type_map()
    out = []
    for name, cls, fixture, key_id in RECORD_VECTOR_PLAN:
        # Parsed from the text this module holds, never read back from disk. Reading the file
        # would make a hand-edited fixture agree with itself, which is what check mode exists
        # to catch.
        record = json_literal.loads(RECORD_FIXTURES[fixture])
        root, leaves, _salts, _hashes = ref.build_tree(
            "SHA-256", record, type_map, bytes.fromhex(MASTER_SALT_A),
            SYNTHETIC_RECORD_TYPE, SYNTHETIC_SCHEMA_VERSION, RECORD_ID_A, ISSUER_ID, key_id,
        )
        vec = {
            "name": name,
            "class": cls,
            "recordType": SYNTHETIC_RECORD_TYPE,
            "schemaVersion": SYNTHETIC_SCHEMA_VERSION,
            "issuerId": ISSUER_ID,
            "recordFile": "corpus/fixtures/records/" + fixture,
            "masterSaltHex": MASTER_SALT_A,
            "recordId": RECORD_ID_A,
            "leafCount": len(leaves),
            "root": root.hex(),
        }
        if key_id is not None:
            vec["issuerKeyId"] = key_id
        out.append(vec)

    roots = {v["name"]: v["root"] for v in out}
    # The three class 5 siblings MUST give three distinct roots. dogtag collapses all three to
    # one leaf (flatten.rs:96-115), so this is the vector that catches an implementation that
    # inherited that.
    structural = {roots["record-structure-empty-array"],
                  roots["record-structure-empty-object"],
                  roots["record-structure-explicit-null"]}
    if len(structural) != 3:
        raise SystemExit("corpus defect: class 5 siblings do not produce three distinct roots")
    if roots["record-entry-layout-flattened"] == roots["record-entry-layout-normalized"]:
        raise SystemExit("corpus defect: class 13 entry layouts produce the same root")
    return out


def build_type_map_vectors():
    type_map = synthetic_type_map()
    out = []
    for name, segments, kind, expect in SYNTHETIC_TYPE_MAP_VECTORS:
        resolved = type_map.resolve(segments, kind)
        if resolved != expect:
            raise SystemExit(f"corpus defect: {name} resolved {resolved}, expected {expect}")
        out.append({
            "name": name,
            "class": 11,
            "recordType": SYNTHETIC_RECORD_TYPE,
            "segments": segments,
            "jsonKind": kind,
            "expectTag": resolved,
        })
    for name, segments, kind in SYNTHETIC_FAIL_CLOSED_VECTORS:
        try:
            type_map.resolve(segments, kind)
        except ref.RoaxError:
            pass
        else:
            raise SystemExit(f"corpus defect: {name} resolved when it should fail closed")
        out.append({
            "name": name,
            "class": 11,
            "recordType": SYNTHETIC_RECORD_TYPE,
            "segments": segments,
            "jsonKind": kind,
            "expectFailClosed": True,
        })
    return out
