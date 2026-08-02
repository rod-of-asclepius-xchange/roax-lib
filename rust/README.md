# ROAX-CANON/1 for Rust

This crate is the independent Rust implementation of ROAX-CANON/1.
It implements strict literal-preserving JSON parsing, structured path and value encoding, schema-selected type-map lookup, salted leaf construction, RFC 9162 trees, full-copy verification and selective disclosure.

The implementation is written for Rust 1.81 or newer and forbids unsafe code.

## Protocol boundaries

Use `issue_full_copy`, `issue_full_copy_with_salts`, `commit_full_copy_with_salts`, `verify_full`, `disclose` and `verify_disclosed` as the protocol boundaries.
`issue_full_copy_with_salts` is the deterministic twin of the first: conformance corpus class 20 pins an issuance, and under decision D4b nothing re-derives a salt, so a round trip whose expected envelope bytes are committed has to be issued under committed salts.
The `Profile` implementation supplied by an application validates the complete record schema and binds the exact record type, schema version, type-map artifact and issuer scope before construction or verification, as required by ROAX-CANON/1 sections 3.2, 4.2 and 10.

`fold_inclusion_proof_untrusted` is deliberately named as a low-level RFC 9162 fold.
It is not disclosure verification because both the alleged leaf hash and tree size are caller inputs; `verify_disclosed` recomputes the salted leaf hash first, as required by ROAX-CANON/1 section 10 step 2 and section 11.1.

Envelope generation 1 and 2 have different reserved leaf sets.
Callers select `ReservedLeafSet::EnvelopeV1` only for the committed legacy corpus and envelope 1.0 compatibility, while current issuance uses `ReservedLeafSet::EnvelopeV2` and commits the exact `roax.typeMap.id` leaf under ROAX-CANON/1 sections 4.2 and 11.2.

**A verifier that accepts BOTH generations must choose one per envelope with `reserved_leaf_set_for`, never from the outer `typeMap` member.**
That member is supplied by the holder, so choosing on it hands the choice to the party the binding constrains: delete the member, withhold the leaf, and a verifier reading only the member drops to the 1.0 generation where `roax.typeMap.id` is not in the floor and nothing asks for it.
`reserved_leaf_set_for` reads the COMMITTED evidence as well - any disclosed leaf or `salts` entry addressing that single segment selects 2.0 - and a copy that then presents no member fails with `Error::TypeMapNotNamed`, which is kept apart from `Error::OuterIdentityMismatch` because with neither side naming a map the two agree and nothing is mismatched.
A verifier that requires the binding regardless passes `EnvelopeV2` directly instead of calling it.

Decision D14 was ruled D14a on 2026-07-30: the type-map lookup compares the NFC-normalized key (ROAX-CANON/1 section 4.2; `docs/decisions.md`, D14).
`DfaTypeMap::resolve` normalizes a KEY segment before taking its transition, and a loaded artifact's transition keys are already validated NFC, so both sides of the comparison are normalized.

**`LookupKeyMode`, `TypeResolver::ensure_lookup_decision_independent` and `Error::LookupNormalizationUndecided` are gone.**
While D14 was open this crate took neither side: the mode had no default and the construction and verification paths refused a key whose binding differed between the two readings.
That guard existed to refuse a lookup whose answer depended on the open question, and with one reading there is nothing for it to refuse.
It was deleted rather than reduced to a single-variant enum, which would have invited the other variant back.

Normalizing does not widen a map: a key whose NFC form is not a declared transition still fails closed with `Error::UnknownTypeBinding`.

This crate carries no value-domain rule such as the vaccination `dose` positive-integer narrowing, and that is ruled rather than an omission: ROAX-CANON/1 section 4.2 orders profile validation before map resolution, and decision D13a keeps value-domain validation in a separate, independently versioned layer.
`SchemaValidator` is the seam an application supplies one through, and `tests/dfa_profile_protocol.rs` shows a profile using it to refuse `dose: 0` while the bare canonicalization layer accepts the same value.

`DfaTypeMap::from_exact_bytes` loads validated base artifacts.
It rejects issuer child artifacts because proving their parent identity and logical additivity requires the exact parent and the executable checks in `docs/type-maps.md` section 5; accepting a child without that input would violate the fail-closed rule in ROAX-CANON/1 section 4.2.

## Validation

From the repository root:

```sh
ROAX_EXTRACTED_RECORDS="$(pwd -P)/schemata/extracted" \
  cargo test --manifest-path rust/Cargo.toml --all-targets

ROAX_EXTRACTED_RECORDS="$(pwd -P)/schemata/extracted" \
  cargo clippy --manifest-path rust/Cargo.toml --all-targets -- -D warnings
```

Class 10 needs two samples extracted from the gitignored Open-Attestation schemata checkout at commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`, as cited by `corpus/conformance-corpus-1.0.json`: the recovery healthcert, and the vaccination healthcert its two 2026-07-30 bindings made committable.
Inside `ROAX_EXTRACTED_RECORDS` this test names each file by the vector's EXPORT rather than by its profile, so they are `sampleDocument.json` and `sampleVaccineHealthCert.json` (`tests/conformance_corpus.rs:1078-1085`); the TypeScript runner's `<authority>.<profile>.json` convention is a separate contract and one directory can satisfy both.
With neither sample supplied the integration test fails visibly instead of reporting a complete pass.
With one of the two, class 10 reports `PASS WITH SKIPS` and names each vector it could not run, which is a partial run rather than a failure (`tests/conformance_corpus.rs:116-140`).

The committed class-9 rows all match, but the corpus currently lacks the forged-size, full-disclosure row required by `docs/conformance-corpus.md` class 9.
`tests/security_boundaries.rs` pins the Rust defence locally, while `corpus/README.md` records why that does not complete the cross-language release gate.
