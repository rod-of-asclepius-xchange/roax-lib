"""The corpus vector plan: INPUTS only, no expected values.

Everything in this file is an input a vector is built from. Every expected value - encoded
bytes, salts, leaf hashes, roots, audit paths, resolved tags, accept/reject verdicts - is
computed by an implementation and never written here.

That split is what makes the cross-check meaningful. `build_corpus.py` computes the expected
values with implementation A; `check_corpus.mjs --emit` recomputes every one of them with
implementation B and the two files are compared byte for byte. A value hard-coded here would
be agreed on by both implementations without either having computed it.

Class numbers refer to `docs/conformance-corpus.md` section 3.
"""

# Fixed inputs. THE TWO MASTER SALTS THAT SAT HERE ARE DELETED RATHER THAN LEFT UNUSED: decision
# D4 is ruled D4b, so section 7 has no derivation and nothing can seed one (spec section 7.1), and
# a committed 32-byte constant named MASTER_SALT is the readiest thing to reach for when
# reintroducing the construction the ruling removed. The class 12 note below records what the
# deleted salt vectors asserted and why nothing replaces them in kind.
RECORD_ID_A = "urn:uuid:11111111-1111-4111-8111-111111111111"
RECORD_ID_B = "urn:uuid:22222222-2222-4222-8222-222222222222"

# Leaf vectors use a FIXED salt, so that class 1, 2, 4, 5, 6 and 7 test leaf construction in
# isolation. It is fixed rather than derived because under D4b there is nothing to derive it
# from, and each leaf vector carries the salt it was built with, so a leaf failure stays a leaf
# failure.
LEAF_SALT = "000102030405060708090a0b0c0d0e0f"

# A single path shared by the discrimination leaves, so that any difference between two of them
# comes from the tag or the value and from nothing else.
VALUE_PATH = [{"key": "value"}]

DIGITS_40 = "1234567890123456789012345678901234567890"

ISSUER_ID = "did:web:corpus.roax.invalid"
ISSUER_KEY_ID = "did:web:corpus.roax.invalid#key-1"

# A recordType that exists ONLY inside this corpus. It is deliberately NOT in the
# docs/profiles/ registry and MUST NOT be issued against: it names synthetic fixtures whose
# shape was authored for these vectors rather than taken from any health authority's schema.
SYNTHETIC_RECORD_TYPE = "org.roax.corpus.synthetic"
SYNTHETIC_SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------------------------
# Class 1 - FHIR decimals, and class 2 - integers beyond 2^53
# ---------------------------------------------------------------------------------------------

# (name, class, tag, input). Tag 3 is INTEGER, tag 4 is DECIMAL, tag 2 is STRING, tag 1 is BOOL.
ENCODE_VALUE = [
    # Class 1. The pairs that MUST stay distinct, which is what the whole scheme exists for.
    ("decimal-0.010", 1, 4, "0.010"),
    ("decimal-0.01", 1, 4, "0.01"),
    ("decimal-1.50", 1, 4, "1.50"),
    ("decimal-1.5", 1, 4, "1.5"),
    ("decimal-2.0", 1, 4, "2.0"),
    ("decimal-2", 1, 4, "2"),
    ("decimal-neg-0.0", 1, 4, "-0.0"),
    ("decimal-neg-0.00", 1, 4, "-0.00"),
    ("decimal-neg-zero-integral", 1, 4, "-0"),
    ("decimal-tiny-20dp", 1, 4, "0.00000000000000000001"),
    ("decimal-40-digit-integer-part", 1, 4, DIGITS_40),
    ("decimal-40-digit-fraction", 1, 4, "0." + DIGITS_40),
    ("decimal-beyond-double", 1, 4, "1234567890123456789.1"),
    ("decimal-int64-max", 1, 4, "9223372036854775807"),
    # Class 1, the exponent trio the class states explicitly so it cannot be misread: these
    # three are EQUAL, because trailing zeros of the INTEGER part carry no precision.
    ("decimal-1e2", 1, 4, "1e2"),
    ("decimal-1.0e2", 1, 4, "1.0e2"),
    ("decimal-100", 1, 4, "100"),
    # ... and this one is DISTINCT from them, because trailing zeros of the FRACTION are not.
    ("decimal-100.0", 1, 4, "100.0"),
    # Class 1, the worked expansions the specification requires an implementation to reproduce.
    ("decimal-1.00e1", 1, 4, "1.00e1"),
    ("decimal-1.5e-2", 1, 4, "1.5e-2"),
    ("decimal-1e-3", 1, 4, "1e-3"),
    ("decimal-0e5", 1, 4, "0e5"),

    # Class 2.
    ("integer-int64-max", 2, 3, "9223372036854775807"),
    ("integer-int64-min", 2, 3, "-9223372036854775808"),
    ("integer-40-digit", 2, 3, DIGITS_40),
    ("integer-neg-zero", 2, 3, "-0"),
    ("integer-zero", 2, 3, "0"),
    ("integer-five", 2, 3, "5"),

    # Class 3's positive vector. 1e1023 expands to exactly 1024 digits, which is the bound, so
    # it MUST be accepted. Without it an implementation passes class 3 by rejecting everything
    # large. Its partner reject vector is `decimal-just-over-digit-bound`.
    ("decimal-at-digit-bound", 3, 4, "1e1023"),

    # Class 4. NFC and NFD spellings of the same character MUST encode identically.
    ("string-nfc-e-acute", 4, 2, "é"),
    ("string-nfd-e-acute", 4, 2, "é"),
    ("string-above-bmp", 4, 2, "\U0001f600"),
    ("string-fullwidth-z", 4, 2, "Ｚ"),
    ("string-ascii-z", 4, 2, "Z"),
    # U+212A KELVIN SIGN normalizes to ASCII K. It is the evidence that NFC can cross into
    # ASCII at all, which is why specification section 11.2 cites it.
    ("string-kelvin-sign", 4, 2, "K"),
    ("string-ascii-k", 4, 2, "K"),

    # Class 16 - Unicode version sensitivity, and honest about its own limit.
    #
    # NFC is version-dependent, so an implementation whose tables come from a different Unicode
    # release may legitimately differ. No character whose NFC form actually CHANGED between
    # recent releases has been identified for this corpus, so these vectors do not demonstrate a
    # version difference: they carry strings whose NFC form is stable across recent releases and
    # exercise the composition machinery that a version difference would disturb. The version
    # that produced them is the corpus-level `unicodeVersion` field, which is the marker class
    # 16 asks for. corpus/README.md records which tables each reference implementation ran, and
    # they were not the same release, which is the strongest thing available here short of a
    # character that actually moved.
    ("string-hangul-decomposed", 16, 2, "각"),
    ("string-hangul-composed", 16, 2, "각"),
    ("string-angstrom-singleton", 16, 2, "Å"),
    ("string-a-ring-composed", 16, 2, "Å"),
    ("string-combining-mark-reordering", 16, 2, "q̣̇"),
    ("string-combining-mark-canonical-order", 16, 2, "q̣̇"),
    ("string-vietnamese-decomposed", 16, 2, "ệ"),
    ("string-vietnamese-composed", 16, 2, "ệ"),
    ("string-no-composition-arabic", 16, 2, "مرحبا"),
    ("string-devanagari-nukta", 16, 2, "क़"),

    # Class 7. Same digits, different tags, and the empty carriers.
    ("string-five", 7, 2, "5"),
    ("decimal-5.0", 7, 4, "5.0"),
    ("string-true", 7, 2, "true"),
    ("bool-true", 7, 1, True),
    ("bool-false", 7, 1, False),
    ("integer-100", 7, 3, "100"),
    ("null-value", 5, 0, None),
    ("empty-array-value", 5, 6, None),
    ("empty-object-value", 5, 7, None),
]

# ---------------------------------------------------------------------------------------------
# Class 6 - path, and class 4's key half
# ---------------------------------------------------------------------------------------------

# (name, class, segments)
ENCODE_PATH = [
    ("path-root", 6, []),
    ("path-single-key", 6, [{"key": "a"}]),
    ("path-empty-string-key", 6, [{"key": ""}]),
    # The nested-versus-dotted pair section 5.1 uses. Provably distinct with no rule at all,
    # because the segment counts differ.
    ("path-nested-a-b", 6, [{"key": "keyCollisionA"}, {"key": "b"}]),
    ("path-literal-dotted-key", 6, [{"key": "keyCollisionB.c"}]),
    # Keys that dogtag REJECTS (flatten.rs:17-20). Length prefixing needs no rejection rule.
    ("path-key-with-dot", 6, [{"key": "a.b"}]),
    ("path-key-with-brackets", 6, [{"key": "a[0]"}]),
    ("path-key-with-all-three", 6, [{"key": "we.ird[key]"}]),
    ("path-array-of-one", 6, [{"key": "arrayOfOne"}, {"index": 0}]),
    ("path-index-zero", 6, [{"index": 0}]),
    ("path-index-max-u32", 6, [{"index": 4294967295}]),
    ("path-deep-nesting", 6, [{"key": k} for k in ("a", "b", "c", "d", "e", "f", "g", "h")]),
    # An array element and a numeric-keyed map member, which OpenAttestation commits
    # identically (specification section 5.1).
    ("path-numeric-key-zero", 6, [{"key": "0"}]),
    ("path-mixed", 6, [{"key": "a"}, {"index": 3}, {"key": "b"}, {"index": 0}]),

    # Class 4's key half. NFC and NFD keys MUST encode identically.
    ("path-nfc-key", 4, [{"key": "é"}]),
    ("path-nfd-key", 4, [{"key": "é"}]),
    ("path-above-bmp-key", 4, [{"key": "\U0001f600"}]),
    ("path-fullwidth-z-key", 4, [{"key": "Ｚ"}]),
    ("path-ascii-z-key", 4, [{"key": "z"}]),

    # Class 15's accept rows, at the encoding level. The guard verdicts themselves are envelope
    # vectors, because acceptance is a property of the guard and not of the encoding.
    ("path-bare-roax-key", 15, [{"key": "roax"}]),
    ("path-roax-x-key", 15, [{"key": "roaxX"}, {"key": "foo"}]),
    ("path-roax-dotted-not-first", 15, [{"key": "a"}, {"key": "roax.foo"}]),
    ("path-kelvin-key", 15, [{"key": "Kelvin"}]),

    # The reserved paths of section 11.2, each a SINGLE segment carrying the literal dotted
    # name and NOT one segment per dot component. Pinning their encoding pins the tree floor,
    # because every record commits them, and it pins their sort position: the five key lengths
    # are 13, 14, 15, 17 and 18 bytes and length precedes bytes in the encoding, so the
    # reserved leaves sort recordId, issuer.id, recordType, issuer.keyId, schemaVersion - an
    # order an alphabetical sort gets visibly wrong (specification section 5.3).
    ("path-reserved-record-type", 6, [{"key": "roax.recordType"}]),
    ("path-reserved-schema-version", 6, [{"key": "roax.schemaVersion"}]),
    ("path-reserved-record-id", 6, [{"key": "roax.recordId"}]),
    ("path-reserved-issuer-id", 6, [{"key": "roax.issuer.id"}]),
    ("path-reserved-issuer-key-id", 6, [{"key": "roax.issuer.keyId"}]),
]

# ---------------------------------------------------------------------------------------------
# Class 3 - rejection vectors, plus the rejections classes 4, 6 and 15 own
# ---------------------------------------------------------------------------------------------

# (name, class, tag or None, input). `input` uses the escape forms documented in
# corpus/README.md: a plain JSON value, {"$utf16": [...]}, {"$segments": [...]} or
# {"$jsonText": "..."}.
REJECT = [
    # Class 3, at a DECIMAL-bound path.
    ("reject-decimal-huge-exponent", 3, 4, "1.4e+9999"),
    ("reject-decimal-just-over-digit-bound", 3, 4, "1e1024"),
    ("reject-decimal-leading-zero", 3, 4, "01"),
    ("reject-decimal-empty-fraction", 3, 4, "1."),
    ("reject-decimal-empty-fraction-with-exponent", 3, 4, "1.e2"),
    ("reject-decimal-no-integer-part", 3, 4, ".5"),
    ("reject-decimal-explicit-plus", 3, 4, "+1"),
    ("reject-decimal-nan-text", 3, 4, "NaN"),
    ("reject-decimal-infinity-text", 3, 4, "Infinity"),
    ("reject-decimal-hex", 3, 4, "0x10"),
    ("reject-decimal-trailing-space", 3, 4, "1.0 "),
    # A trailing newline. This one exists because the two reference implementations disagreed
    # on it: Python's `$` also matches immediately before a trailing newline while JavaScript's
    # matches only at end of input, so an implementation written with `$` in a Python-family
    # regex dialect silently accepts "1.0\n" and canonicalizes it. Anchoring with \A and \Z is
    # what the grammar in specification section 6.2 means.
    ("reject-decimal-trailing-newline", 3, 4, "1.0\n"),
    ("reject-integer-trailing-newline", 3, 3, "1\n"),
    # Class 3, at an INTEGER-bound path.
    ("reject-integer-leading-zero", 3, 3, "01"),
    ("reject-integer-explicit-plus", 3, 3, "+1"),
    ("reject-integer-with-fraction", 3, 3, "1.0"),
    ("reject-integer-with-exponent", 3, 3, "1e2"),
    ("reject-integer-negative-leading-zero", 3, 3, "-01"),
    # Class 3, at the parser boundary. These are not values at a tag: JSON itself does not
    # admit them, and section 3.2 requires the rejection at the input boundary.
    ("reject-json-nan", 3, None, {"$jsonText": '{"a": NaN}'}),
    ("reject-json-infinity", 3, None, {"$jsonText": '{"a": Infinity}'}),
    ("reject-json-negative-infinity", 3, None, {"$jsonText": '{"a": -Infinity}'}),
    ("reject-json-duplicate-key", 3, None, {"$jsonText": '{"a": "x", "a": "y"}'}),

    # Class 4. Unpaired surrogates MUST be rejected, before normalization.
    ("reject-unpaired-high-surrogate-value", 4, 2, {"$utf16": ["0041", "d800", "0042"]}),
    ("reject-unpaired-low-surrogate-value", 4, 2, {"$utf16": ["dc00"]}),
    ("reject-unpaired-surrogate-key", 4, None,
     {"$segments": [{"key": {"$utf16": ["d83d", "0041"]}}]}),

    # Class 6. An index at 2^32 MUST be rejected rather than truncated.
    # NOTE: this cannot be expressed through the `segments` field, whose index maximum is
    # 4294967295, so it is carried in `input` instead. See corpus/README.md, "Known corpus
    # schema limits".
    ("reject-index-at-2-32", 6, None, {"$segments": [{"index": 4294967296}]}),
    ("reject-index-beyond-2-32", 6, None, {"$segments": [{"index": 4294967300}]}),

    # Class 15's reject rows. The guard is on the first segment's NFC-normalized key.
    ("reject-reserved-exact-collision", 15, None, {"$segments": [{"key": "roax.recordId"}]}),
    ("reject-reserved-prefix-squat", 15, None, {"$segments": [{"key": "roax.anythingElse"}]}),
    ("reject-reserved-future-leaf-squat", 15, None, {"$segments": [{"key": "roax.recordIdX"}]}),
]

# ---------------------------------------------------------------------------------------------
# Class 12 - cross-record unlinkability under independent per-leaf salts
# ---------------------------------------------------------------------------------------------
#
# THE SALT VECTOR CLASS IS GONE. It asserted that a (masterSalt, recordId, path) triple produced
# a given salt under the section 7 derivation, and decision D4 is ruled D4b: there is no
# derivation, no master salt and no preimage, so there is nothing for such a vector to assert
# (spec section 7.1). `saltVector` was removed from the corpus schema in the same change.
#
# What replaces it is behavioural rather than pinned. Salts are independent random draws, so no
# fixed hexadecimal expectation can exist for what an implementation must draw freshly; the
# runner performs `trials` independent issuances and asserts relations over the results.
#
# (name, class, paths, tag, value, trials, recordIds)
#
# `paths` carries AT LEAST TWO DISTINCT paths, and that is the half of this class that catches
# intra-record reuse: an implementation drawing ONE salt per record and reusing it across every
# leaf produces a different salt at any single path in each trial, so a single-path vector would
# pass it. Comparing two paths WITHIN one issuance is what fails it.
UNLINKABILITY = [
    (
        # The three mistakes docs/conformance-corpus.md class 12 names, each caught by a
        # different assertion: a deterministic salt fails the across-issuance assertions, one
        # draw per record fails the within-issuance one, and a salt reused across records fails
        # the across-issuance salt assertion.
        "unlinkability-independent-per-leaf-salts", 12,
        [
            [{"key": "fhirBundle"}, {"key": "entry"}, {"index": 0}, {"key": "birthDate"}],
            [{"key": "fhirBundle"}, {"key": "entry"}, {"index": 0}, {"key": "gender"}],
        ],
        2, "1965-08-09", 4, None,
    ),
    (
        # The same subject issued twice under ONE record identifier. Under the deleted D4a
        # construction the identifier was folded into every salt preimage, so a shared one was
        # the case that leaked; under D4b it is not an input to anything and the outcome is
        # unchanged. The vector states that explicitly rather than leaving a reader who knows
        # the old construction to wonder whether it still matters.
        "unlinkability-shared-record-id", 12,
        [
            [{"key": "fhirBundle"}, {"key": "entry"}, {"index": 0}, {"key": "birthDate"}],
            [{"key": "roax.recordId"}],
        ],
        2, "1965-08-09", 4, [RECORD_ID_A, RECORD_ID_A],
    ),
    (
        # A reserved leaf and a record leaf in one vector. Reserved leaves are ordinary leaves
        # in every respect (spec section 11.2), so they are salted independently too; an
        # implementation that special-cased them would pass every other class.
        "unlinkability-reserved-and-record-leaf", 12,
        [
            [{"key": "roax.issuer.id"}],
            [{"key": "é"}],
        ],
        2, "1965-08-09", 4, None,
    ),
]

# ---------------------------------------------------------------------------------------------
# Class 11 - the schema binding, over the type maps derived from the reference schemas
# ---------------------------------------------------------------------------------------------

# (name, recordType, segments, jsonKind). The expected outcome - a resolved tag or a fail-closed
# rejection - is COMPUTED against the committed type map, never written here. These reference
# `corpus/type-maps/<recordType>.json`, which `build_type_maps.py` derives from the reference
# schemas with a citation on every entry.
MOH_TYPE_MAP_VECTORS = [
    # Resolved bindings, one per schema scope the type map has to cover (specification section
    # 4.2): the vaccination healthcert's own inline definitions, the lite FHIR schema the PDT
    # and recovery healthcerts reference, and the notarise schema the vaccination healthcert
    # pulls in from a third document.
    ("typemap-vaccination-inline-definition", "sg.gov.moh.vaccination-healthcert",
     [{"key": "fhirBundle"}, {"key": "entry"}, {"index": 0}, {"key": "gender"}], "string"),
    ("typemap-vaccination-notarise-scope", "sg.gov.moh.vaccination-healthcert",
     [{"key": "notarisationMetadata"}, {"key": "reference"}], "string"),
    ("typemap-recovery-lite-fhir-scope", "sg.gov.moh.recovery-healthcert",
     [{"key": "fhirBundle"}, {"key": "entry"}, {"index": 0}, {"key": "resource"},
      {"key": "birthDate"}], "string"),
    ("typemap-recovery-profile-scope", "sg.gov.moh.recovery-healthcert",
     [{"key": "validUntil"}], "string"),
    ("typemap-pdt-polymorphic-type", "sg.gov.moh.pdt-healthcert",
     [{"key": "type"}], "string"),

    # Fail-closed, on paths that are genuinely present in the shipped samples and that the
    # reference schemas do not determine a ROAX tag for. These are not invented gaps.
    #
    #   dose            declared "type": "number" with no pattern. ROAX has two numeric tags
    #                   and JSON Schema's `number` chooses neither. FHIR's own lite schema
    #                   distinguishes `integer` from `decimal` by PATTERN, both being
    #                   "type": "number"; the notarise schema carries no such pattern.
    #   expiryDateTime  declared with a `format` and `examples` and no `type` at all.
    #   issuers[*].name PDT's root object declares no `issuers` member and does not close
    #                   itself, so the member is permitted and undeclared.
    ("typemap-vaccination-dose-fails-closed", "sg.gov.moh.vaccination-healthcert",
     [{"key": "notarisationMetadata"}, {"key": "signedEuHealthCerts"}, {"index": 0},
      {"key": "dose"}], "number"),
    ("typemap-vaccination-expiry-fails-closed", "sg.gov.moh.vaccination-healthcert",
     [{"key": "notarisationMetadata"}, {"key": "signedEuHealthCerts"}, {"index": 0},
      {"key": "expiryDateTime"}], "string"),
    ("typemap-pdt-issuers-fails-closed", "sg.gov.moh.pdt-healthcert",
     [{"key": "issuers"}, {"index": 0}, {"key": "name"}], "string"),
    ("typemap-pdt-template-fails-closed", "sg.gov.moh.pdt-healthcert",
     [{"key": "$template"}, {"key": "name"}], "string"),
    ("typemap-pdt-attachments-fails-closed", "sg.gov.moh.pdt-healthcert",
     [{"key": "attachments"}, {"index": 0}, {"key": "data"}], "string"),
    # A path no sample contains, so that the fail-closed rule is shown to apply to an ordinary
    # unknown path and not only to the schema gaps above.
    ("typemap-recovery-unknown-path-fails-closed", "sg.gov.moh.recovery-healthcert",
     [{"key": "notInAnySchema"}], "string"),
]


# ---------------------------------------------------------------------------------------------
# Class 8 - tree shape, and class 9 - negative proof vectors
# ---------------------------------------------------------------------------------------------

# Section 9's split rule goes wrong only at non-power-of-two sizes, so a corpus that tests only
# 8 and 16 proves nothing. 130 is the leaf count of the largest real MOH record.
TREE_SIZES = [1, 2, 3, 5, 7, 8, 9, 130]

# (name, class, attack, baseTreeSize, index)
NEGATIVE_PROOF = [
    ("negative-wrong-root", 9, "wrong-root", 8, 3),
    ("negative-flipped-sibling", 9, "flipped-sibling", 8, 3),
    ("negative-internal-node-as-leaf", 9, "internal-node-as-leaf", 8, 0),
    ("negative-index-out-of-range", 9, "index-out-of-range", 8, 8),
    ("negative-truncated-audit-path", 9, "truncated-audit-path", 8, 3),
    ("negative-extended-audit-path", 9, "extended-audit-path", 8, 3),
    # Repeated at a non-power-of-two size, where a hand-rolled tree is most likely to be wrong.
    ("negative-wrong-root-n7", 9, "wrong-root", 7, 5),
    ("negative-flipped-sibling-n7", 9, "flipped-sibling", 7, 5),
    ("negative-truncated-audit-path-n7", 9, "truncated-audit-path", 7, 5),
    ("negative-extended-audit-path-n7", 9, "extended-audit-path", 7, 5),
    ("negative-internal-node-as-leaf-n130", 9, "internal-node-as-leaf", 130, 0),
]
