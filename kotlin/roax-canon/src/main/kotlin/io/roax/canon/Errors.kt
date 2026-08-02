package io.roax.canon

/**
 * Every condition this library refuses on, as a stable machine-readable code.
 *
 * The codes are this library's own taxonomy. `corpus/README.md` records that the four existing
 * implementations already name two of these conditions four and two different ways respectively,
 * so a corpus `reason` is the reference implementations' spelling rather than a normative code.
 * The conformance runner therefore carries a DECLARED equivalence table
 * ([io.roax.canon.conformance.ReasonEquivalence]) mapping one reference code to the one local code
 * naming the same condition; a rejection for a different reason still fails.
 */
enum class Reason(val code: String) {
    // --- value and path encoding (specification sections 5 and 6) ---
    INTEGER_GRAMMAR("integer-grammar"),
    DECIMAL_GRAMMAR("decimal-grammar"),
    DIGIT_BOUND_EXCEEDED("digit-bound-exceeded"),
    UNPAIRED_SURROGATE("unpaired-surrogate"),
    INDEX_OUT_OF_32_BIT_RANGE("index-out-of-32-bit-range"),
    BASE64_NOT_CANONICAL("base64-not-canonical"),
    SALT_LENGTH("salt-length"),

    // --- input boundary (specification section 3.2) ---
    DUPLICATE_KEY("duplicate-key"),
    NON_FINITE_NUMBER("non-finite-number"),
    JSON_SYNTAX("json-syntax"),
    MALFORMED_UTF8("malformed-utf8"),

    // --- schema binding (specification section 4.2, decision D7) ---
    /**
     * No transition, or no output for the observed JSON kind. Fail closed.
     *
     * `roax_ref.py`/`roax_ref.mjs` spell this `type-map-uncovered-path` and the Python library
     * spells it `type-unresolved`; this spelling matches the TypeScript and Rust libraries.
     */
    TYPE_MAP_FAIL_CLOSED("type-map-fail-closed"),
    TYPE_TAG_KIND_MISMATCH("type-tag-kind-mismatch"),
    BLOB_REF_NOT_DECLARED("blob-ref-not-declared"),

    // --- reserved namespace (specification section 11.2) ---
    RESERVED_NAMESPACE("reserved-namespace"),

    // --- record and tree (specification sections 3.3 and 9) ---
    EMPTY_RECORD("empty-record"),
    DUPLICATE_LEAF_PATH("duplicate-leaf-path"),
    ROOT_MISMATCH("root-mismatch"),
    LEAF_COUNT_MISMATCH("leaf-count-mismatch"),
    INCLUSION_PROOF_FAILED("inclusion-proof-failed"),

    // --- envelope (specification sections 7.3, 10.2, 11.1 and 11.3) ---
    HASH_ALG_NOT_ALLOWED("hash-alg-not-allowed"),

    /**
     * An ordering `ROAX-CANON/1` does not define. H3 of specification section 9.5 at its narrowest:
     * refused rather than approximated by the default.
     */
    ORDERING_NOT_DEFINED("ordering-not-defined"),

    /**
     * Two leaves of one record share a leaf hash under `hash` ordering. Paths are already unique,
     * so this is a collision rather than a tie, and section 9 requires rejection rather than a
     * tie-break.
     */
    LEAF_HASH_COLLISION("leaf-hash-collision"),
    PROFILE_UNKNOWN("profile-unknown"),
    CANON_MISMATCH("canon-mismatch"),
    OUTER_IDENTITY_MISMATCH("outer-identity-mismatch"),
    MINIMUM_DISCLOSURE_FLOOR("minimum-disclosure-floor"),
    BOTH_RECORD_AND_DISCLOSURE("both-record-and-disclosure"),
    NEITHER_RECORD_NOR_DISCLOSURE("neither-record-nor-disclosure"),
    DISCLOSED_COPY_CARRIES_SALTS("disclosed-copy-carries-salts"),
    MASTER_SALT_IN_ENVELOPE("master-salt-in-envelope"),
    DISCLOSED_LEAF_NAMED_WITHOUT_VALUE("disclosed-leaf-named-without-value"),
    SALT_MISSING_FOR_LEAF("salt-missing-for-leaf"),
    SALTS_DUPLICATE_PATH("salts-duplicate-path"),
    SALTS_LENGTH_NOT_LEAF_COUNT("salts-length-not-leaf-count"),
    ENVELOPE_SHAPE("envelope-shape"),
}

/** The single exception type this library raises. Every instance carries a [Reason]. */
class RoaxException(val reason: Reason, detail: String) :
    RuntimeException("${reason.code}: $detail")

internal fun fail(reason: Reason, detail: String): Nothing = throw RoaxException(reason, detail)
