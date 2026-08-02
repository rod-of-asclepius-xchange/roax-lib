# What the Kotlin implementation found

Written while building an independent library from [`docs/spec/roax-canon-1.md`](../docs/spec/roax-canon-1.md) alone, under ruled decision Da.

**Result: 504 of 504 committed corpus vectors pass, with zero NOT RUN**, producing roots byte-identical to the Rust, TypeScript, Python and Swift libraries wherever the corpus covers a behaviour.
It was 488 when this document was written, and section 8 below records what the vectors added since then found in this module.
Two class-5 vectors need a reading of the empty-container rule that the specification does not support, which is the already-recorded corpus defect restated in section 2 below.

Findings are ordered by who has to act on them: the specification first, then the corpus, then things that are only facts about this platform.

## 1. Kotlin/JVM literal-preserving JSON is now established, and the answer is a hand-written scanner

**This closes an open engineering question the specification names.**
Section 6.4's platform table marks Kotlin/JVM "Not established", and section 2.2 says to treat that row as an open engineering question rather than a solved one, because "nobody has yet checked".

Checked.
**No JSON library on the JVM can carry this design**, and the reason is not performance or ergonomics but that two required properties are unavailable together:

- a number must survive as its **verbatim source text**, because section 6.2 requires `0.010` to stay distinct from `0.01` and section 6.4 forbids parsing record numbers through any floating-point type;
- **duplicate member names must be visible**, because section 3.2 requires them to be rejected, and a `Map`-shaped parse result has already silently dropped one by the time a caller could look.

So `io.roax.canon.json.JsonReader` is a hand-written scanner, which is the same answer section 6.4 already records for Swift.
The Kotlin row of that table can move from "Not established" to a confirmed positive result with the same mechanism as Swift's.

**`java.math.BigDecimal` is the trap this platform sets, and it is worse than a plain float** because it looks like the right tool.
Measured on JDK 17.0.19:

| Behaviour | Consequence |
|---|---|
| `BigDecimal("1e2").toString()` is `1E+2`, `0e5` is `0E+5`, `1e-7` is `1E-7` | Scientific notation, which the section 6.2 output grammar `^-?(0\|[1-9][0-9]*)(\.[0-9]+)?$` does not admit at all. |
| `toPlainString()` reproduces **all seven** worked examples in section 6.2 | Which is exactly what makes reaching for it dangerous: the formatting agrees and the validation does not. |
| Its parser accepts `+1`, `007`, `.5`, `5.` | Every one of those is rejected by one or both ROAX grammars, so validation has to be hand-written regardless. |
| `equals` compares scale, `compareTo` does not | `0.010`.equals(`0.01`) is false while `compareTo` is 0. Either answers a different question, and picking the wrong one silently loses the FHIR precision requirement. |
| `stripTrailingZeros()` turns `2.0` into `2` and `100` into `1E+2` | The trailing-zero destruction FHIR R4 says implementations SHALL NOT do, plus scientific notation on the way out. |
| Length is only measurable after expansion | `1.4e+9999` allocates ten thousand digits before it can be rejected, and `1.4e+999999999` is a memory-exhaustion input. |

This library therefore does the arithmetic on digit strings and computes the 1024-digit bound **before allocating anything**.
`JvmPlatformTrapTest` pins every row above as an executable assertion about the JDK, so a future JDK that changes one fails loudly rather than moving a root.

**A second platform trap, recorded because it is silent in both directions.**
`"A\uD800".toByteArray(UTF_8)` yields `41 3f` - the unpaired surrogate becomes an ASCII `?` - and `java.text.Normalizer.normalize` passes a lone surrogate straight through unchanged.
Neither raises anything, so section 6.1's "unpaired surrogates MUST be rejected before normalization" has to be an explicit check on this platform, exactly as section 6.1 records for dogtag's TypeScript SDK.
`String(bytes, UTF_8)` substitutes U+FFFD for malformed UTF-8 with the same silence, so decoding goes through a `CharsetDecoder` set to `REPORT`.

## 2. The Unicode version cannot be pinned from inside a JVM library, and here is what that costs

**Section 6.1 pins Unicode 15.1 and no JDK ships it.**
`java.text.Normalizer` uses whatever Unicode data drop the running JDK - or, on Android, the platform ICU - was built against, and no public API exposes which.
Measured by probing `Character.isDefined` on a code point first assigned in each release:

| Runtime | NFC tables |
|---|---|
| JDK 17.0.19 | Unicode 13.0 |
| JDK 25.0.2 | Unicode 16.0 |
| Python 3.13.5, corpus implementation A | Unicode 15.1 |
| Node 22 / ICU 77, corpus implementation B | Unicode 16.0 |

Section 6.1 anticipates this and makes a mismatch detectable **by declaration** rather than by demonstration, so `Nfc` is an injectable interface that declares its `unicodeVersion`, the corpus runner prints the comparison on every run, and the library does not claim a conformance it cannot verify.

**What the gap actually costs was measured rather than assumed, twice.**

The whole test suite runs on either JDK - `gradle -p kotlin -Proax.testJdk=25 :roax-canon:test` - and **all 504 vectors pass under both**, at Unicode 13.0 and at 16.0.
Separately, NFC was applied to every string appearing anywhere in the committed corpus, and the digest over the normalized set is **byte-identical** on both JDKs.

**That second measurement is a live guard rather than a one-time run, and it is [`PlatformNfcTablesTest`](roax-canon/src/test/kotlin/io/roax/canon/PlatformNfcTablesTest.kt).**
Leaving it as prose would have left the property unguarded, and it is the one claim here that least deserves that: it rots silently the first time a JDK or an Android ICU changes how NFC normalizes, which is precisely the divergence this protocol exists to prevent.
The test pins the digest `4d02818303f50a85f439b01b7c9b6ba71fe0a533be171715217c39224a9549bf` together with the counts that corroborate it, and **running it under both JDKs IS the cross-version comparison**, because a single JVM cannot compare two table versions.
The constant is deliberately not keyed on the probed `unicodeVersion`, since a per-version table would degrade the guard into "each runtime agrees with itself".

Its input set is `corpus/conformance-corpus-1.0.json` plus `corpus/fixtures/records`, `corpus/fixtures/envelopes` and `corpus/type-maps`, taking object member keys as well as string values because the key site is half of what specification section 5.1 hashes and half of what class 19 tests.
That yields **14,836 strings, of which 54 are non-ASCII and 23 are changed by NFC**, with none skipped for carrying a lone surrogate, and every one of those four figures is identical on JDK 17.0.19 and JDK 25.0.2.
The hand-run figure of 14,826 recorded before the guard existed came from a slightly different enumeration, and the two agree on the 54 and the 23, which are the only strings the measurement can turn on.

That brackets the 15.1 pin from both sides, which is a slightly stronger demonstration than the one `corpus/README.md` already records for Node 16.0 against Python 15.1.
**It is not a demonstration that a version mismatch is detectable**, which class 16 already says it is not: no character whose NFC form changed between these releases has been identified for this corpus.
It is evidence that these particular vectors are stable across the release boundary, and nothing more.

## 3. The corpus can only be passed through a format the repository forbids for resolution

Restated rather than newly found - `docs/typescript-implementation-findings.md` records it identically - because a second independent build hitting it is itself evidence.

Every committed vector needing a map resolves against `corpus/type-maps/<recordType>.json`, which is the display-pattern format whose own schema says it "MUST NOT be used to publish or resolve a type map", and which section 4.2 rules out by requiring a structured-path DFA that "MUST NOT parse or match a display path".
There is no published artifact for `org.roax.corpus.synthetic` at all, so **no conforming DFA resolver can resolve a single corpus record.**

This library builds the resolver behind the `TypeResolver` interface and ships both: `DfaTypeMap` is the operative one and `DisplayPatternTypeMap` is labelled corpus-only at its declaration.
`PublishedTypeMapTest` exercises the operative one against the four artifacts in `type-maps/`, because otherwise the format the specification actually mandates would ship untested while the superseded one carried the whole suite.

## 4. Specification section 3.3's empty-container rule is unsatisfiable against the committed corpus, at exactly 2 vectors

Also already recorded, and reproduced here independently at the same count, which is the point of measuring it again.

Section 3.3 says an empty container gets tag 6 or 7 "only when the exact selected map authorizes that structured path and observed kind", because assigning the tag first would let an unknown empty issuer extension bypass decision D7.
`corpus/type-maps/org.roax.corpus.synthetic.json` declares `a.b` for `jsonKind: "null"` alone, while `record-structure-empty-array` and `record-structure-empty-object` carry an empty array and an empty object there.
Under the specification's own rule both records fail closed and have no root; the corpus asserts one.

`EmptyContainerAuthorization` exposes both readings, defaulting to the specification's.
The corpus runner asserts that the divergence set is **exactly those two vector names** rather than tolerating a range, so a corpus rebuild that changes the count fails here.

## 5. The two `unresolved` slots the published artifacts still carry are asserted, not assumed

`docs/type-maps.md` section 1.6 states that not one of the four ruled bindings is in the four published artifacts.
`PublishedTypeMapTest` asserts that directly: the published vaccination artifact fails closed for `dose` at `number` and for `expiryDateTime` at `string`, while the corpus-side map resolves both.
If a future change regenerates the artifacts without deleting section 1.6, this test fails rather than passing silently.

The same suite re-measures section 2.3's claim that no artifact emits NULL, BYTES or BLOB_REF, over every reachable binding in all four artifacts, and reproduces the four pinned content IDs from the exact bytes.

## 6. Behaviours the corpus does not discriminate

Under decision Da the corpus is the entire enforcement mechanism, so a behaviour it does not cover is where five libraries may silently diverge.
Each of these is a **library-local regression** in `SpecificationGapTest`, not a corpus edit: specification section 1.1 requires a canonicalization rule and the vectors asserting it to land in the same change, and `docs/conformance-corpus.md` section 1.2 forbids a corpus row from deciding an open question, so adding rows from a library build would settle several of these from inside a data file.

| Gap | What this library does | What closing it needs |
|---|---|---|
| **Class 9's forged-tree-size row.** `corpus/README.md` marks the class stale: no committed `negativeProof` row has that attack, and the carrier holds only a supplied leaf hash rather than the path, tag, value and salt needed to drive full disclosed-copy verification. | Reproduces the section 11.1 measurement - an internal node at index 0 with a forged size of 2 verifies against the genuine root - and then shows whole-envelope verification refusing it, because section 10 step 2 recomputes every leaf hash. | A corpus carrier that can express a full disclosed-copy attack. This is corpus-side work, and a library-local regression does not complete the release gate. |
| **No vector generates a disclosure.** Every class-14, 15, 17 and 18 vector consumes a pre-built fixture, so an implementation whose issuance and verification halves disagree passes the corpus. | Commits, discloses, serializes and re-verifies, asserting that no withheld leaf's salt appears anywhere in the output. | A vector class that names paths to disclose and asserts the result verifies. |
| **`0e99999`** - ambiguity 2, which reading the digit bound counts. | Rejected, the literal and memory-safe reading. | A ruling, then a vector. The vector alone would settle it from inside a data file. |
| **The 1024-digit bound on INTEGER** - ambiguity 1. | Applied, matching both reference implementations and Rust. | A ruling; section 6.2 states the bound under *Canonical decimal* while its own justification counts an integer against it. |
| **NFC-colliding sibling keys with disjoint descendants** - ambiguity 6. | Accepted, matching Rust. A duplicate *complete* encoded leaf path is still refused. | A ruling. |
| **Whether display-pattern `**` matches a run of zero segments.** | One or more. | Nothing: this belongs to a format that is superseded for resolution. The real fix is the corpus moving to the structured-path DFA, which also closes finding 3. |
| **An empty-string key inside a record.** `path-empty-string-key` pins the encoding; no record vector carries one, so nothing checks that a flattener keeps the segment rather than skipping it. | Committed as a real segment, and the root differs from the same record without it. | A record vector, which decides nothing open and would be a clean addition. |

## 7. Two things this library deliberately does not do

**No profile-schema validation and no value-domain validation.**
Section 4.2 orders complete profile validation *before* map resolution, and ruled decision D13a keeps value-domain rules in a separate, independently versioned layer.
So the `dose` positive-integer narrowing is not here and this layer accepts `0` as a grammar-valid INTEGER - `RuledDecisionsTest` asserts that explicitly, so the layering is visible rather than looking like an oversight.

**No anchoring.**
Section 2.2 leaves the registry undesigned, so `VerifierConfig.anchorRoot` and `anchorHashAlg` are seams.
When `anchorHashAlg` is absent the envelope's own value is used, which is a hint being trusted; mechanism H2 of section 7.4 is the only algorithm binding that works and it needs a registry this library cannot supply.
The type is nullable rather than absent so a deployment can see in the signature that it is trusting a hint.

## 8. What corpus class 20 found here, which no verifying-side vector could

**Kind: library.
Two defects, both fixed, and both in the ENVELOPE-PRODUCING half this module had never been asked to exercise.**

Every committed envelope fixture is written by the corpus generator, so classes 14, 15, 17 and 18 run this module's verifier against a third party's bytes.
Nothing ran it against its own output until class 20 asked an implementation to issue a copy, disclose from it and verify the result.

**The tag-5 BYTES disclosure carrier was base64 on both sides.**
`EnvelopeWriter` emitted `Base64Strict.encode(...)` and the verifier read `Base64Strict.decode(...)`, so the two agreed with each other and disagreed with every other implementation.
`schemas/envelope-1.0.json` pins that carrier to "lowercase hex of even length"; base64 is how a RECORD spells `base64Binary`, and the pinned RFC 4648 form is an input-admissibility condition there rather than the committed value (specification section 6.3).
**No committed disclosed-copy fixture carries a BYTES leaf**, which is why 488 vectors could not see it: the corpus reaches tag 5 through record vectors and through the value encoder, never through a disclosure.

**The `typeMap` member was written without its `version`.**
`schemas/envelope-1.0.json` requires `id` and `version` together whenever the member is present, so this module emitted a schema-invalid envelope under `EnvelopeProfile.V2_TYPE_MAP_BOUND`.
Nothing caught it because nothing compared a produced envelope against a committed one.

**The first fix for that was itself schema-invalid, and by the same mechanism.**
It emitted both members while coercing an absent `typeMapVersion` to the empty string, and `""` fails the schema's `^[0-9]+\.[0-9]+\.[0-9]+$` exactly as an absent member fails `required`.
`EnvelopeVerifier` reads only `typeMap.id` and validates no version at all, so this module would again have accepted its own invalid output, and every class-20 vector supplies a version so the corpus still could not see it.
`Reserved.leavesFor` already refused an absent `typeMapId` under the same profile, so the asymmetry was inside one module: the writer now refuses an absent version on the same terms.

**And the mirror of it on the reading side: a wrongly typed `typeMap` member read as ABSENT.**
`(env["typeMap"] as? JsonObject)?.get("id") as? JsonString` answers `null` for `"typeMap": []` just as it does for a member that is not there, and absence is the one shape the binding treats as a pre-binding envelope-1.0 copy.
That is the same defect as `"salts": {}` beside a `disclosure`, which the corpus does carry as a vector: **a guard that turns itself off on malformed input is worse than no guard.**
It was not exploitable here - with the leaf disclosed the binding still fails on the null outer value - but both reference implementations refuse this shape and this module accepted it, and only the `salts` instance of the rule got a fixture.
A present `typeMap` is now rejected as `envelope-shape` unless it is an object carrying a string `id` and a string `version`.

**A third defect came from classes 14 and 18 rather than 20**, and is the same shape as the two above.
The `roax.typeMap.id` binding fired only when the verifier's own `EnvelopeProfile` selected it, so a V1-configured verifier accepted a copy that withheld the leaf while the outer member named one.
It now fires whenever EITHER side names a type map; `corpus/README.md` states the rule and the residual case.

**And one the corpus still cannot reach at all, fixed on the evidence of the specification alone.**
`hashAlg` is carried twice when an anchoring registry is configured - once by the envelope and once by the registry - and this module read `config.anchorHashAlg ?: env["hashAlg"]` without ever comparing them.
An envelope declaring `Poseidon-BN254` was therefore verified under SHA-256 and its declared value discarded silently, which is an issuance specification section 7.4 forbids being accepted without a word.
`docs/conformance-corpus.md` class 18 states the row and marks it UNBUILT, because specification section 2.2 leaves the anchoring registry undesigned and the corpus may not invent that interface, so `SpecificationGapTest` carries it instead.
The Rust, TypeScript and Python libraries all rejected the disagreement already.
