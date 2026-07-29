"""Reader, flattener, tree, record and envelope tests.

    python3 -m unittest discover -s python/tests -t python
"""

from __future__ import annotations

import re
import sys
import unicodedata
import unittest

from roax_canon import (
    DEFAULT_PROFILES,
    RESERVED_V1,
    RESERVED_V2,
    DisplayPatternTypeMap,
    Index,
    JsonNumber,
    Key,
    MappingSalts,
    Profile,
    RecordIdentity,
    RoaxError,
    audit_path,
    build_tree,
    disclosed_copy,
    draw_salt,
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
from roax_canon.errors import ErrorCode
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


class TestReservedLeaves(unittest.TestCase):
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
            {**SYNTHETIC_MAP, "entries": [{"pattern": "\u00e9", "jsonKind": "string", "tag": 2},
                                          {"pattern": "e\u0301", "jsonKind": "string", "tag": 2}]}
        )
        record = loads('{"\\u00e9": "a", "e\\u0301": "b"}')
        self.assertEqual(len(record), 2, "the two keys are distinct JSON member names")
        with self.assertRaises(RoaxError) as ctx:
            build_tree(record, IDENTITY, accents, MappingSalts({}))
        self.assertEqual(ctx.exception.code, ErrorCode.DUPLICATE_PATH)


class TestTree(unittest.TestCase):
    def test_split_rule(self):
        self.assertEqual([largest_power_of_two_below(n) for n in range(2, 10)], [1, 2, 2, 4, 4, 4, 4, 8])

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
        envelope = full_copy(self.record, IDENTITY, self.built)
        result = verify_envelope(envelope, self.config)
        self.assertTrue(result.accepted, result.detail)

    def test_full_copy_detects_a_tampered_value(self):
        envelope = full_copy(self.record, IDENTITY, self.built)
        envelope["record"]["marker"] = "tampered"
        self.assertEqual(verify_envelope(envelope, self.config).reason, ErrorCode.ROOT_MISMATCH)

    def test_full_copy_rejects_a_missing_salt(self):
        envelope = full_copy(self.record, IDENTITY, self.built)
        envelope["salts"][0]["segments"] = [{"key": "notALeafInThisTree"}]
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.SALT_MISSING_FOR_LEAF
        )

    def test_full_copy_rejects_a_duplicate_salt_path(self):
        envelope = full_copy(self.record, IDENTITY, self.built)
        envelope["salts"][1]["segments"] = envelope["salts"][0]["segments"]
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.SALTS_DUPLICATE_PATH
        )

    def test_full_copy_rejects_a_salts_length_disagreement(self):
        envelope = full_copy(self.record, IDENTITY, self.built)
        envelope["leafCount"] = envelope["leafCount"] + 1
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.SALTS_LENGTH_NOT_LEAF_COUNT
        )

    def test_disclosed_copy_round_trip(self):
        floor = self.registry.get("org.roax.corpus.synthetic")
        reveal = list(floor.floor()) + [(Key("marker"),)]
        envelope = disclosed_copy(reveal, IDENTITY, self.built, profile=floor)
        self.assertNotIn("salts", envelope)
        self.assertTrue(verify_envelope(envelope, self.config).accepted)

    def test_disclosed_copy_carries_no_withheld_salt(self):
        floor = self.registry.get("org.roax.corpus.synthetic")
        reveal = list(floor.floor()) + [(Key("marker"),)]
        envelope = disclosed_copy(reveal, IDENTITY, self.built, profile=floor)
        emitted = {entry["salt"] for entry in envelope["disclosure"]["leaves"]}
        revealed = {
            self.built.salts[self.built.index_of(path)].hex() for path in reveal
        }
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
            {**SYNTHETIC_MAP, "entries": SYNTHETIC_MAP["entries"]
             + [{"pattern": "blob", "jsonKind": "string", "tag": 5}]}
        )
        record = loads('{"marker": "m", "blob": "aGVsbG8="}')
        built = issue(record, IDENTITY, blob_map)
        self.assertEqual(built.leaves[built.index_of((Key("blob"),))].value, b"hello")

        profile = Profile("org.roax.corpus.synthetic", ((Key("blob"),),))
        config = VerifierConfig(
            profiles=DEFAULT_PROFILES.with_profile(profile),
            resolvers={"org.roax.corpus.synthetic": blob_map},
        )
        full = full_copy(record, IDENTITY, built)
        self.assertTrue(verify_envelope(full, config).accepted)

        partial = disclosed_copy(list(profile.floor()), IDENTITY, built, profile=profile)
        blob_entry = next(
            e for e in partial["disclosure"]["leaves"] if e["displayPath"] == "blob"
        )
        self.assertEqual(blob_entry["value"], b"hello".hex())
        result = verify_envelope(partial, config)
        self.assertTrue(result.accepted, f"{result.reason}: {result.detail}")

    def test_disclosed_copy_rejects_salts_array(self):
        floor = self.registry.get("org.roax.corpus.synthetic")
        reveal = list(floor.floor()) + [(Key("marker"),)]
        envelope = disclosed_copy(reveal, IDENTITY, self.built, profile=floor)
        envelope["salts"] = []
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.DISCLOSED_COPY_CARRIES_SALTS
        )

    def test_disclosed_copy_rejects_a_seed_member(self):
        floor = self.registry.get("org.roax.corpus.synthetic")
        reveal = list(floor.floor()) + [(Key("marker"),)]
        envelope = disclosed_copy(reveal, IDENTITY, self.built, profile=floor)
        envelope["masterSalt"] = "00" * 32
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.MASTER_SALT_IN_ENVELOPE
        )

    def test_floor_is_enforced_and_binding_runs_first(self):
        floor = self.registry.get("org.roax.corpus.synthetic")
        # Withhold the profile's own non-redactable path, `marker`, keeping every reserved
        # one: the floor fires, because nothing earlier can.
        reserved_only = [p for p in floor.floor() if p[0].value.startswith("roax.")]
        envelope = disclosed_copy(reserved_only, IDENTITY, self.built, profile=None)
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.MINIMUM_DISCLOSURE_FLOOR
        )
        # Withhold a reserved path: the identity binding fires FIRST, so the reason is
        # outer-identity-mismatch rather than minimum-disclosure-floor. That ordering is
        # what 16 of the corpus's 54 envelope vectors pin.
        partial = [p for p in floor.floor() if p[0].value != "roax.recordType"]
        envelope = disclosed_copy(partial + [(Key("marker"),)], IDENTITY, self.built, profile=None)
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.OUTER_IDENTITY_MISMATCH
        )

    def test_outer_identity_relabel_is_rejected(self):
        floor = self.registry.get("org.roax.corpus.synthetic")
        reveal = list(floor.floor()) + [(Key("marker"),)]
        envelope = disclosed_copy(reveal, IDENTITY, self.built, profile=floor)
        envelope["recordType"] = "sg.gov.moh.pdt-healthcert"
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.OUTER_IDENTITY_MISMATCH
        )

    def test_unknown_profile_and_algorithm_fail_closed(self):
        envelope = full_copy(self.record, IDENTITY, self.built)
        envelope["recordType"] = "com.example.not-a-profile"
        self.assertEqual(verify_envelope(envelope, self.config).reason, ErrorCode.PROFILE_UNKNOWN)
        envelope = full_copy(self.record, IDENTITY, self.built)
        envelope["hashAlg"] = "Poseidon-BN254"
        self.assertEqual(
            verify_envelope(envelope, self.config).reason, ErrorCode.HASH_ALG_NOT_ALLOWED
        )

    def test_registry_authority_overrides_the_envelope(self):
        envelope = full_copy(self.record, IDENTITY, self.built)
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
        envelope = disclosed_copy(reveal, IDENTITY, built, profile=self.profile)
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

    Two properties are pinned here and neither is reachable from the committed corpus,
    because all 54 envelope fixtures are schema-valid.

    1. A member that is a JSON *number* where the envelope schema requires a JSON string
       is REJECTED rather than committed. `JsonNumber` subclasses `str` so the literal
       survives, so `encode_value(STRING, ...)` would encode the two identically and the
       envelope would verify against a genuine root.
    2. `verify_envelope` returns a `VerificationResult` for every input. A verifier
       service handed a hostile envelope must reject it, not crash.
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
        return full_copy(self.record, IDENTITY, self.built)

    def disclosed(self):
        floor = self.registry.get("org.roax.corpus.synthetic")
        reveal = list(floor.floor()) + [(Key("marker"),)]
        return disclosed_copy(reveal, IDENTITY, self.built, profile=floor)

    def test_a_json_number_identity_member_is_rejected(self):
        # Without the check this envelope verifies: the reserved `roax.schemaVersion` leaf
        # is recomputed from JsonNumber("1.0"), which encodes byte-identically to the
        # string "1.0" the genuine root committed.
        for envelope in (self.full(), self.disclosed()):
            hostile = dict(envelope)
            hostile["schemaVersion"] = JsonNumber("1.0")
            self.assertEqual(
                verify_envelope(hostile, self.config).reason, ErrorCode.ENVELOPE_SHAPE
            )

    def test_every_identity_member_is_checked(self):
        cases = {
            "recordId": lambda e: e.update(recordId=JsonNumber("5")),
            "issuer.id": lambda e: e.update(issuer={**e["issuer"], "id": JsonNumber("5")}),
            "issuer.keyId": lambda e: e.update(
                issuer={**e["issuer"], "keyId": JsonNumber("5")}
            ),
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

    def test_a_json_number_disclosed_leaf_value_is_rejected(self):
        # No corpus vector reaches this at any tag, so this test is the only thing holding
        # it: no envelope fixture carries a non-string `value` at tag 2, 3 or 4.
        #
        # DECIMAL is the case that shows the harm. `JsonNumber` subclasses `str`, so a
        # carrier of 0.010 canonicalizes to the same "0.010" the genuine leaf committed
        # and the envelope verifies, while any consumer re-reading those same bytes with a
        # stdlib parser gets 0.01 - the trailing-zero destruction specification section
        # 6.4 and `docs/decisions.md` part 0 exist to prevent, and which
        # `schemas/envelope-1.0.json` forbids by pinning the carrier to "type": "string".
        record = loads('{"marker": "m", "amount": 0.010}')
        built = issue(record, IDENTITY, resolver())
        profile = Profile("org.roax.corpus.synthetic", ((Key("marker"),),))
        config = VerifierConfig(
            profiles=DEFAULT_PROFILES.with_profile(profile),
            resolvers={"org.roax.corpus.synthetic": resolver()},
        )
        reveal = list(profile.floor()) + [(Key("marker"),), (Key("amount"),)]
        envelope = disclosed_copy(reveal, IDENTITY, built, profile=profile)

        def with_amount(carrier):
            copied = {**envelope, "disclosure": {**envelope["disclosure"]}}
            copied["disclosure"]["leaves"] = [
                {**leaf, "value": carrier} if leaf["displayPath"] == "amount" else leaf
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

        self.assertTrue(verify_envelope(with_amount("0.010"), config).accepted)
        self.assertEqual(
            verify_envelope(with_amount(JsonNumber("0.010")), config).reason,
            ErrorCode.ENVELOPE_SHAPE,
        )
        # The same collapse at the other two string carriers, and the tags that are
        # deliberately NOT string carriers must keep working.
        self.assertEqual(
            verify_envelope(with_amount(JsonNumber("5")), config).reason,
            ErrorCode.ENVELOPE_SHAPE,
        )
        boolean = loads('{"marker": "m", "flag": true}')
        boolean_built = issue(boolean, IDENTITY, resolver())
        self.assertTrue(
            verify_envelope(
                disclosed_copy(
                    list(profile.floor()) + [(Key("marker"),), (Key("flag"),)],
                    IDENTITY,
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
            '"leafCount":%s,"issuer":{"id":"i"},%s}'
        )
        cases = {
            "segments is null": base % (1, '"record":{},"salts":[{"segments":null,"salt":"'
                                        + salt + '"}]'),
            "segments carries an object key": base % (
                1, '"record":{},"salts":[{"segments":[{"key":{}}],"salt":"' + salt + '"}]'
            ),
            "auditPath is null": base % (
                1,
                '"disclosure":{"mode":"selective","leaves":[{"segments":[{"key":"a"}],'
                '"index":0,"tag":2,"value":"x","salt":"' + salt + '","auditPath":null}]}',
            ),
            "typeMap is a string": base % (
                1,
                '"typeMap":"oops","record":{},"salts":[{"segments":[{"key":"a"}],"salt":"'
                + salt + '"}]',
            ),
            # CPython 3.11+ caps int(str) at 4300 digits, so an unbounded count raises
            # ValueError before any rule of this specification applies. Same interpreter
            # hazard `roax_canon.numbers` already refuses for a decimal exponent.
            "leafCount has 5000 digits": base % ("9" * 5000, '"record":{},"salts":[]'),
            "index has 5000 digits": base % (
                1,
                '"disclosure":{"mode":"selective","leaves":[{"segments":[{"key":"a"}],'
                '"index":' + "9" * 5000 + ',"tag":2,"value":"x","salt":"' + salt
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
        self.assertEqual(a.encoded_paths, b.encoded_paths, "tree shape is a function of paths alone")

    def test_short_salt_rejected(self):
        with self.assertRaises(RoaxError) as ctx:
            leaf_hash((Key("a"),), 2, "x", b"\x00" * 8)
        self.assertEqual(ctx.exception.code, ErrorCode.SALT_LENGTH)


class TestTypeMapMatcher(unittest.TestCase):
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

    def test_ambiguous_patterns_are_rejected_rather_than_mis_parsed(self):
        for pattern in ("a[b]", "a[", "]a", "", "a.*"):
            with self.subTest(pattern=pattern):
                with self.assertRaises(RoaxError):
                    DisplayPatternTypeMap(
                        {**SYNTHETIC_MAP, "entries": [{"pattern": pattern, "tag": 2}]}
                    )

    def test_lookup_compares_raw_because_d14_is_open(self):
        # Decision D14 asks whether the type-map LOOKUP matches over an NFC-normalized
        # key or over the bytes as received, and it is OPEN (`docs/decisions.md` part 2a).
        # Both existing reference implementations compare raw and so does this one.
        # Adding an nfc() on either side would rule D14 silently, so this test pins the
        # current behaviour rather than endorsing it: U+212A renders as "K" and does not
        # match an ASCII "K" pattern, even though the leaf it names commits as ASCII.
        m = DisplayPatternTypeMap(
            {**SYNTHETIC_MAP, "entries": [{"pattern": "Kelvin", "jsonKind": "string", "tag": 2}]}
        )
        self.assertEqual(m.resolve((Key("Kelvin"),), "string"), 2)
        with self.assertRaises(RoaxError) as ctx:
            m.resolve((Key("\u212aelvin"),), "string")
        self.assertEqual(ctx.exception.code, ErrorCode.TYPE_UNRESOLVED)
        # And the corpus is deliberately neutral about which reading is right: its
        # synthetic map carries the key under BOTH spellings.
        both = DisplayPatternTypeMap(
            {**SYNTHETIC_MAP, "entries": [{"pattern": "\u212aelvin", "jsonKind": "string", "tag": 2},
                                          {"pattern": "Kelvin", "jsonKind": "string", "tag": 2}]}
        )
        self.assertEqual(both.resolve((Key("\u212aelvin"),), "string"), 2)
        self.assertEqual(both.resolve((Key("Kelvin"),), "string"), 2)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(not unittest.main(exit=False).result.wasSuccessful())
