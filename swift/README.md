# The Swift implementation of ROAX-CANON/1

A zero-dependency SwiftPM package implementing [`docs/spec/roax-canon-1.md`](../docs/spec/roax-canon-1.md), built for macOS and iOS because it is destined for the dogtag iOS app.

**This is the fourth independent build, and independent means what it says.**
Decision D was ruled Da on 2026-07-29 to independent, corpus-enforced libraries rather than a shared core over a binding layer, and the obligation that ruling carries is on **how** each library is written: from the specification text, without reading another implementation while writing it.
This package was written that way.
`corpus/tools/roax_ref.py`, `corpus/tools/roax_ref.mjs`, `corpus/tools/check_corpus.mjs`, `rust/`, `src/` and `python/` were not read during implementation; validation against the corpus happened afterwards.
A library produced by reading an existing one passes the corpus while destroying what a pass means.

## Status

**488 of 488 committed corpus vectors pass**, with class 10 run against the pinned reference checkout.

| Measure | Result |
|---|---|
| Corpus vectors | 488 pass, 0 fail, 0 NOT RUN with a reference checkout |
| Unit and gap tests | 38 pass |
| Vaccination sample | commits at 91 leaves without an issuer key identifier, 92 with one |
| Recovery sample | commits at 69 leaves without an issuer key identifier, 70 with one |
| Runtime dependencies | none; CryptoKit where it exists, and an in-tree SHA-256 otherwise |

What that pass does and does not mean is in [`FINDINGS.md`](FINDINGS.md), which is worth more than the code.
Four findings are new with this build: a Swift `String` comparison rule that silently answers an open specification ambiguity in the opposite direction from the rest of the family; two corpus gaps - the forged-tree-size attack, and the fact that no vector covers the ENVELOPE-PRODUCING side, which hid a real bug in this library that all 488 vectors missed; and the envelope-2.0 type-map binding, which the corpus cannot reach in either direction.

## Running it

```sh
swift build --package-path swift
swift test  --package-path swift
swift run   --package-path swift roax-conformance
```

The runner's exit status follows `corpus/README.md`, so a bare run does not read as a pass:

| Status | Meaning |
|---:|---|
| 0 | Every check and vector ran and passed. |
| 1 | At least one check ran and failed. |
| 2 | Nothing failed, but at least one check or vector was NOT RUN. |

**Class 10 needs the pinned third-party reference checkout**, which `.gitignore` excludes by design and which is never copied into this repository.
Extract the two records it needs into a scratch directory first, then name that directory:

```sh
python3 corpus/tools/extract_reference_record.py \
  --module <checkout>/src/sg/gov/moh/recovery-healthcert/2.0/sample-data.ts \
  --export sampleDocument --out /tmp/roax-records/sg.gov.moh.recovery-healthcert.json

python3 corpus/tools/extract_reference_record.py \
  --module <checkout>/src/sg/gov/moh/vaccination-healthcert/1.0/sample-data.ts \
  --export sampleVaccineHealthCert --out /tmp/roax-records/sg.gov.moh.vaccination-healthcert.json

swift run --package-path swift roax-conformance --references /tmp/roax-records
```

**The filename inside that directory is the runner's contract**, and it is `<recordType>.json`.
The vector names only the path inside the reference checkout and the extraction utility writes wherever `--out` says, so a mismatch is reported as NOT RUN naming the exact path probed.
This is the same convention the TypeScript runner uses and it is **not** Rust's, which names each file by its export instead through `ROAX_EXTRACTED_RECORDS`; one directory can satisfy both.
`swift test` reads the same directory from `ROAX_REFERENCE_RECORDS`, and without it exactly the four class-10 vectors report NOT RUN.

The checkout must be at Open-Attestation/schemata commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`, which is what every artifact records.

## What is in the package

| Target | What it is |
|---|---|
| `ROAXCanon` | The library. No dependencies. |
| `ROAXCanonCorpus` | The corpus runner, as a library so that `swift test` is a real gate rather than a second suite that could pass while the corpus failed. |
| `roax-conformance` | The command-line front end to that runner. |

Inside `ROAXCanon`, the pieces that carry a protocol boundary:

| File | Boundary it owns |
|---|---|
| `JSONValue.swift` | The literal-preserving JSON scanner specification section 6.4 requires for Swift, and the section 3.2 input-boundary rejections. |
| `Numbers.swift` | Canonical INTEGER and DECIMAL over ASCII digits, the 1024-digit bound, and exponent expansion. |
| `Base64.swift` | The RFC 4648 section 4 form pinned by specification section 6.3, as an input-admissibility condition. |
| `Path.swift` | `encodePath`, the display form that is never hashed, and the reserved-namespace guard. |
| `TypeMap.swift` | The resolver seam, and the superseded display-pattern matcher the corpus is expressed in. |
| `Commitment.swift` | Flattening, the reserved-leaf union, the section 9 sort and issuance. |
| `Envelope.swift` | Both copy kinds, the outer-identity binding and the minimum-disclosure floor, in the order section 11.3 derives. |
| `MerkleTree.swift` | RFC 9162 with the section 9.1 adaptation, over already-hashed leaves. |

## Six things a reader should know before changing anything here

### The type-map resolver is an interface because the corpus forces it to be

Specification section 4.2 makes the operative matcher a structured-path DFA over `schemas/type-map-artifact-1.0.json`, and says the display-pattern format MUST NOT be used to resolve.
Every corpus vector that needs a map nevertheless resolves against `corpus/type-maps/<recordType>.json`, which **is** that superseded format, and no published artifact for `org.roax.corpus.synthetic` exists at all - so no structured-path DFA can resolve a single corpus record.
`TypeResolver` is therefore a protocol, `DisplayPatternTypeMap` is labelled superseded at its declaration, and a structured-artifact resolver can be added without any caller changing.
Do not quietly promote the display-pattern format to operative.

### The empty-container policy defaults to the specification, not to the corpus

`EmptyContainerPolicy.mapAuthorized` is the default, because specification section 3.3 says the map must authorize EMPTY_ARRAY and EMPTY_OBJECT before the flattener assigns them.
The committed corpus does not implement that rule, so the runner selects `.assignedWithoutMapAuthorization` and prints which reading it is using.
The cost is exactly 2 class-5 vectors and a test pins that number.
See [`FINDINGS.md`](FINDINGS.md) finding 8; the fix is a corpus edit, not an implementation default.

### Duplicate keys are compared as raw bytes, and the one-character difference is load-bearing

Swift compares `String` by canonical equivalence rather than by bytes, so the idiomatic `Set<String>` duplicate-key check rejects records whose member names differ raw and agree under NFC.
That decides `corpus/README.md` ambiguity 6 in the opposite direction from the Rust implementation, through a language feature rather than a decision.
`JSONScanner` keys on `Array(key.utf8)` for that reason.
The same language feature is *correct* for `PathSegment`, where canonical equivalence coincides exactly with encoded-path equality, and both readings are pinned by tests so an edit that harmonizes them breaks one.
See [`FINDINGS.md`](FINDINGS.md) finding 7.

### A disclosure this library produces must verify through this library's verifier

No corpus vector checks that: every committed envelope fixture was built by something else, so the corpus only ever runs the verifier against a third party's bytes.
`Commitment.disclose` therefore fills in each leaf's carrier through `Leaf.carrierValue`, and the carriers are per tag rather than the record's spellings - BYTES is lowercase hex here even though the record spelled it base64.
See [`FINDINGS.md`](FINDINGS.md) finding 10, which records the bug this gap hid.

### What this library verifies about a type map is one thing, and this is not envelope-2.0 support

The committed corpus is `schemas/envelope-1.0.json` throughout, and this package parses a `typeMap` member and commits `roax.typeMap.id` as a fifth reserved leaf.
That makes it *partly* a 2.0 implementation, which is worth stating precisely rather than leaving a reader to infer from the source.

**Implemented.**
In a disclosed copy, the outer `typeMap.id` is bound to the `roax.typeMap.id` leaf the root commits, and the leaf joins the minimum-disclosure floor.
Both are driven by what is **committed**, never by whether the holder chose to present the outer member: the binding fires whenever either side names a type map, and absence is the same `outer-identity-mismatch` as disagreement.
A check whose execution the presenter controls is not a check.

**Not implemented, and each one is named individually because a summary would read as more coverage than there is:**

| Check `schemas/envelope-2.0.json` implies | Status here |
|---|---|
| Fetching the artifact `typeMap.id` names | Not done; this package retrieves nothing. |
| Reproducing the artifact content identifier from fetched bytes | Not done; `typeMap.id` is compared as an opaque string. |
| Comparing the artifact's `recordType`, `schemaVersion` and `typeMapVersion` against the envelope's | Not done. |
| Issuer-scope membership against an extension artifact's `scope.issuerIds` | Not done; no issuer extension is admitted or refused here. |
| Resolving through the operative structured-path DFA | Not done; the display-pattern resolver above is what runs. |

**One case a single envelope carries no evidence for.**
A disclosed copy that omits both the outer member and the leaf is byte-indistinguishable from a legitimate 1.0 copy, and the only signal a fifth reserved leaf was committed is `leafCount`, which specification section 11.1 measured is not authenticated in a disclosed copy.
So it is the verifier's decision rather than the envelope's: `EnvelopeVerifier(typeMapBinding: .required)` demands a copy name a type map at all, and `.boundWhenPresent` is the default because the corpus is 1.0.
That demand is enforced on **both** copy kinds, and refusing it reports `type-map-not-named` rather than `outer-identity-mismatch`, because with neither the outer member nor the leaf present the two sides agree and nothing is mismatched.
See [`FINDINGS.md`](FINDINGS.md) finding 11.

### There is one leaf-preimage builder and nothing else assembles those bytes

`LeafConstruction.preimage` is it.
dogtag records the cost of a second one - "A second preimage builder is the drift" - and under ruled decision D4b there is no salt preimage left to be the other one.
Nothing else in this package concatenates a domain string, a path and a tag.

## Platform support

`Package.swift` declares macOS 13 and iOS 16, and **the iOS half is verified rather than declared**:

```sh
xcodebuild -scheme ROAXCanon -destination 'generic/platform=iOS' build
```

builds `ROAXCanon` against `iPhoneOS26.2.sdk` for `arm64-apple-ios16.0` and succeeds, with CryptoKit resolving there.
That check is worth running rather than assuming, because `swift build` alone uses the macOS sysroot even when handed an iOS target triple, and reports success while warning `using sysroot for 'MacOSX' but targeting 'iPhone'`.
A package that only ever saw `swift build` could fail on the platform it was written for.

Nothing in the library needs Darwin: SHA-256 comes from CryptoKit through `#if canImport(CryptoKit)` and from `ReferenceSHA256` otherwise, and a test asserts the two agree across every block boundary.
That pair is a cross-check rather than a divergence risk precisely because the test exists.

Foundation is used for two things only, and both are noted where they appear: `precomposedStringWithCanonicalMapping` for NFC, and file and `Data` handling in the runner.
`JSONSerialization` and `Decimal` are used **nowhere** in the library, and appear only inside tests that assert what they do wrong.
