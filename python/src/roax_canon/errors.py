"""Error taxonomy for ROAX-CANON/1.

Every rejection this library performs carries a stable machine code.
The codes are the ones the conformance corpus uses as its ``reason`` strings, so an
implementation report can be compared against `corpus/conformance-corpus-1.0.json`
without a translation table (`corpus/README.md`, "Checking an implementation that is
not one of these two").

Nothing here is a warning.
Specification section 4.2 and ruled decision D7a require an unresolved path to fail
closed, so this module has no severity axis: a condition either rejects or it does not
exist.
"""

from __future__ import annotations

__all__ = [
    "RoaxError",
    "InputError",
    "GrammarError",
    "PathError",
    "TypeResolutionError",
    "TreeError",
    "EnvelopeError",
    "ErrorCode",
]


class ErrorCode:
    """The stable rejection codes.

    Grouped by the specification section that requires the rejection.
    """

    # Section 3.2, admissible values at the input boundary.
    DUPLICATE_KEY = "duplicate-key"
    NON_FINITE_NUMBER = "non-finite-number"
    UNPAIRED_SURROGATE = "unpaired-surrogate"
    MALFORMED_JSON = "malformed-json"

    # Section 6.2, canonical numbers.
    INTEGER_GRAMMAR = "integer-grammar"
    DECIMAL_GRAMMAR = "decimal-grammar"
    DIGIT_BOUND_EXCEEDED = "digit-bound-exceeded"

    # Section 6.3, the pinned base64 form.
    BASE64_NOT_CANONICAL = "base64-not-canonical"

    # Section 5, path encoding.
    INDEX_OUT_OF_32_BIT_RANGE = "index-out-of-32-bit-range"
    DUPLICATE_PATH = "duplicate-path"

    # Section 11.2, the reserved namespace guard.
    RESERVED_NAMESPACE = "reserved-namespace"

    # Section 4.2 and section 6.5, schema binding.
    TYPE_UNRESOLVED = "type-unresolved"
    TYPE_MAP_REJECTED = "type-map-rejected"

    # Sections 6.1 and 7.4, registered but unusable selections.
    # Specification section 9. An ordering this version does not define, which is H3 of
    # section 9.5 at its narrowest, and two leaves of one record sharing a leaf hash under
    # `hash` ordering - paths are already unique, so that is a collision rather than a tie
    # and section 9 requires rejection rather than a tie-break.
    ORDERING_NOT_DEFINED = "ordering-not-defined"
    LEAF_HASH_COLLISION = "leaf-hash-collision"
    HASH_ALG_UNDEFINED = "hash-alg-undefined"
    HASH_ALG_NOT_ALLOWED = "hash-alg-not-allowed"
    BLOB_REF_NOT_DECLARED = "blob-ref-not-declared"

    # Section 3.3, the record's own contribution.
    EMPTY_RECORD = "empty-record"

    # Section 9 and section 10, tree and proof.
    TREE_EMPTY = "tree-empty"
    INCLUSION_PROOF_FAILED = "inclusion-proof-failed"

    # Section 11, the envelope.
    ENVELOPE_SHAPE = "envelope-shape"
    CANON_MISMATCH = "canon-mismatch"
    PROFILE_UNKNOWN = "profile-unknown"
    MASTER_SALT_IN_ENVELOPE = "master-salt-in-envelope"
    DISCLOSED_COPY_CARRIES_SALTS = "disclosed-copy-carries-salts"
    DISCLOSED_LEAF_NAMED_WITHOUT_VALUE = "disclosed-leaf-named-without-value"
    SALTS_DUPLICATE_PATH = "salts-duplicate-path"
    SALTS_LENGTH_NOT_LEAF_COUNT = "salts-length-not-leaf-count"
    SALT_MISSING_FOR_LEAF = "salt-missing-for-leaf"
    SALT_LENGTH = "salt-length"
    LEAF_COUNT_MISMATCH = "leaf-count-mismatch"
    ROOT_MISMATCH = "root-mismatch"
    OUTER_IDENTITY_MISMATCH = "outer-identity-mismatch"
    MINIMUM_DISCLOSURE_FLOOR = "minimum-disclosure-floor"

    OK = "ok"


class RoaxError(Exception):
    """Base class for every rejection.

    ``code`` is the stable identifier and is what a conformance report compares.
    ``detail`` is free prose and is never compared.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class InputError(RoaxError):
    """Rejected at the input boundary, before any hashing (specification section 3.2)."""


class GrammarError(RoaxError):
    """A value that does not match its tag's grammar (specification section 6.2)."""


class PathError(RoaxError):
    """A path that cannot be encoded (specification section 5)."""


class TypeResolutionError(RoaxError):
    """The type map did not authorize this path and kind (specification section 4.2)."""


class TreeError(RoaxError):
    """A tree or proof that cannot be constructed or verified (specification section 9)."""


class EnvelopeError(RoaxError):
    """An envelope that MUST be rejected (specification sections 10 and 11)."""
