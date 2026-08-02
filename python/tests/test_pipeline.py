"""Reader, flattener, tree, record and envelope tests.

PYTHONPATH=python/src python3 -m unittest discover -s python/tests -t python
"""

from __future__ import annotations

import re
import sys
import tempfile
import unicodedata
import unittest
from dataclasses import replace

from roax_canon import (
    DEFAULT_PROFILES,
    RESERVED_V1,
    RESERVED_V2,
    DisplayPatternTypeMap,
    Index,
    JsonNumber,
    Key,
    MappingSalts,
    PositionalSalts,
    Profile,
    RecordIdentity,
    RoaxError,
    audit_path,
    build_tree,
    disclosed_copy,
    draw_salt,
    encode_path,
    flatten,
    full_copy,
    issue,
    json_kind,
    leaf_hash,
    loads,
    merkle_tree_head,
    order_leaves,
    reserved_leaves,
    verify_envelope,
    verify_inclusion,
    VerifierConfig,
)
from roax_canon import display_path
from roax_canon.errors import ErrorCode
from roax_canon.jsonio import is_uri_string
from roax_canon.tree import largest_power_of_two_below

SYNTHETIC_MAP = {
    "typeMapVersion": "1.0.0",
    "recordType": "org.roax.corpus.synthetic",
    "schemaVersion": "1.0",
    "entries": [
        {"pattern": "marker", "jsonKind": "string", "tag": 2},
        {"pattern": "count", "jsonKind": "number", "tag": 3},
        {"pattern": "amount", "jsonKind": "number", "tag": 4},
        {"pattern": "flag", "jsonKind": "boolean", "tag": 1},
        {"pattern": "a.b", "jsonKind": "null", "tag": 0},
        {"pattern": "a.b", "jsonKind": "array", "tag": 6},
        {"pattern": "a.b", "jsonKind": "object", "tag": 7},
        {"pattern": "list[*]", "jsonKind": "string", "tag": 2},
        {"pattern": "deep.**", "jsonKind": "string", "tag": 2},
    ],
}

IDENTITY = RecordIdentity(
    record_type="org.roax.corpus.synthetic",
    schema_version="1.0",
    record_id="urn:uuid:11111111-1111-4111-8111-111111111111",
    issuer_id="did:web:example.invalid",
)


def resolver() -> DisplayPatternTypeMap:
    return DisplayPatternTypeMap(SYNTHETIC_MAP, source="<test>")


class TestJsonReader(unittest.TestCase):
    def test_uri_carrier_matches_the_schema_components(self):
        accepted = (
            "did:web:example.invalid",
            "urn:uuid:11111111-1111-4111-8111-111111111111",
            "https://example.invalid",
            "x://[::1]",
            "x://",
            "x:/",
            "x:y??q",
            "x:y?q?r",
        )
        rejected = (
            "not a uri",
            "x:y[",
            "x:y]",
            "x:y#z#q",
            "x:y?q[f]",
            "x://host/a[b]",
            "x:#",
            "x:?",
        )
        for value in accepted:
            with self.subTest(accepted=value):
                self.assertTrue(is_uri_string(value))
        for value in rejected:
            with self.subTest(rejected=value):
                self.assertFalse(is_uri_string(value))

    def test_numeric_literals_are_preserved_verbatim(self):
        parsed = loads('{"a": 0.010, "b": 9223372036854775807, "c": 1e999}')
        self.assertEqual(str(parsed["a"]), "0.010")
        self.assertEqual(str(parsed["b"]), "9223372036854775807")
        self.assertEqual(str(parsed["c"]), "1e999")
        for value in parsed.values():
            self.assertIsInstance(value, JsonNumber)

    def test_a_json_number_is_never_a_json_string(self):
        # The trap the obvious `parse_int=str` fix walks into. The type map is keyed on
        # observed kind, so a collapsed representation resolves the wrong tag.
        parsed = loads('{"n": 5, "s": "5"}')
        self.assertEqual(str(parsed["n"]), str(parsed["s"]))
        self.assertEqual(json_kind(parsed["n"]), "number")
        self.assertEqual(json_kind(parsed["s"]), "string")

    def test_section_3_2_rejections(self):
        for text, code in [
            ('{"a": NaN}', ErrorCode.NON_FINITE_NUMBER),
            ('{"a": Infinity}', ErrorCode.NON_FINITE_NUMBER),
            ('{"a": -Infinity}', ErrorCode.NON_FINITE_NUMBER),
            ('{"a": 1, "a": 2}', ErrorCode.DUPLICATE_KEY),
            ('{"a": {"b": 1, "b": 2}}', ErrorCode.DUPLICATE_KEY),
            ('{"a": "\\ud800"}', ErrorCode.UNPAIRED_SURROGATE),
            ('{"\\ud800": 1}', ErrorCode.UNPAIRED_SURROGATE),
        ]:
            with self.subTest(text=text):
                with self.assertRaises(RoaxError) as ctx:
                    loads(text)
                self.assertEqual(ctx.exception.code, code)

    def test_invalid_utf8_bytes_rejected(self):
        with self.assertRaises(RoaxError) as ctx:
            loads(b'{"a": "\xff"}')
        self.assertEqual(ctx.exception.code, ErrorCode.MALFORMED_JSON)


class TestReservedNamespaceGuard(unittest.TestCase):
    def test_rejected(self):
        for key in ("roax.recordType", "roax.recordId", "roax.anythingElse", "roax.recordIdX"):
            with self.subTest(key=key):
                with self.assertRaises(RoaxError) as ctx:
                    flatten(loads('{"%s": "x"}' % key), resolver())
                self.assertEqual(ctx.exception.code, ErrorCode.RESERVED_NAMESPACE)

    def test_accepted(self):
        # `roax` and `roaxX` carry no dot and collide with nothing. This reverses an
        # earlier draft of the specification, which rejected both.
        for record in ('{"roax": "x", "marker": "m"}', '{"roaxX": {"foo": "x"}, "marker": "m"}'):
            with self.subTest(record=record):
                permissive = DisplayPatternTypeMap(
                    {
                        **SYNTHETIC_MAP,
                        "entries": SYNTHETIC_MAP["entries"]
                        + [
                            {"pattern": "roax", "jsonKind": "string", "tag": 2},
                            {"pattern": "roaxX.foo", "jsonKind": "string", "tag": 2},
                        ],
                    }
                )
                self.assertTrue(flatten(loads(record), permissive))

    def test_only_the_first_segment(self):
        # `[KEY("a"), KEY("roax.foo")]` differs from every reserved path in segment count
        # and cannot collide, so rejecting it would be over-broad.
        deep = DisplayPatternTypeMap(
            {**SYNTHETIC_MAP, "entries": [{"pattern": "a.**", "jsonKind": "string", "tag": 2}]}
        )
        leaves = flatten(loads('{"a": {"roax.foo": "x"}}'), deep)
        self.assertEqual(leaves[0].path, (Key("a"), Key("roax.foo")))


class TestFlatten(unittest.TestCase):
    def test_empty_array_object_and_null_are_three_leaves(self):
        tags = set()
        for body in ('{"a": {"b": []}}', '{"a": {"b": {}}}', '{"a": {"b": null}}'):
            leaves = flatten(loads(body), resolver())
            self.assertEqual(len(leaves), 1)
            tags.add(leaves[0].tag)
        self.assertEqual(tags, {6, 7, 0})

    def test_empty_container_authorization_is_the_default(self):
        bare = DisplayPatternTypeMap(
            {**SYNTHETIC_MAP, "entries": [{"pattern": "a.b", "jsonKind": "null", "tag": 0}]}
        )
        with self.assertRaises(RoaxError) as ctx:
            flatten(loads('{"a": {"b": []}}'), bare)
        self.assertEqual(ctx.exception.code, ErrorCode.TYPE_UNRESOLVED)
        # And the opt-out, which is what the committed corpus asserts.
        leaves = flatten(loads('{"a": {"b": []}}'), bare, authorize_empty_containers=False)
        self.assertEqual(leaves[0].tag, 6)

    def test_unknown_path_fails_closed(self):
        with self.assertRaises(RoaxError) as ctx:
            flatten(loads('{"notInTheMap": "x"}'), resolver())
        self.assertEqual(ctx.exception.code, ErrorCode.TYPE_UNRESOLVED)

    def test_wrong_kind_fails_closed(self):
        with self.assertRaises(RoaxError) as ctx:
            flatten(loads('{"count": "5"}'), resolver())
        self.assertEqual(ctx.exception.code, ErrorCode.TYPE_UNRESOLVED)

    def test_tag_comes_from_the_map_not_the_literal(self):
        flattened = flatten(loads('{"count": 5, "amount": 5}'), resolver())
        leaves = {leaf.path[0].value: leaf.tag for leaf in flattened}
        self.assertEqual(leaves, {"count": 3, "amount": 4})

    def test_an_empty_container_record_is_one_leaf_so_the_zero_leaf_guard_never_fires(self):
        """Pins `FINDINGS.md` item 14, a SPECIFICATION DEFECT rather than a choice made here.

        Specification section 3.3 requires a record contributing zero leaves of its own to
        be rejected at issuance, and its own flatten makes that state unreachable: `{}` and
        `[]` each emit ONE leaf, at the zero-segment path.

        **Do not "fix" this into a rejection.** The guard is kept on the footing section
        9.1 gives `MTH([])` - a total function with an unreachable branch - and
        `docs/typescript-implementation-findings.md` finding 7 pins the same behaviour in
        `test/unit.ts`. Changing one library alone would manufacture exactly the
        cross-implementation divergence the corpus exists to catch.
        """
        bare = DisplayPatternTypeMap(
            {**SYNTHETIC_MAP, "entries": [{"pattern": "marker", "jsonKind": "string", "tag": 2}]}
        )
        for text, tag in (("{}", 7), ("[]", 6)):
            with self.subTest(record=text):
                leaves = flatten(loads(text), bare, authorize_empty_containers=False)
                self.assertEqual(len(leaves), 1, "zero-leaf is unreachable, so this is never 0")
                self.assertEqual(leaves[0].path, ())
                self.assertEqual(encode_path(leaves[0].path).hex(), "00000000")
                self.assertEqual(leaves[0].tag, tag)

        # Under the library-default authorized reading the record is refused too, but by
        # `type-unresolved` rather than `empty-record`: the zero-segment path is one no
        # display-pattern map can address. So the guard is unreachable under BOTH readings
        # of section 3.3, which is why no test can assert `empty-record` is ever raised.
        with self.assertRaises(RoaxError) as ctx:
            flatten(loads("{}"), bare)
        self.assertEqual(ctx.exception.code, ErrorCode.TYPE_UNRESOLVED)


class TestReservedLeaves(unittest.TestCase):
    def test_identity_fields_are_genuine_json_strings(self):
        required = ("record_type", "schema_version", "record_id", "issuer_id")
        optional = ("issuer_key_id", "type_map_id")
        base = {
            "record_type": IDENTITY.record_type,
            "schema_version": IDENTITY.schema_version,
            "record_id": IDENTITY.record_id,
            "issuer_id": IDENTITY.issuer_id,
            "issuer_key_id": None,
            "type_map_id": None,
        }
        for field_name in required + optional:
            with self.subTest(field=field_name):
                hostile = {**base, field_name: JsonNumber("5")}
                with self.assertRaises(RoaxError) as ctx:
                    RecordIdentity(**hostile)
                self.assertEqual(ctx.exception.code, ErrorCode.ENVELOPE_SHAPE)
                self.assertIn(field_name, ctx.exception.detail)

    def test_identity_schema_minima_and_uri_are_enforced_at_issuance(self):
        base = {
            "record_type": IDENTITY.record_type,
            "schema_version": IDENTITY.schema_version,
            "record_id": IDENTITY.record_id,
            "issuer_id": IDENTITY.issuer_id,
        }
        for field_name in ("schema_version", "record_id"):
            with self.subTest(empty=field_name):
                with self.assertRaises(RoaxError) as ctx:
                    RecordIdentity(**{**base, field_name: ""})
                self.assertEqual(ctx.exception.code, ErrorCode.ENVELOPE_SHAPE)

        for issuer_id in ("", "not a uri", "did:", "1did:value", "https: white space"):
            with self.subTest(issuer_id=issuer_id):
                with self.assertRaises(RoaxError) as ctx:
                    RecordIdentity(**{**base, "issuer_id": issuer_id})
                self.assertEqual(ctx.exception.code, ErrorCode.ENVELOPE_SHAPE)

        for issuer_id in (
            "did:web:example.invalid",
            "urn:uuid:11111111-1111-4111-8111-111111111111",
            "https://example.invalid/issuer",
        ):
            with self.subTest(valid_issuer_id=issuer_id):
                self.assertEqual(
                    RecordIdentity(**{**base, "issuer_id": issuer_id}).issuer_id,
                    issuer_id,
                )

        for record_type in ("synthetic", "Org.example.record", "org_example.record", "org..record"):
            with self.subTest(record_type=record_type):
                with self.assertRaises(RoaxError) as ctx:
                    RecordIdentity(**{**base, "record_type": record_type})
                self.assertEqual(ctx.exception.code, ErrorCode.ENVELOPE_SHAPE)

    def test_single_dotted_segment(self):
        for leaf in reserved_leaves(IDENTITY):
            self.assertEqual(len(leaf.path), 1)
            self.assertTrue(leaf.path[0].value.startswith("roax."))
            self.assertEqual(leaf.tag, 2)

    def test_v1_and_v2_sets(self):
        self.assertEqual(len(reserved_leaves(IDENTITY, reserved_set=RESERVED_V1)), 4)
        keyed = RecordIdentity(
            IDENTITY.record_type,
            IDENTITY.schema_version,
            IDENTITY.record_id,
            IDENTITY.issuer_id,
            issuer_key_id="did:web:example.invalid#key-1",
            type_map_id="sha256:" + "0" * 64,
        )
        self.assertEqual(len(reserved_leaves(keyed, reserved_set=RESERVED_V1)), 5)
        self.assertEqual(len(reserved_leaves(keyed, reserved_set=RESERVED_V2)), 6)

    def test_absent_key_id_emits_no_leaf(self):
        paths = {leaf.path[0].value for leaf in reserved_leaves(IDENTITY)}
        self.assertNotIn("roax.issuer.keyId", paths)

    def test_ordering_is_length_then_bytes(self):
        # The free self-check: under the envelope 1.0 reserved set the five leaves of a
        # keyed record sort recordId, issuer.id, recordType, issuer.keyId, schemaVersion,
        # which is 13, 14, 15, 17 and 18 UTF-8 bytes.
        keyed = RecordIdentity(
            IDENTITY.record_type,
            IDENTITY.schema_version,
            IDENTITY.record_id,
            IDENTITY.issuer_id,
            issuer_key_id="k",
        )
        order = [leaf.path[0].value for _, leaf in order_leaves(reserved_leaves(keyed))]
        self.assertEqual(
            order,
            [
                "roax.recordId",
                "roax.issuer.id",
                "roax.recordType",
                "roax.issuer.keyId",
                "roax.schemaVersion",
            ],
        )

    def test_normalization_collision_is_a_duplicate_path(self):
        # Two record keys that differ only in normalization form are distinct JSON member
        # names and the SAME path once NFC is applied (specification section 6.1), so the
        # sort in section 9 would have a tie it has no rule for. Rejected instead.
        accents = DisplayPatternTypeMap(
            {
                **SYNTHETIC_MAP,
                "entries": [
                    {"pattern": "\u00e9", "jsonKind": "string", "tag": 2},
                    {"pattern": "e\u0301", "jsonKind": "string", "tag": 2},
                ],
            }
        )
        record = loads('{"\\u00e9": "a", "e\\u0301": "b"}')
        self.assertEqual(len(record), 2, "the two keys are distinct JSON member names")
        with self.assertRaises(RoaxError) as ctx:
            build_tree(record, IDENTITY, accents, MappingSalts({}))
        self.assertEqual(ctx.exception.code, ErrorCode.DUPLICATE_PATH)


class TestTree(unittest.TestCase):
    def test_split_rule(self):
        self.assertEqual(
            [largest_power_of_two_below(n) for n in range(2, 10)], [1, 2, 2, 4, 4, 4, 4, 8]
        )

    def test_single_leaf_is_not_rehashed(self):
        leaf = bytes(range(32))
        self.assertEqual(merkle_tree_head([leaf]), leaf)

    def test_round_trip_every_size_to_130(self):
        leaves = [bytes([i % 256]) * 32 for i in range(130)]
        for n in list(range(1, 20)) + [63, 64, 65, 129, 130]:
            window = leaves[:n]
            root = merkle_tree_head(window)
            for i in range(n):
                path = audit_path(i, window)
                self.assertTrue(verify_inclusion(window[i], i, n, path, root), f"n={n} i={i}")

    def test_truncated_and_extended_paths_fail(self):
        leaves = [bytes([i]) * 32 for i in range(8)]
        root = merkle_tree_head(leaves)
        path = audit_path(3, leaves)
        self.assertFalse(verify_inclusion(leaves[3], 3, 8, path[:-1], root))
        self.assertFalse(verify_inclusion(leaves[3], 3, 8, path + [bytes(32)], root))

    def test_forged_tree_size_reproduces_the_section_11_1_measurement(self):
        # Specification section 11.1 measured this on Node and corrected the document with
        # it. Reproduced here independently, in Python, because the conclusion is what
        # makes leaf recomputation non-optional rather than belt and braces.
        from roax_canon.tree import _mth
        from roax_canon.hashes import get_hash

        h = get_hash("SHA-256")
        leaves = [bytes([i]) * 32 for i in range(8)]
        root = merkle_tree_head(leaves)
        internal = _mth(leaves[:4], h)
        sibling = _mth(leaves[4:], h)
        self.assertFalse(verify_inclusion(internal, 0, 8, [sibling], root), "honest size must fail")
        self.assertTrue(
            verify_inclusion(internal, 0, 2, [sibling], root),
            "a FORGED tree size of 2 verifies; leafCount is not authenticated",
        )


class TestRecordAndEnvelope(unittest.TestCase):
    def setUp(self):
        self.record = loads('{"marker": "m", "count": 5, "amount": 0.010, "flag": true}')
        self.built = issue(self.record, IDENTITY, resolver())
        self.registry = DEFAULT_PROFILES.with_profile(
            Profile("org.roax.corpus.synthetic", ((Key("marker"),),))
        )
        self.config = VerifierConfig(
            profiles=self.registry, resolvers={"org.roax.corpus.synthetic": resolver()}
        )

    def test_leaf_count_is_the_union(self):
        self.assertEqual(self.built.leaf_count, 4 + 4)

    def test_full_copy_round_trip(self):
        envelope = full_copy(self.built)
        result = verify_envelope(envelope, self.config)
        self.assertTrue(result.accepted, result.detail)

    def test_hash_ordered_envelope_verifies_under_the_registry_that_names_it(self):
        """The ordering axis, pinned HERE because no corpus vector reaches it.

        Every class-20 round-trip vector is path-ordered, so nothing in the corpus asks this
        package to issue a ``hash``-ordered envelope and then verify it. That is the surface on
        which the TypeScript library was found issuing an envelope its own verifier refused,
        which is exactly what conformance corpus class 20 exists to catch.
        """
        for ordering in ("path", "hash"):
            built = issue(self.record, replace(IDENTITY, ordering=ordering), resolver())
            envelope = full_copy(built)
            # The outer member is SELF-DESCRIPTION and is asserted here because no verifier
            # reads it, so nothing else in this suite can see it go missing. Both envelope
            # schemas define its ABSENCE as meaning `path`, so a hash-ordered copy without it
            # would assert an ordering it was not issued under.
            self.assertEqual(
                envelope.get("ordering"), None if ordering == "path" else ordering
            )
            # H2: the ordering comes from the anchoring registry. BOTH registry answers are
            # exercised, so the refusal of the wrong one is evidence rather than an untested
            # branch (specification section 9.5).
            for registry_says in ("path", "hash"):
                cfg = replace(self.config, anchored_ordering=registry_says)
                result = verify_envelope(envelope, cfg)
                with self.subTest(issued=ordering, registry=registry_says):
                    self.assertEqual(result.accepted, registry_says == ordering, result.detail)

    def test_the_ordering_leaf_is_committed_for_hash_and_for_nothing_else(self):
        """Specification section 11.2: the second conditional reserved leaf."""
        paths = {}
        for ordering in ("path", "hash"):
            built = issue(self.record, replace(IDENTITY, ordering=ordering), resolver())
            paths[ordering] = [display_path(leaf.path) for leaf in built.leaves]
        self.assertNotIn("roax.ordering", paths["path"])
        self.assertIn("roax.ordering", paths["hash"])
        self.assertEqual(len(paths["hash"]), len(paths["path"]) + 1)

    def test_an_empty_object_record_anchors_rather_than_being_rejected(self):
        """The half of `FINDINGS.md` item 14 that section 3.3 actually forbids.

        Section 3.3 requires a zero-leaf record to be "rejected at issuance rather than
        anchored". `{}` contributes one leaf, so it is anchored: it gets a leaf count and a
        root. Pinned here so the defect report stays checkable against the code.
        """
        bare = DisplayPatternTypeMap(
            {**SYNTHETIC_MAP, "entries": [{"pattern": "marker", "jsonKind": "string", "tag": 2}]}
        )
        salts = PositionalSalts([draw_salt() for _ in range(8)])
        built = build_tree(loads("{}"), IDENTITY, bare, salts, authorize_empty_containers=False)
        self.assertEqual(built.leaf_count, 1 + 4, "one record leaf plus the four reserved ones")
        self.assertEqual(len(built.root), 32)

        # It verifies only when the verifier carries the same structural setting; the
        # library default refuses the zero-segment path. Both directions are asserted
        # because an unconditioned claim about this round trip would be wrong.
        floorless = DEFAULT_PROFILES.with_profile(Profile("org.roax.corpus.synthetic", ()))
        for authorize, accepted, reason in ((False, True, "ok"), (True, False, "type-unresolved")):
            with self.subTest(verifier_authorize_empty_containers=authorize):
                result = verify_envelope(
                    full_copy(built),
                    VerifierConfig(
                        profiles=floorless,
                        resolvers={"org.roax.corpus.synthetic": bare},
                        authorize_empty_containers=authorize,
                    ),
                )
                self.assertEqual(result.accepted, accepted, result.detail)
                self.assertEqual(result.reason, reason)

    def test_full_copy_record_must_be_a_json_object(self):
        for record in (loads("[]"), loads('"scalar"'), loads("5"), None):
            with self.subTest(stage="issue", record=record):
                with self.assertRaises(RoaxError) as ctx:
                    issue(record, IDENTITY, resolver())
                self.assertEqual(ctx.exception.code, ErrorCode.ENVELOPE_SHAPE)

            with self.subTest(stage="verify", record=record):
                hostile = full_copy(self.built)
                hostile["record"] = record
                self.assertEqual(
                    verify_envelope(hostile, self.config).reason,
                    ErrorCode.ENVELOPE_SHAPE,
                )

    def test_envelope_leaf_count_carrier_floors(self):
        hostile = disclosed_copy(
            list(self.registry.get(IDENTITY.record_type).floor()),
            self.built,
            profile=self.registry.get(IDENTITY.record_type),
        )
        hostile["leafCount"] = 4
        self.assertEqual(
            verify_envelope(hostile, self.config).reason,
            ErrorCode.ENVELOPE_SHAPE,
        )

        hostile = full_copy(self.built)
        hostile["leafCount"] = 5
        hostile["issuer"] = {
            **hostile["issuer"],
            "keyId": "did:web:example.invalid#key-1",
        }
        self.assertEqual(
            verify_envelope(hostile, self.config).reason,
            ErrorCode.ENVELOPE_SHAPE,
        )

        minimal = issue(loads('{"marker": "m"}'), IDENTITY, resolver())
        self.assertEqual(minimal.leaf_count, 5)
        self.assertTrue(verify_envelope(full_copy(minimal), self.config).accepted)

        keyed_identity = replace(
            IDENTITY,
            issuer_key_id="did:web:example.invalid#key-1",
        )
        keyed = issue(loads('{"marker": "m"}'), keyed_identity, resolver())
        self.assertEqual(keyed.leaf_count, 6)
        self.assertTrue(verify_envelope(full_copy(keyed), self.config).accepted)

    def test_emitters_accept_no_replacement_issuance_context(self):
        alternate_identity = RecordIdentity(
            record_type=IDENTITY.record_type,
            schema_version="2.0",
            record_id="urn:uuid:22222222-2222-4222-8222-222222222222",
            issuer_id="did:web:other.invalid",
        )
        profile = self.registry.get(IDENTITY.record_type)
        reveal = list(profile.floor())

        full_replacements = {
            "record": {"marker": "replacement"},
            "identity": alternate_identity,
            "hash_alg": "Poseidon-BN254",
            "reserved_set": RESERVED_V2,
        }
        for name, replacement in full_replacements.items():
            with self.subTest(emitter="full", replacement=name):
                with self.assertRaises(TypeError):
                    full_copy(self.built, **{name: replacement})

        disclosed_replacements = {
            "identity": alternate_identity,
            "hash_alg": "Poseidon-BN254",
            "reserved_set": RESERVED_V2,
        }
        for name, replacement in disclosed_replacements.items():
            with self.subTest(emitter="disclosed", replacement=name):
                with self.assertRaises(TypeError):
                    disclosed_copy(reveal, self.built, **{name: replacement})

        with self.assertRaises(TypeError):
            full_copy({"marker": "replacement"}, alternate_identity, self.built)
        with self.assertRaises(TypeError):
            disclosed_copy(reveal, alternate_identity, self.built)

    def test_commitment_owns_an_isolated_record_snapshot(self):
        record = loads('{"marker": "before", "count": 5, "list": ["original"]}')
        built = issue(record, IDENTITY, resolver())

        record["marker"] = "after"
        record["count"] = JsonNumber("6")
        record["list"][0] = "after"
        first = full_copy(built)
        self.assertEqual(first["record"]["marker"], "before")
        self.assertEqual(str(first["record"]["count"]), "5")
        self.assertIsInstance(first["record"]["count"], JsonNumber)
        self.assertEqual(first["record"]["list"], ["original"])
        self.assertTrue(verify_envelope(first, self.config).accepted)

        first["record"]["marker"] = "envelope mutation"
        first["record"]["list"][0] = "envelope mutation"
        second = full_copy(built)
        self.assertEqual(second["record"]["marker"], "before")
        self.assertEqual(second["record"]["list"], ["original"])
        self.assertTrue(verify_envelope(second, self.config).accepted)

    def test_disclosed_copy_profile_must_match_the_sealed_record_type(self):
        mismatched = Profile(
            "sg.gov.moh.pdt-healthcert",
            ((Key("marker"),),),
        )
        reveal = list(self.registry.get(IDENTITY.record_type).floor())
        with self.assertRaises(RoaxError) as ctx:
            disclosed_copy(reveal, self.built, profile=mismatched)
        self.assertEqual(ctx.exception.code, ErrorCode.PROFILE_UNKNOWN)
        self.assertIn("does not match", ctx.exception.detail)

    def test_builtin_type_map_metadata_is_bound_to_the_record_identity(self):
        mismatches = {
            "recordType": {
                **SYNTHETIC_MAP,
                "recordType": "org.example.other",
            },
            "schemaVersion": {
                **SYNTHETIC_MAP,
                "schemaVersion": "2.0",
            },
        }
        for field_name, document in mismatches.items():
            with self.subTest(stage="issue", field=field_name):
                mismatched = DisplayPatternTypeMap(document)
                with self.assertRaises(RoaxError) as ctx:
                    issue(self.record, IDENTITY, mismatched)
                self.assertEqual(ctx.exception.code, ErrorCode.TYPE_MAP_REJECTED)
                self.assertIn(field_name, ctx.exception.detail)

            with self.subTest(stage="verify full copy", field=field_name):
                config = VerifierConfig(
                    profiles=self.registry,
                    resolvers={
                        IDENTITY.record_type: DisplayPatternTypeMap(document),
                    },
                )
                result = verify_envelope(full_copy(self.built), config)
                self.assertEqual(result.reason, ErrorCode.TYPE_MAP_REJECTED)
                self.assertIn(field_name, result.detail)

    def test_custom_resolver_remains_a_trusted_metadata_free_seam(self):
        delegate = resolver()

        class CustomResolver:
            def resolve(self, segments, kind):
                return delegate.resolve(segments, kind)

        custom = CustomResolver()
        built = issue(self.record, IDENTITY, custom)
        config = VerifierConfig(
            profiles=self.registry,
            resolvers={IDENTITY.record_type: custom},
        )
        self.assertTrue(verify_envelope(full_copy(built), config).accepted)

    def test_v2_round_trip_is_issuable_and_binds_the_identifier_it_commits(self):
        # THIS TEST REPLACES ONE THAT ASSERTED THE OPPOSITE, and the reversal is the point.
        #
        # It used to require issuance, emission and verification to REFUSE `RESERVED_V2`
        # outright, on the ground that they "need to load the exact published DFA selected by
        # this content ID". That is false for the producing side: an issuer knows which
        # artifact it used and supplies its identifier, and nothing has to be fetched or
        # reproduced. The refusal made this package unable to issue any record the current
        # specification admits, because section 11.2 marks `roax.typeMap.id` emitted ALWAYS -
        # and conformance corpus class 20 is what surfaced that, by asking an implementation
        # to PRODUCE an envelope rather than only to verify one.
        #
        # What the package still does not do is unchanged and is asserted below: it never
        # fetches the artifact, never reproduces its content ID, and never compares the
        # artifact's own metadata. So a syntactically plausible identifier is committed and
        # bound - never resolved - and this test pins the binding rather than a refusal.
        identity = RecordIdentity(
            IDENTITY.record_type,
            IDENTITY.schema_version,
            IDENTITY.record_id,
            IDENTITY.issuer_id,
            type_map_id="sha256:" + "0" * 64,
            type_map_version=SYNTHETIC_MAP["typeMapVersion"],
        )
        profile = self.registry.get("org.roax.corpus.synthetic")
        built = issue(self.record, identity, resolver(), reserved_set=RESERVED_V2)
        config = VerifierConfig(
            profiles=self.registry,
            resolvers={"org.roax.corpus.synthetic": resolver()},
        )

        # The producing side round-trips through this package's OWN verifier, on both copy
        # kinds. This is the assertion class 20 exists for.
        full = full_copy(built)
        self.assertEqual(full["typeMap"]["id"], identity.type_map_id)
        self.assertTrue(verify_envelope(full, config).accepted)

        revealed = list(profile.floor(reserved_set=RESERVED_V2))
        disclosed = disclosed_copy(revealed, built, profile=profile)
        self.assertTrue(verify_envelope(disclosed, config).accepted)

        # And the binding itself, in both directions. Each of these is a copy whose outer
        # member and committed leaf disagree, and absence on either side is a disagreement:
        # a check whose execution the presenter controls is not a check.
        disagreeing = disclosed_copy(revealed, built, profile=profile)
        disagreeing["typeMap"] = {"id": "sha256:" + "1" * 64, "version": "1.0.0"}
        self.assertEqual(
            verify_envelope(disagreeing, config).reason,
            ErrorCode.OUTER_IDENTITY_MISMATCH,
        )

        stripped = disclosed_copy(revealed, built, profile=profile)
        del stripped["typeMap"]
        self.assertEqual(
            verify_envelope(stripped, config).reason,
            ErrorCode.OUTER_IDENTITY_MISMATCH,
        )

        withheld = disclosed_copy(
            [
                path
                for path in revealed
                if not (len(path) == 1 and getattr(path[0], "value", None) == "roax.typeMap.id")
            ],
            built,
        )
        self.assertEqual(
            verify_envelope(withheld, config).reason,
            ErrorCode.OUTER_IDENTITY_MISMATCH,
        )

    def test_full_copy_detects_a_tampered_value(self):
        envelope = full_copy(self.built)
        envelope["record"]["marker"] = "tampered"
        self.assertEqual(verify_envelope(envelope, self.config).reason, ErrorCode.ROOT_MISMATCH)

    def test_full_copy_rejects_a_missing_salt(self):
        envelope = full_copy(self.built)
        envelope["salts"][0]["segments"] = [{"key": "notALeafInThisTree"}]
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.SALT_MISSING_FOR_LEAF
        )

    def test_full_copy_rejects_a_duplicate_salt_path(self):
        envelope = full_copy(self.built)
        envelope["salts"][1]["segments"] = envelope["salts"][0]["segments"]
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.SALTS_DUPLICATE_PATH
        )

    def test_full_copy_rejects_a_salts_length_disagreement(self):
        envelope = full_copy(self.built)
        envelope["leafCount"] = envelope["leafCount"] + 1
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.SALTS_LENGTH_NOT_LEAF_COUNT
        )

    def test_disclosed_copy_round_trip(self):
        floor = self.registry.get("org.roax.corpus.synthetic")
        reveal = list(floor.floor()) + [(Key("marker"),)]
        envelope = disclosed_copy(reveal, self.built, profile=floor)
        self.assertNotIn("salts", envelope)
        self.assertTrue(verify_envelope(envelope, self.config).accepted)

    def test_disclosed_copy_carries_no_withheld_salt(self):
        floor = self.registry.get("org.roax.corpus.synthetic")
        reveal = list(floor.floor()) + [(Key("marker"),)]
        envelope = disclosed_copy(reveal, self.built, profile=floor)
        emitted = {entry["salt"] for entry in envelope["disclosure"]["leaves"]}
        revealed = {self.built.salts[self.built.index_of(path)].hex() for path in reveal}
        self.assertEqual(emitted, revealed)
        withheld = set(s.hex() for s in self.built.salts) - revealed
        self.assertTrue(withheld)
        self.assertFalse(emitted & withheld, "a withheld leaf's salt must be unrepresentable")

    def test_bytes_leaf_round_trips_through_both_envelope_shapes(self):
        # No corpus vector reaches tag 5: no version-1 profile binds BYTES, because the
        # healthcert blob fields bind STRING and FHIR base64Binary is unresolved
        # (specification section 6.3). So the encoder-without-a-decoder asymmetry this
        # closes is invisible to the corpus and is pinned here instead.
        blob_map = DisplayPatternTypeMap(
            {
                **SYNTHETIC_MAP,
                "entries": SYNTHETIC_MAP["entries"]
                + [{"pattern": "blob", "jsonKind": "string", "tag": 5}],
            }
        )
        record = loads('{"marker": "m", "blob": "aGVsbG8="}')
        built = issue(record, IDENTITY, blob_map)
        self.assertEqual(built.leaves[built.index_of((Key("blob"),))].value, b"hello")

        profile = Profile("org.roax.corpus.synthetic", ((Key("blob"),),))
        config = VerifierConfig(
            profiles=DEFAULT_PROFILES.with_profile(profile),
            resolvers={"org.roax.corpus.synthetic": blob_map},
        )
        full = full_copy(built)
        self.assertTrue(verify_envelope(full, config).accepted)

        partial = disclosed_copy(list(profile.floor()), built, profile=profile)
        blob_entry = next(e for e in partial["disclosure"]["leaves"] if e["displayPath"] == "blob")
        self.assertEqual(blob_entry["value"], b"hello".hex())
        result = verify_envelope(partial, config)
        self.assertTrue(result.accepted, f"{result.reason}: {result.detail}")

    def test_bytes_binding_rejects_a_json_number_record_value(self):
        # JsonNumber subclasses str, and "1111" is canonical base64. A bare str check
        # would therefore decode this JSON number and commit it as BYTES even though the
        # map observed kind is explicitly `number`.
        numeric_bytes_map = DisplayPatternTypeMap(
            {
                **SYNTHETIC_MAP,
                "entries": SYNTHETIC_MAP["entries"]
                + [{"pattern": "blob", "jsonKind": "number", "tag": 5}],
            }
        )
        with self.assertRaises(RoaxError) as ctx:
            flatten(loads('{"marker": "m", "blob": 1111}'), numeric_bytes_map)
        self.assertEqual(ctx.exception.code, ErrorCode.ENVELOPE_SHAPE)

    def test_disclosed_copy_rejects_salts_array(self):
        floor = self.registry.get("org.roax.corpus.synthetic")
        reveal = list(floor.floor()) + [(Key("marker"),)]
        envelope = disclosed_copy(reveal, self.built, profile=floor)
        envelope["salts"] = []
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.DISCLOSED_COPY_CARRIES_SALTS
        )

    def test_disclosed_copy_rejects_a_seed_member(self):
        floor = self.registry.get("org.roax.corpus.synthetic")
        reveal = list(floor.floor()) + [(Key("marker"),)]
        envelope = disclosed_copy(reveal, self.built, profile=floor)
        envelope["masterSalt"] = "00" * 32
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.MASTER_SALT_IN_ENVELOPE
        )

    def test_floor_is_enforced_and_binding_runs_first(self):
        floor = self.registry.get("org.roax.corpus.synthetic")
        # Withhold the profile's own non-redactable path, `marker`, keeping every reserved
        # one: the floor fires, because nothing earlier can.
        reserved_only = [p for p in floor.floor() if p[0].value.startswith("roax.")]
        envelope = disclosed_copy(reserved_only, self.built, profile=None)
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.MINIMUM_DISCLOSURE_FLOOR
        )
        # Withhold a reserved path: the identity binding fires FIRST, so the reason is
        # outer-identity-mismatch rather than minimum-disclosure-floor. That ordering is
        # what 16 of the corpus's 54 envelope vectors pin.
        partial = [p for p in floor.floor() if p[0].value != "roax.recordType"]
        envelope = disclosed_copy(partial + [(Key("marker"),)], self.built, profile=None)
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.OUTER_IDENTITY_MISMATCH
        )

    def test_outer_identity_relabel_is_rejected(self):
        floor = self.registry.get("org.roax.corpus.synthetic")
        reveal = list(floor.floor()) + [(Key("marker"),)]
        envelope = disclosed_copy(reveal, self.built, profile=floor)
        envelope["recordType"] = "sg.gov.moh.pdt-healthcert"
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.OUTER_IDENTITY_MISMATCH
        )

    def test_unknown_profile_and_algorithm_fail_closed(self):
        envelope = full_copy(self.built)
        envelope["recordType"] = "com.example.not-a-profile"
        self.assertEqual(verify_envelope(envelope, self.config).reason, ErrorCode.PROFILE_UNKNOWN)
        envelope = full_copy(self.built)
        envelope["hashAlg"] = "Poseidon-BN254"
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.HASH_ALG_NOT_ALLOWED
        )

    def test_registry_authority_overrides_the_envelope(self):
        envelope = full_copy(self.built)
        hostile = VerifierConfig(
            profiles=self.registry,
            resolvers={"org.roax.corpus.synthetic": resolver()},
            anchored_root=bytes(32),
        )
        self.assertEqual(verify_envelope(envelope, hostile).reason, ErrorCode.ROOT_MISMATCH)


class TestDisclosedCarrierIsTheCommittedValue(unittest.TestCase):
    """A disclosed copy carries what the leaf hash committed, not the record's literal.

    `python/tools/run_corpus.py` never calls :func:`disclosed_copy`, so the emitter has no
    corpus exposure at all and these tests are the only thing holding this.

    The two patterns below are the ones `schemas/envelope-1.0.json` pins on a disclosed
    leaf's ``value`` at tags 3 and 4; the DECIMAL one is written there with its own note
    that exponent notation has already been expanded.
    """

    INTEGER_CARRIER = re.compile(r"\A-?(0|[1-9][0-9]*)\Z")
    DECIMAL_CARRIER = re.compile(r"\A-?(0|[1-9][0-9]*)(\.[0-9]+)?\Z")

    def setUp(self):
        self.profile = Profile("org.roax.corpus.synthetic", ((Key("marker"),),))
        self.config = VerifierConfig(
            profiles=DEFAULT_PROFILES.with_profile(self.profile),
            resolvers={"org.roax.corpus.synthetic": resolver()},
        )

    def emit(self, body, path):
        record = loads(body)
        built = issue(record, IDENTITY, resolver())
        reveal = list(self.profile.floor()) + [(Key(key),) for key in record]
        envelope = disclosed_copy(reveal, built, profile=self.profile)
        result = verify_envelope(envelope, self.config)
        self.assertTrue(result.accepted, f"{result.reason}: {result.detail}")
        return next(
            leaf for leaf in envelope["disclosure"]["leaves"] if leaf["displayPath"] == path
        )["value"]

    def test_decimal_exponent_notation_is_expanded(self):
        for literal in ("1e2", "1.0e2"):
            with self.subTest(literal=literal):
                emitted = self.emit('{"marker": "m", "amount": %s}' % literal, "amount")
                self.assertEqual(emitted, "100")
                self.assertIsNotNone(self.DECIMAL_CARRIER.match(emitted))
                self.assertNotIsInstance(emitted, JsonNumber)

    def test_decimal_trailing_zeros_still_survive(self):
        # Canonicalizing the carrier must not become a licence to strip precision:
        # `0.010` is not `0.01` and FHIR R4 says SHALL.
        emitted = self.emit('{"marker": "m", "amount": 0.010}', "amount")
        self.assertEqual(emitted, "0.010")
        self.assertIsNotNone(self.DECIMAL_CARRIER.match(emitted))

    def test_negative_zero_integer_is_normalized(self):
        emitted = self.emit('{"marker": "m", "count": -0}', "count")
        self.assertEqual(emitted, "0")
        self.assertIsNotNone(self.INTEGER_CARRIER.match(emitted))
        self.assertNotIsInstance(emitted, JsonNumber)

    def test_string_travels_as_its_nfc_form(self):
        # U+0065 U+0301 commits as U+00E9 (specification section 6.1), so that is what the
        # carrier must say.
        emitted = self.emit('{"marker": "e\\u0301"}', "marker")
        self.assertEqual(emitted, "é")
        self.assertEqual(emitted, unicodedata.normalize("NFC", emitted))


class TestHostileEnvelopeMembers(unittest.TestCase):
    """Specification section 11.3 makes everything outside the root attacker-controlled.

    Three hostile-input properties are pinned here.
    The committed fixtures exercise the ordinary paths, while their schema-valid carriers
    do not take the rejection branches below.

    1. A member that is a JSON *number* where the envelope schema requires a JSON string
       is REJECTED rather than committed. `JsonNumber` subclasses `str` so the literal
       survives, so `encode_value(STRING, ...)` would encode the two identically and the
       envelope would verify against a genuine root.
    2. `verify_envelope` converts the malformed JSON-value shapes enumerated below into a
       `VerificationResult`. A verifier service handed one must reject it, not crash.
    3. Every object `schemas/envelope-1.0.json` closes is closed here too, at each depth.
       A nested object is read by named key, so an extra member one level down would be
       ignored, and one carrying a withheld leaf's salt would ride inside an envelope that
       verifies `ok` (specification section 7.3, rule 3).
    """

    def setUp(self):
        self.record = loads('{"marker": "m", "count": 5, "amount": 0.010, "flag": true}')
        self.built = issue(self.record, IDENTITY, resolver())
        self.registry = DEFAULT_PROFILES.with_profile(
            Profile("org.roax.corpus.synthetic", ((Key("marker"),),))
        )
        self.config = VerifierConfig(
            profiles=self.registry, resolvers={"org.roax.corpus.synthetic": resolver()}
        )

    def full(self):
        return full_copy(self.built)

    def disclosed(self):
        floor = self.registry.get("org.roax.corpus.synthetic")
        reveal = list(floor.floor()) + [(Key("marker"),)]
        return disclosed_copy(reveal, self.built, profile=floor)

    def test_a_json_number_identity_member_is_rejected(self):
        # Without the check this envelope verifies: the reserved `roax.schemaVersion` leaf
        # is recomputed from JsonNumber("1.0"), which encodes byte-identically to the
        # string "1.0" the genuine root committed.
        for envelope in (self.full(), self.disclosed()):
            hostile = dict(envelope)
            hostile["schemaVersion"] = JsonNumber("1.0")
            self.assertEqual(verify_envelope(hostile, self.config).reason, ErrorCode.ENVELOPE_SHAPE)

    def test_every_identity_member_is_checked(self):
        cases = {
            "recordId": lambda e: e.update(recordId=JsonNumber("5")),
            "issuer.id": lambda e: e.update(issuer={**e["issuer"], "id": JsonNumber("5")}),
            "issuer.keyId": lambda e: e.update(issuer={**e["issuer"], "keyId": JsonNumber("5")}),
            "typeMap.id": lambda e: e.update(typeMap={"id": JsonNumber("5")}),
        }
        for name, mutate in cases.items():
            with self.subTest(member=name):
                hostile = dict(self.full())
                mutate(hostile)
                self.assertEqual(
                    verify_envelope(hostile, self.config).reason, ErrorCode.ENVELOPE_SHAPE
                )
        # `recordType` is checked too, but the profile lookup that must fail closed ahead
        # of everything else reaches a numeric one first, so its reason stays
        # `profile-unknown`. Either way it is not accepted.
        hostile = dict(self.full())
        hostile["recordType"] = JsonNumber("5")
        self.assertEqual(verify_envelope(hostile, self.config).reason, ErrorCode.PROFILE_UNKNOWN)

    def test_identity_minima_and_issuer_uri_are_enforced_by_the_verifier(self):
        cases = {
            "empty schemaVersion": lambda envelope: envelope.update(schemaVersion=""),
            "empty recordId": lambda envelope: envelope.update(recordId=""),
            "empty issuer.id": lambda envelope: envelope.update(
                issuer={**envelope["issuer"], "id": ""}
            ),
            "relative issuer.id": lambda envelope: envelope.update(
                issuer={**envelope["issuer"], "id": "not a uri"}
            ),
        }
        for shape in (self.full, self.disclosed):
            for name, mutate in cases.items():
                with self.subTest(shape=shape.__name__, case=name):
                    hostile = shape()
                    mutate(hostile)
                    self.assertEqual(
                        verify_envelope(hostile, self.config).reason,
                        ErrorCode.ENVELOPE_SHAPE,
                    )

    def test_record_type_form_is_checked_independently_of_the_profile_registry(self):
        invalid_type = "invalid"
        hostile = self.full()
        hostile["recordType"] = invalid_type
        config = VerifierConfig(
            profiles=self.registry.with_profile(Profile(invalid_type)),
            resolvers={invalid_type: resolver()},
        )
        self.assertEqual(
            verify_envelope(hostile, config).reason,
            ErrorCode.ENVELOPE_SHAPE,
        )

    def test_optional_type_map_hint_has_the_envelope_1_carrier_shape(self):
        # When present, this descriptor's carrier is closed and fully shaped by
        # schemas/envelope-1.0.json, and every malformed case below is an ENVELOPE_SHAPE
        # rejection rather than a silent absence - reading a present-but-wrong-typed member
        # as missing is what would switch the binding below off from outside.
        #
        # THE FIRST ASSERTION USED TO BE THAT A DESCRIPTOR UNRELATED TO THIS ROOT WAS
        # ACCEPTED, "proving the hint did not start selecting a map". That was the defect
        # rather than the property: the member is not authority (specification section 11.3),
        # and a copy presenting an identifier the root does not commit is exactly what the
        # section 4.2 binding refuses. Nothing here selects a map; what changed is that the
        # unauthenticated hint is now BOUND to the leaf instead of ignored.
        valid = {
            "id": "sha256:" + "0" * 64,
            "version": "9.9.9",
        }
        envelope = self.full()
        envelope["typeMap"] = valid
        self.assertEqual(
            verify_envelope(envelope, self.config).reason,
            ErrorCode.SALT_MISSING_FOR_LEAF,
            "a full copy naming a type map commits the leaf, so a member bolted onto a copy "
            "issued without one asks for a salt the copy never carried",
        )

        cases = {
            "not an object": None,
            "missing id": {"version": "1.0.0"},
            "missing version": {"id": "sha256:" + "0" * 64},
            "numeric id": {"id": JsonNumber("5"), "version": "1.0.0"},
            "numeric version": {
                "id": "sha256:" + "0" * 64,
                "version": JsonNumber("1.0"),
            },
            "malformed id": {"id": "x", "version": "1.0.0"},
            "malformed version": {
                "id": "sha256:" + "0" * 64,
                "version": "1.0",
            },
            "unknown member": {**valid, "latest": True},
        }
        for name, descriptor in cases.items():
            with self.subTest(case=name):
                hostile = self.full()
                hostile["typeMap"] = descriptor
                self.assertEqual(
                    verify_envelope(hostile, self.config).reason,
                    ErrorCode.ENVELOPE_SHAPE,
                )

    def test_display_path_is_a_string_hint_and_is_never_reconstructed(self):
        # The structured segments remain authoritative. A wrong but genuine display
        # string is accepted, while a JsonNumber or nested carrier is schema-invalid.
        envelope = self.disclosed()
        envelope["disclosure"]["leaves"][0]["displayPath"] = "deliberately.not.the.path"
        self.assertTrue(verify_envelope(envelope, self.config).accepted)

        for hostile_value in (JsonNumber("5"), {}, []):
            with self.subTest(value=hostile_value):
                hostile = self.disclosed()
                hostile["disclosure"]["leaves"][0]["displayPath"] = hostile_value
                self.assertEqual(
                    verify_envelope(hostile, self.config).reason,
                    ErrorCode.ENVELOPE_SHAPE,
                )

    def test_anchor_has_the_exact_closed_schema_carrier(self):
        registry = "0x" + "aB" * 20
        tx_hash = "0x" + "Cd" * 32
        for chain_id in (JsonNumber("1.0"), JsonNumber("1e0")):
            with self.subTest(valid_chain_id=chain_id):
                envelope = self.full()
                envelope["anchor"] = {
                    "chainId": chain_id,
                    "registry": registry,
                    "txHash": tx_hash,
                    "anchoredAt": "2026-07-28T23:59:60Z",
                }
                self.assertTrue(verify_envelope(envelope, self.config).accepted)

        cases = {
            "null anchor": None,
            "missing chainId": {"registry": registry},
            "missing registry": {"chainId": JsonNumber("1")},
            "boolean chainId": {"chainId": True, "registry": registry},
            "fractional chainId": {"chainId": JsonNumber("1.1"), "registry": registry},
            "negative chainId": {"chainId": JsonNumber("-1"), "registry": registry},
            "numeric registry": {
                "chainId": JsonNumber("1"),
                "registry": JsonNumber("1" * 40),
            },
            "nested registry": {"chainId": JsonNumber("1"), "registry": {}},
            "short registry": {"chainId": JsonNumber("1"), "registry": "0x0"},
            "numeric txHash": {
                "chainId": JsonNumber("1"),
                "registry": registry,
                "txHash": JsonNumber("1" * 64),
            },
            "nested txHash": {
                "chainId": JsonNumber("1"),
                "registry": registry,
                "txHash": [],
            },
            "bad anchoredAt": {
                "chainId": JsonNumber("1"),
                "registry": registry,
                "anchoredAt": "2026-02-29T00:00:00Z",
            },
            "numeric anchoredAt": {
                "chainId": JsonNumber("1"),
                "registry": registry,
                "anchoredAt": JsonNumber("2026"),
            },
            "nested anchoredAt": {
                "chainId": JsonNumber("1"),
                "registry": registry,
                "anchoredAt": {},
            },
        }
        for name, anchor in cases.items():
            with self.subTest(case=name):
                hostile = self.full()
                hostile["anchor"] = anchor
                self.assertEqual(
                    verify_envelope(hostile, self.config).reason,
                    ErrorCode.ENVELOPE_SHAPE,
                )

    def test_a_json_number_disclosed_leaf_value_is_rejected(self):
        # The 54 committed envelope fixtures contain 317 ordinary tag-2 string values.
        # None exercises the hostile-number branch, or a disclosed value at tag 3, 4 or 5,
        # so these four direct cases hold the discriminator at each string carrier.
        #
        # DECIMAL is the case that shows the harm. `JsonNumber` subclasses `str`, so a
        # carrier of 0.010 canonicalizes to the same "0.010" the genuine leaf committed
        # and the envelope verifies, while any consumer re-reading those same bytes with a
        # stdlib parser gets 0.01 - the trailing-zero destruction specification section
        # 6.4 and `docs/decisions.md` part 0 exist to prevent, and which
        # `schemas/envelope-1.0.json` forbids by pinning the carrier to "type": "string".
        carrier_map = DisplayPatternTypeMap(
            {
                **SYNTHETIC_MAP,
                "entries": SYNTHETIC_MAP["entries"]
                + [{"pattern": "blob", "jsonKind": "string", "tag": 5}],
            }
        )
        record = loads('{"marker": "5", "count": 5, "amount": 0.010, "blob": "EQ=="}')
        built = issue(record, IDENTITY, carrier_map)
        profile = Profile("org.roax.corpus.synthetic", ((Key("marker"),),))
        config = VerifierConfig(
            profiles=DEFAULT_PROFILES.with_profile(profile),
            resolvers={"org.roax.corpus.synthetic": carrier_map},
        )
        reveal = list(profile.floor()) + [
            (Key("count"),),
            (Key("amount"),),
            (Key("blob"),),
        ]
        envelope = disclosed_copy(reveal, built, profile=profile)

        def with_carrier(path, carrier):
            copied = {**envelope, "disclosure": {**envelope["disclosure"]}}
            copied["disclosure"]["leaves"] = [
                {**leaf, "value": carrier} if leaf["displayPath"] == path else leaf
                for leaf in envelope["disclosure"]["leaves"]
            ]
            return copied

        # The encoder must emit the schema's string carrier rather than the record's
        # JsonNumber, or the round trip stops closing: this is what `disclosed_copy`
        # produced unmodified.
        emitted = next(
            leaf for leaf in envelope["disclosure"]["leaves"] if leaf["displayPath"] == "amount"
        )["value"]
        self.assertEqual(emitted, "0.010")
        self.assertNotIsInstance(emitted, JsonNumber)
        self.assertTrue(verify_envelope(envelope, config).accepted)

        cases = {
            "marker": (2, JsonNumber("5")),
            "count": (3, JsonNumber("5")),
            "amount": (4, JsonNumber("0.010")),
            "blob": (5, JsonNumber("11")),
        }
        for path, (tag, hostile_value) in cases.items():
            with self.subTest(path=path, tag=tag):
                honest = next(
                    leaf for leaf in envelope["disclosure"]["leaves"] if leaf["displayPath"] == path
                )
                self.assertEqual(honest["tag"], tag)
                self.assertIsInstance(honest["value"], str)
                self.assertNotIsInstance(honest["value"], JsonNumber)
                self.assertEqual(
                    verify_envelope(with_carrier(path, hostile_value), config).reason,
                    ErrorCode.ENVELOPE_SHAPE,
                )

        # Tags that deliberately do not use a string carrier must keep working.
        boolean = loads('{"marker": "m", "flag": true}')
        boolean_built = issue(boolean, IDENTITY, resolver())
        self.assertTrue(
            verify_envelope(
                disclosed_copy(
                    list(profile.floor()) + [(Key("marker"),), (Key("flag"),)],
                    boolean_built,
                    profile=profile,
                ),
                config,
            ).accepted
        )

    def test_a_tag_8_leaf_keeps_its_own_reason(self):
        # Specification section 6.5 rejects a tag-8 leaf before any carrier is read, so
        # the carrier check must not preempt `blob-ref-not-declared`.
        envelope = self.disclosed()
        envelope["disclosure"]["leaves"][0] = {
            **envelope["disclosure"]["leaves"][0],
            "tag": 8,
            "value": {"blobByteLength": JsonNumber("14314"), "blobDigest": "00" * 32},
        }
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.BLOB_REF_NOT_DECLARED
        )

    def test_a_nested_object_carrying_a_withheld_salt_is_rejected(self):
        # The leak the top-level scan alone does not close. Every nested object is read by
        # named key, so a `salts` array parked inside `disclosure` is ignored while the
        # envelope verifies `ok` - and it carries the salt of a leaf the holder chose to
        # withhold, which is the dictionary search specification section 7.3 rule 3 and
        # section 10.1 forbid.
        withheld = (Key("amount"),)
        leaked = self.built.salts[self.built.index_of(withheld)].hex()
        hostile = self.disclosed()
        hostile["disclosure"] = {
            **hostile["disclosure"],
            "salts": [{"segments": [{"key": "amount"}], "salt": leaked}],
        }
        self.assertEqual(verify_envelope(hostile, self.config).reason, ErrorCode.ENVELOPE_SHAPE)

        # A seed member one level down keeps the reason the top-level scan gives it, at
        # each closed object this module dereferences and at the one it never reads.
        cases = {
            "issuer": ("issuer", {"masterSalt": "00" * 32}),
            "disclosure": ("disclosure", {"saltSeed": "00" * 32}),
            "anchor": ("anchor", {"chainId": 1, "registry": "0x0", "kdfKey": "00" * 32}),
        }
        for where, (member, extra) in cases.items():
            with self.subTest(where=where):
                hostile = dict(self.disclosed())
                hostile[member] = {**hostile.get(member, {}), **extra}
                self.assertEqual(
                    verify_envelope(hostile, self.config).reason,
                    ErrorCode.MASTER_SALT_IN_ENVELOPE,
                )

        # `salt` is in the seed list and is legitimate on both leaf shapes, so the scan must
        # skip a name the object itself declares; an undeclared member is still refused.
        accepted = self.disclosed()
        self.assertTrue(verify_envelope(accepted, self.config).accepted)
        hostile = self.disclosed()
        hostile["disclosure"]["leaves"][0] = {
            **hostile["disclosure"]["leaves"][0],
            "leafHash": "00" * 32,
        }
        self.assertEqual(verify_envelope(hostile, self.config).reason, ErrorCode.ENVELOPE_SHAPE)

        hostile = self.full()
        hostile["salts"] = [{**hostile["salts"][0], "seed": "00" * 32}] + hostile["salts"][1:]
        self.assertEqual(
            verify_envelope(hostile, self.config).reason, ErrorCode.MASTER_SALT_IN_ENVELOPE
        )

    def test_a_json_number_hex_field_is_rejected(self):
        # `schemas/envelope-1.0.json` pins each of these to "type": "string", and an
        # all-digit even-length numeric literal satisfies the hex test on its own. Neither
        # is choosable by a producer - both are pinned by the honest commitment - so the
        # discriminator is the reason: an unfixed `_hexbytes` accepts the carrier and the
        # envelope fails later on the value instead of on its shape.
        hostile = dict(self.full())
        hostile["root"] = JsonNumber("1" * 64)
        self.assertEqual(verify_envelope(hostile, self.config).reason, ErrorCode.ENVELOPE_SHAPE)

        hostile = self.disclosed()
        hostile["disclosure"]["leaves"][0] = {
            **hostile["disclosure"]["leaves"][0],
            "salt": JsonNumber("1" * 32),
        }
        self.assertEqual(verify_envelope(hostile, self.config).reason, ErrorCode.ENVELOPE_SHAPE)

        hostile = self.disclosed()
        hostile["disclosure"]["leaves"][0] = {
            **hostile["disclosure"]["leaves"][0],
            "auditPath": [JsonNumber("1" * 64)],
        }
        self.assertEqual(verify_envelope(hostile, self.config).reason, ErrorCode.ENVELOPE_SHAPE)

    def test_a_json_number_path_key_is_rejected(self):
        # The same collapse one layer down: {"key": 5} would encode identically to
        # {"key": "5"} (specification section 5).
        hostile = dict(self.full())
        hostile["salts"] = [dict(s) for s in hostile["salts"]]
        hostile["salts"][0]["segments"] = [{"key": JsonNumber("5")}]
        self.assertEqual(verify_envelope(hostile, self.config).reason, ErrorCode.ENVELOPE_SHAPE)

    def test_malformed_members_reject_rather_than_raise(self):
        salt = "00" * 16
        base = (
            '{"canon":"ROAX-CANON/1","hashAlg":"SHA-256","recordType":"hl7.fhir.bundle",'
            '"schemaVersion":"1.0","recordId":"r","root":"' + "00" * 32 + '",'
            '"leafCount":%s,"issuer":{"id":"did:example:issuer"},%s}'
        )
        cases = {
            "segments is null": base
            % (5, '"record":{},"salts":[{"segments":null,"salt":"' + salt + '"}]'),
            "segments carries an object key": base
            % (5, '"record":{},"salts":[{"segments":[{"key":{}}],"salt":"' + salt + '"}]'),
            "auditPath is null": base
            % (
                5,
                '"disclosure":{"mode":"selective","leaves":[{"segments":[{"key":"a"}],'
                '"index":0,"tag":2,"value":"x","salt":"' + salt + '","auditPath":null}]}',
            ),
            "typeMap is a string": base
            % (
                5,
                '"typeMap":"oops","record":{},"salts":[{"segments":[{"key":"a"}],"salt":"'
                + salt
                + '"}]',
            ),
            # CPython 3.11+ ships with a configurable int(str) conversion limit whose
            # default is 4300 digits, so an unbounded count raises ValueError before any
            # rule of this specification applies. Same interpreter hazard
            # `roax_canon.numbers` already refuses for a decimal exponent.
            "leafCount has 5000 digits": base % ("9" * 5000, '"record":{},"salts":[]'),
            "index has 5000 digits": base
            % (
                5,
                '"disclosure":{"mode":"selective","leaves":[{"segments":[{"key":"a"}],'
                '"index":'
                + "9" * 5000
                + ',"tag":2,"value":"x","salt":"'
                + salt
                + '","auditPath":[]}]}',
            ),
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                result = verify_envelope(loads(text))
                self.assertEqual(result.reason, ErrorCode.ENVELOPE_SHAPE)
                # Each case must be caught by its own explicit check, not by the backstop
                # in `verify_envelope`; otherwise those checks would be dead code.
                self.assertNotIn("malformed envelope member", result.detail)


class TestSalts(unittest.TestCase):
    def test_independent_per_leaf_draws(self):
        drawn = [draw_salt() for _ in range(64)]
        self.assertTrue(all(len(s) == 16 for s in drawn))
        self.assertEqual(len(set(drawn)), 64)

    def test_reissuance_produces_a_different_root(self):
        record = loads('{"marker": "m"}')
        a = issue(record, IDENTITY, resolver())
        b = issue(record, IDENTITY, resolver())
        self.assertNotEqual(a.root, b.root)
        self.assertEqual(
            a.encoded_paths, b.encoded_paths, "tree shape is a function of paths alone"
        )

    def test_short_salt_rejected(self):
        with self.assertRaises(RoaxError) as ctx:
            leaf_hash((Key("a"),), 2, "x", b"\x00" * 8)
        self.assertEqual(ctx.exception.code, ErrorCode.SALT_LENGTH)


class TestTypeMapMatcher(unittest.TestCase):
    def test_tag_uses_json_schema_integer_semantics(self):
        def load_tag(literal):
            document = (
                '{"typeMapVersion":"1.0.0",'
                '"recordType":"org.roax.corpus.synthetic",'
                '"schemaVersion":"1.0",'
                '"entries":[{"pattern":"marker","jsonKind":"string","tag":' + literal + "}]}"
            )
            with tempfile.NamedTemporaryFile("w+", suffix=".json") as handle:
                handle.write(document)
                handle.flush()
                return DisplayPatternTypeMap.from_file(handle.name)

        # JSON Schema's integer type is mathematical, not lexical.
        for literal in ("1.0", "1e0"):
            with self.subTest(valid=literal):
                self.assertEqual(load_tag(literal).resolve((Key("marker"),), "string"), 1)

        for literal in ("1.1", "true", '"1"', "-1", "9", "null", "{}"):
            with self.subTest(invalid=literal):
                with self.assertRaises(RoaxError) as ctx:
                    load_tag(literal)
                self.assertEqual(ctx.exception.code, ErrorCode.TYPE_MAP_REJECTED)

    def test_index_wildcard(self):
        self.assertEqual(resolver().resolve((Key("list"), Index(7)), "string"), 2)

    def test_any_run_is_one_or_more(self):
        m = resolver()
        self.assertEqual(m.resolve((Key("deep"), Key("x")), "string"), 2)
        self.assertEqual(m.resolve((Key("deep"), Key("x"), Index(0), Key("y")), "string"), 2)
        with self.assertRaises(RoaxError):
            m.resolve((Key("deep"),), "string")

    def test_a_map_binding_tag_8_is_rejected_outright(self):
        with self.assertRaises(RoaxError) as ctx:
            DisplayPatternTypeMap(
                {**SYNTHETIC_MAP, "entries": [{"pattern": "blob", "jsonKind": "string", "tag": 8}]}
            )
        self.assertEqual(ctx.exception.code, ErrorCode.TYPE_MAP_REJECTED)

    def test_a_malformed_entry_carries_the_stable_code(self):
        # The fail-closed artifact-loading surface: a missing or non-string `pattern` and
        # a non-object entry must reject with `type-map-rejected` like every neighbouring
        # check, rather than raising KeyError or AttributeError out of `from_file`.
        for entries in (
            [{"jsonKind": "string", "tag": 2}],
            ["not an object"],
            [{"pattern": None, "tag": 2}],
            [{"pattern": JsonNumber("5"), "tag": 2}],
        ):
            with self.subTest(entries=entries):
                with self.assertRaises(RoaxError) as ctx:
                    DisplayPatternTypeMap({**SYNTHETIC_MAP, "entries": entries})
                self.assertEqual(ctx.exception.code, ErrorCode.TYPE_MAP_REJECTED)

    def test_top_level_carrier_rejects_with_the_stable_code(self):
        cases = [
            [],
            {key: value for key, value in SYNTHETIC_MAP.items() if key != "typeMapVersion"},
            {key: value for key, value in SYNTHETIC_MAP.items() if key != "recordType"},
            {key: value for key, value in SYNTHETIC_MAP.items() if key != "schemaVersion"},
            {**SYNTHETIC_MAP, "unexpected": True},
            {
                **SYNTHETIC_MAP,
                "entries": [
                    {
                        "pattern": "marker",
                        "jsonKind": "string",
                        "tag": 2,
                        "unexpected": True,
                    }
                ],
            },
        ]
        for document in cases:
            with self.subTest(document=document):
                with self.assertRaises(RoaxError) as ctx:
                    DisplayPatternTypeMap(document)
                self.assertEqual(ctx.exception.code, ErrorCode.TYPE_MAP_REJECTED)

        # Exercise the actual file-loading boundary too: an array used to escape as an
        # AttributeError when the constructor called `.get`.
        with tempfile.NamedTemporaryFile("w+", suffix=".json") as handle:
            handle.write("[]")
            handle.flush()
            with self.assertRaises(RoaxError) as ctx:
                DisplayPatternTypeMap.from_file(handle.name)
        self.assertEqual(ctx.exception.code, ErrorCode.TYPE_MAP_REJECTED)

    def test_ambiguous_patterns_are_rejected_rather_than_mis_parsed(self):
        for pattern in ("a[b]", "a[", "]a", "", "a.*"):
            with self.subTest(pattern=pattern):
                with self.assertRaises(RoaxError):
                    DisplayPatternTypeMap(
                        {**SYNTHETIC_MAP, "entries": [{"pattern": pattern, "tag": 2}]}
                    )

    def test_lookup_matches_a_key_under_nfc_on_both_sides(self):
        # Ruled decision D14a on 2026-07-30 (`docs/decisions.md` part 2a): the type-map
        # LOOKUP matches over NFC-normalized keys rather than over the bytes as received.
        # U+212A KELVIN SIGN renders as "K" and its NFC form IS ASCII "K", so the leaf it
        # names commits as ASCII and the lookup now agrees with that.
        m = DisplayPatternTypeMap(
            {**SYNTHETIC_MAP, "entries": [{"pattern": "Kelvin", "jsonKind": "string", "tag": 2}]}
        )
        self.assertEqual(m.resolve((Key("Kelvin"),), "string"), 2)
        self.assertEqual(m.resolve((Key("\u212aelvin"),), "string"), 2)

        # BOTH sides normalize, so a pattern authored decomposed denotes the same path
        # language as one authored composed and either reaches either spelling.
        for pattern in ("\u00e9", "e\u0301"):
            authored = DisplayPatternTypeMap(
                {**SYNTHETIC_MAP, "entries": [{"pattern": pattern, "jsonKind": "string", "tag": 2}]}
            )
            self.assertEqual(authored.resolve((Key("\u00e9"),), "string"), 2)
            self.assertEqual(authored.resolve((Key("e\u0301"),), "string"), 2)

        # Normalizing the lookup key does NOT widen the map to a different character:
        # fail-closed still applies to a key whose NFC form is not the pattern's.
        with self.assertRaises(RoaxError) as ctx:
            m.resolve((Key("kelvin"),), "string")
        self.assertEqual(ctx.exception.code, ErrorCode.TYPE_UNRESOLVED)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(not unittest.main(exit=False).result.wasSuccessful())
