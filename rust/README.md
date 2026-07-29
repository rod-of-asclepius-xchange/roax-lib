# ROAX-CANON/1 for Rust

This crate is the independent Rust implementation of ROAX-CANON/1.
It implements strict literal-preserving JSON parsing, structured path and value encoding, schema-selected type-map lookup, salted leaf construction, RFC 9162 trees, full-copy verification and selective disclosure.

The implementation is written for Rust 1.81 or newer and forbids unsafe code.

## Protocol boundaries

Use `issue_full_copy`, `commit_full_copy_with_salts`, `verify_full`, `disclose` and `verify_disclosed` as the protocol boundaries.
The `Profile` implementation supplied by an application validates the complete record schema and binds the exact record type, schema version, type-map artifact and issuer scope before construction or verification, as required by ROAX-CANON/1 sections 3.2, 4.2 and 10.

`fold_inclusion_proof_untrusted` is deliberately named as a low-level RFC 9162 fold.
It is not disclosure verification because both the alleged leaf hash and tree size are caller inputs; `verify_disclosed` recomputes the salted leaf hash first, as required by ROAX-CANON/1 section 10 step 2 and section 11.1.

Envelope generation 1 and 2 have different reserved leaf sets.
Callers select `ReservedLeafSet::EnvelopeV1` only for the committed legacy corpus and envelope 1.0 compatibility, while current issuance uses `ReservedLeafSet::EnvelopeV2` and commits the exact `roax.typeMap.id` leaf under ROAX-CANON/1 sections 4.2 and 11.2.

Decision D14 remains open, so `LookupKeyMode` has no default.
The high-level construction and verification paths reject a key whose binding changes between raw and NFC-normalized lookup rather than deciding D14 inside this library (`docs/decisions.md`, D14; ROAX-CANON/1 section 4.2).

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

Class 10 needs the recovery sample extracted from the gitignored Open-Attestation schemata checkout at commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`, as cited by `corpus/conformance-corpus-1.0.json`.
The integration test fails visibly instead of reporting a complete pass when that sample is absent.

The committed class-9 rows all match, but the corpus currently lacks the forged-size, full-disclosure row required by `docs/conformance-corpus.md` class 9.
`tests/security_boundaries.rs` pins the Rust defence locally, while `corpus/README.md` records why that does not complete the cross-language release gate.
