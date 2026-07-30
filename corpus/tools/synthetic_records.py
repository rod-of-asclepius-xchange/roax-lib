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
import roax_ref as ref
import salt_sets  # noqa: E402
from corpus_plan import (  # noqa: E402
    ISSUER_ID,
    RECORD_ID_A,
    SYNTHETIC_RECORD_TYPE,
    SYNTHETIC_SCHEMA_VERSION,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.dirname(HERE)
RECORD_DIR = os.path.join(CORPUS_DIR, "fixtures", "records")
TYPE_MAP_DIR = os.path.join(CORPUS_DIR, "type-maps")

AUTHORED = "corpus fixture: authored declaration, not derived from any reference schema"

# Class 19's key site: `é` composed, whose decomposed twin `e\u0301` renders identically.
#
# The map declares ONE spelling, the composed one, and that is what makes the key-site vector
# discriminate ruled decision D14a rather than agree with either reading of it. The decomposed
# twin is deliberately NOT a constant here: it lives in the committed fixture text as the
# escape `\u0301`, so nothing between this module and those bytes can quietly compose it. The
# U+212A KELVIN SIGN key is the same situation now that its duplicate pattern is gone: the map
# below declares the ASCII spelling ALONE, so `\u212Aelvin` reaches it only through NFC and
# `record-guard-kelvin-key` discriminates D14a instead of resolving under either reading.
KEY_ACCENTED_NFC = "é"

SYNTHETIC_TYPE_MAP = {
    # MAJOR under `docs/type-maps.md` section 5.2, because this revision REMOVED a selector:
    # the duplicate U+212A Kelvin pattern that stood in for decision D14 while it was open.
    # That section governs the published `type-maps/` artifacts, and this map is corpus-only
    # and listed by no registry, so the rule binds it by analogy rather than by governance. It
    # is worth following anyway: nothing else tells a reader comparing two checkouts of this
    # file that the selector set changed.
    "typeMapVersion": "2.0.0",
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
        # Class 19's value pair. The PATTERN is ASCII, so type-map matching is not implicated;
        # only the VALUE differs between the two forms, which is what keeps this vector about
        # normalization in the hashing path and nothing else.
        {"pattern": "accented", "jsonKind": "string", "tag": ref.TAG_STRING, "source": AUTHORED},
        # Class 19's KEY pair, and the one entry in this map that discriminates ruled decision
        # D14a. The pattern is authored in the COMPOSED spelling ONLY. The two key fixtures
        # differ in nothing else, so a matcher comparing raw resolves the composed record and
        # fails closed on the decomposed one, while a matcher comparing NFC resolves both to the
        # same tag and therefore to one root. Do not add the decomposed spelling as a second
        # entry: that is the Kelvin workaround this map used to carry, and its whole purpose was
        # to stop a vector depending on an answer nobody had given.
        {"pattern": KEY_ACCENTED_NFC, "jsonKind": "string", "tag": ref.TAG_STRING,
         "source": AUTHORED},

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
        # The ASCII spelling of the Kelvin key ONLY. Under ruled decision D14a the lookup
        # matches over NFC-normalized keys, so `record-guard-kelvin-key`, whose record key is
        # `\u212Aelvin`, reaches this entry through normalization. The U+212A duplicate this
        # map carried while D14 was open is removed rather than kept as a belt: keeping it would
        # leave the vector passing under either reading, which is the whole reason it proved
        # nothing before.
        {"pattern": "Kelvin", "jsonKind": "string", "tag": ref.TAG_STRING, "source": AUTHORED},

        # The three RULED FHIR bindings of `docs/type-maps.md` section 1.3, exercised here on the
        # SYNTHETIC profile. These rows assert the ruled TAG SEMANTICS and they are NOT the FHIR
        # profile binding: the published FHIR artifacts still carry their pre-ruling `unresolved`
        # rows, because regeneration is blocked on the 34 merged object states of
        # `docs/type-maps.md` section 6 and hand-editing a generated artifact would replace a
        # blocked regeneration with an unreproducible one. corpus/README.md says the same.
        #
        # base64Binary -> BYTES, over the DECODED OCTETS. The canonical RFC 4648 section 4
        # spelling is an input-admissibility condition rather than the committed value, so a
        # non-canonical spelling of the same bytes is refused before it can be committed
        # (specification section 6.3).
        {"pattern": "blob.bytes", "jsonKind": "string", "tag": ref.TAG_BYTES, "source": AUTHORED},
        # And the same base64 TEXT at a STRING-bound path, which is the OTHER half of the ruling:
        # a profile that means the transport spelling gets the spelling, so the two paths carry
        # identical record text and commit different bytes. Without this pair, "BYTES commits the
        # decoded octets" is a claim no vector separates from "BYTES commits the text".
        {"pattern": "blob.text", "jsonKind": "string", "tag": ref.TAG_STRING, "source": AUTHORED},
        # Narrative.div -> STRING over the ESCAPED XHTML TEXT, with no parsing and no
        # reserialization. STRING selects `utf8(NFC(s))` and nothing else, so the markup travels
        # as characters (specification section 6.1).
        {"pattern": "narrative.div", "jsonKind": "string", "tag": ref.TAG_STRING,
         "source": AUTHORED},
        # FHIR primitive-array null placeholders -> RULED: publish NO NULL binding, and REJECT a
        # record carrying one until a versioned schema and type-map revision admits the FHIR
        # representation. The ruling is expressed by an ABSENCE, so the entry below binds `string`
        # and deliberately declares nothing for `null`, and the reject vector over this path is
        # what makes that absence checkable. Adding a `null` row here would rule the question the
        # other way from inside a data file.
        {"pattern": "name[*].given[*]", "jsonKind": "string", "tag": ref.TAG_STRING,
         "source": AUTHORED},

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
    # Class 19's VALUE site. The SAME record twice, differing only in whether the accented value
    # is written decomposed or composed. Section 6.1 normalizes a value to NFC before encoding,
    # so the two must produce ONE root. The path is deliberately ASCII, so this pair is about
    # normalization in the hashing path and about nothing else.
    "nfc-value-nfd.json": '{\n  "marker": "structure",\n  "accented": "e\\u0301"\n}\n',
    "nfc-value-nfc.json": '{\n  "marker": "structure",\n  "accented": "\\u00e9"\n}\n',

    # Class 19's KEY site, which decision D14a is what made buildable. The same record twice,
    # differing only in whether the accented KEY is written decomposed or composed. The VALUE is
    # ASCII and identical, so nothing but the key spelling can move the root.
    #
    # This pair is the corpus's discriminator for D14a, and it discriminates in both directions.
    # The synthetic map declares the composed key alone, so a matcher comparing raw resolves
    # `nfc-key-nfc` and fails closed on `nfc-key-nfd` with `type-map-uncovered-path`, and the
    # vector's expectSameRoot is unreachable. A matcher comparing NFC resolves both, and because
    # encode_path already normalizes each KEY segment (section 5.1) the two encode to the same
    # leaf path and therefore to ONE root.
    "nfc-key-nfd.json": '{\n  "marker": "structure",\n  "e\\u0301": "same"\n}\n',
    "nfc-key-nfc.json": '{\n  "marker": "structure",\n  "\\u00e9": "same"\n}\n',
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

    # The three RULED FHIR bindings of `docs/type-maps.md` section 1.3, over the synthetic
    # profile. `bytes` and `text` carry the SAME base64 characters at differently bound paths, so
    # the pair separates "BYTES commits the decoded octets" from "BYTES commits the text": a
    # runner that hashed the base64 characters at the BYTES path would give the two leaves equal
    # value bytes. `div` carries escaped XHTML, which STRING commits as characters with no
    # parsing and no reserialization.
    "fhir-ruled-bindings.json": (
        '{\n'
        '  "blob": {\n'
        '    "bytes": "SGVsbG8sIFJPQVgh",\n'
        '    "text": "SGVsbG8sIFJPQVgh"\n'
        '  },\n'
        '  "narrative": {\n'
        '    "div": '
        '"<div xmlns=\\"http://www.w3.org/1999/xhtml\\">a &amp; b &lt;ok&gt;</div>"\n'
        '  },\n'
        '  "marker": "typed"\n'
        '}\n'
    ),

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
    ("record-fhir-ruled-bindings", 7, "fhir-ruled-bindings.json", None),
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


def _salt_doc(name, ordered):
    """Draw under --draw-salts, otherwise read the committed set. Never draw during a build."""
    if salt_sets.drawing():
        return salt_sets.draw(name, ordered, "path")
    return salt_sets.load(name)


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
        identity = (SYNTHETIC_RECORD_TYPE, SYNTHETIC_SCHEMA_VERSION, RECORD_ID_A, ISSUER_ID, key_id)
        ordered = ref.ordered_leaves(record, type_map, *identity)
        salt_doc = _salt_doc(name, ordered)
        salts = ref.salt_set_from_document(salt_doc, ordered)
        root, leaves, _salts, _hashes = ref.build_tree(
            "SHA-256", record, type_map, salts, *identity
        )
        vec = {
            "name": name,
            "class": cls,
            "recordType": SYNTHETIC_RECORD_TYPE,
            "schemaVersion": SYNTHETIC_SCHEMA_VERSION,
            "issuerId": ISSUER_ID,
            "recordFile": "corpus/fixtures/records/" + fixture,
            "saltsFile": salt_sets.reference_for(name),
            "saltPairing": "path",
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


# Class 19. (vector name, site, salt-set name, NFD fixture, NFC fixture).
#
# BOTH SITES ARE BUILT. docs/conformance-corpus.md class 19 always required both, because an
# implementation can normalize values and not keys; the key row was withheld while decision D14
# was open, since resolving a decomposed KEY through the type map settles whether the lookup
# normalizes. D14 is ruled D14a, so the row now tests a decided question instead of deciding one.
NORMALIZATION_SITES = [
    ("normalization-nfc-value-end-to-end", "value", "normalization-nfc-value",
     "nfc-value-nfd.json", "nfc-value-nfc.json"),
    ("normalization-nfc-key-end-to-end", "key", "normalization-nfc-key",
     "nfc-key-nfd.json", "nfc-key-nfc.json"),
]


def build_normalization_vectors():
    """Class 19. One record in both Unicode forms at each site, asserting ONE root.

    Class 4 asserts NFC against NFD at LEAF level. This asserts it end to end, over the union of
    specification section 3.3, which is where the routes a leaf-level vector misses actually are:
    a reserved-leaf value written straight from the envelope, or a path segment re-encoded from a
    cached form. Both forms of a site share ONE salt set, because two sets would make the roots
    differ for a reason that has nothing to do with normalization (spec section 7, decision D4b).

    The KEY site additionally resolves its differing key through the type map, so it is the
    vector that pins ruled decision D14a: the synthetic map declares the composed spelling
    alone, and a matcher comparing raw fails closed on the decomposed twin instead of producing
    the one root asserted here.
    """
    import json_literal

    emit_fixtures()
    type_map = synthetic_type_map()
    identity = (SYNTHETIC_RECORD_TYPE, SYNTHETIC_SCHEMA_VERSION, RECORD_ID_A, ISSUER_ID, None)

    out = []
    for name, site, salt_name, nfd_fixture, nfc_fixture in NORMALIZATION_SITES:
        # ONE salt set per site, resolved ONCE and used for both forms. Drawing inside the loop
        # would give each form its own set under --draw-salts, and the two roots would then
        # differ for a reason that has nothing to do with normalization - which is exactly what
        # the guard below caught the first time this was written. The two forms have identical
        # ENCODED paths, since encode_path normalizes each key, so one set pairs against both.
        first = json_literal.loads(RECORD_FIXTURES[nfd_fixture])
        ordered = ref.ordered_leaves(first, type_map, *identity)
        salt_doc = _salt_doc(salt_name, ordered)

        roots = []
        for fixture in (nfd_fixture, nfc_fixture):
            record = json_literal.loads(RECORD_FIXTURES[fixture])
            form_ordered = ref.ordered_leaves(record, type_map, *identity)
            salts = ref.salt_set_from_document(salt_doc, form_ordered)
            root, _leaves, _s, _h = ref.build_tree("SHA-256", record, type_map, salts, *identity)
            roots.append(root.hex())

        if roots[0] != roots[1]:
            raise SystemExit(
                f"corpus defect: the NFD and NFC forms of the class-19 {site} record produced "
                f"different roots ({roots[0]} vs {roots[1]}); section 6.1 requires one"
            )

        out.append({
            "name": name,
            "class": 19,
            "site": site,
            "recordFileNFD": "corpus/fixtures/records/" + nfd_fixture,
            "recordFileNFC": "corpus/fixtures/records/" + nfc_fixture,
            "saltsFile": salt_sets.reference_for(salt_name),
            "recordType": SYNTHETIC_RECORD_TYPE,
            "schemaVersion": SYNTHETIC_SCHEMA_VERSION,
            "recordId": RECORD_ID_A,
            "issuerId": ISSUER_ID,
            "expectSameRoot": True,
            "root": roots[0],
        })

    # The class is not complete until both sites are present, and that requirement is on the SET
    # rather than on any one vector, so it is checked here rather than in the corpus schema.
    sites = {vector["site"] for vector in out}
    if sites != {"value", "key"}:
        raise SystemExit(
            f"corpus defect: class 19 must carry both the value and the key site, found {sites}"
        )
    # The two sites MUST NOT share a root, or one salt set has been reused across them and the
    # key vector would be asserting the value vector's arithmetic.
    if len({vector["root"] for vector in out}) != len(out):
        raise SystemExit("corpus defect: two class-19 sites produced the same root")
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
