# What the Swift build found

**Status:** the Swift library passes all 488 committed corpus vectors, with class 10 run against the pinned reference checkout.
This document records what building it independently from `docs/spec/roax-canon-1.md` surfaced.

Each finding says what was measured, on what, and whether it is a finding about **this language**, about the **specification**, or about the **corpus**.
That split matters: a language finding is this library's problem to solve, a specification finding is a defect to report rather than work around, and a corpus finding is a release gate that is not yet closed.

Everything below was measured on Apple Swift 6.2.4 (swiftlang-6.2.4.1.4), macOS 15 arm64, unless stated otherwise.

## Summary

| # | Finding | Kind | Does the corpus catch it? |
|---:|---|---|---|
| 1 | `JSONSerialization` destroys numeric literals, and does so inconsistently | language | Yes, via class 1 - if you use it, you fail |
| 2 | `Decimal` carries 38 significant digits and drops trailing zeros | language | Yes, via classes 1 and 2 |
| 3 | `Data(base64Encoded:)` accepts a non-canonical final quantum | language | Yes, one vector of class 3 |
| 4 | Swift `String` cannot hold an unpaired surrogate and substitutes U+FFFD | language | Yes, class 4 |
| 5 | No Apple API reports the Unicode version of its NFC tables | language | No, and class 16 already says why |
| 6 | The forged-tree-size attack is not reachable through any committed vector | corpus | **No - this is the stale class-9 row** |
| 7 | **Swift `String` equality is canonical equivalence, so the obvious duplicate-key check silently answers `corpus/README.md` ambiguity 6** | language **and** specification | **No, in either direction** |
| 8 | Specification section 3.3's empty-container rule is unsatisfiable against the committed corpus | specification vs corpus | Inverted: the corpus fails an implementation that follows the specification |
| 9 | Section 3.3's zero-leaf MUST can never fire from a JSON record | specification | No, and it cannot |

Findings 8 and 9 were reported by the TypeScript and Python builds before this one and are restated here only because a fourth independent implementation reaching the same place is the evidence those reports were about.
Findings 1 to 5 are Swift-specific.
Findings 6 and 7 are new here.

## 1. `JSONSerialization` destroys numeric literals, and the failure is inconsistent

**Kind: language.
Specification section 6.4 predicted this and this build confirms it, including the part that makes it dangerous.**

Section 6.4 already records Swift as "Yes, negative result": nothing in Foundation preserves a raw numeric literal.
Reproduced here on the values that matter:

```
  0.010                 -> 0.01                    __NSCFNumber
  1.50                  -> 1.5                     __NSCFNumber
  2.0                   -> 2                       __NSCFNumber
  1e2                   -> 100                     __NSCFNumber
  0.1                   -> 0.10000000000000001     __NSCFNumber
  1234567890123456789.1 -> 1234567890123456789.1   NSDecimalNumber   <- survives
  1.4e+9999             -> parse failure
```

`0.010` becoming `0.01` is the FHIR R4 `SHALL` this whole design exists to honour.

**The last row is the finding rather than the first five.**
Foundation switches representation on magnitude, so a large literal survives intact while every small one is destroyed.
An implementation built on `JSONSerialization` therefore passes any test whose fixtures are big numbers and fails on ordinary clinical values, which is the shape of bug that reaches production.

A second, independent reason Foundation cannot be used that section 6.4 does **not** name: `JSONSerialization` silently accepts `{"a":"x","a":"y"}` and keeps one member.
Specification section 3.2 requires duplicate keys to be rejected at the input boundary, and a parser built on Foundation cannot raise that rejection at all.

**What this library does.**
`Sources/ROAXCanon/JSONValue.swift` is a hand-written scanner over UTF-8 bytes that keeps every number as its verbatim source text and rejects duplicate keys, non-finite literals and unpaired surrogates.
Specification section 6.4 says porting such a scanner is REQUIRED for any Swift implementation, and that is what it is.

Pinned by `SwiftPlatformTrapTests.testJSONSerializationDestroysLiteralsAndOursDoesNot`, which asserts **Foundation's** behaviour as well as ours, so the test fails if a future Foundation changes and the finding needs re-measuring.

## 2. `Decimal` is base-10 and still cannot carry a FHIR decimal

**Kind: language.
This is the trap that looks like the solution.**

`Decimal` is a base-10 type, so it avoids binary floating point and looks like the right carrier for a specification obsessed with decimal precision.
It is not, for two independent reasons:

```
  0.010                                                 -> 0.01     trailing zero lost
  38 significant digits is the ceiling:
  12345678901234567890123456789012345678901234567890    -> 12345678901234567890123456789012345678900000000000
  3.14159265358979323846264338327950288419716939937510  -> 3.14159265358979323846264338327950288419
  1e400                                                 -> nil
```

Corpus class 1 carries a 40-digit integer part with a 40-digit fraction, which is 80 significant digits, and class 2 carries integers beyond 2^53.
`Decimal` cannot represent either.

**The 50-digit row is the dangerous one**: it returns a value rather than failing, so a `Decimal`-based implementation would compute a wrong root silently instead of erroring.

**What this library does.**
Nothing in `Sources/ROAXCanon/Numbers.swift` constructs a number of any kind.
Exponent expansion, the digit bound and output normalization are all operations over ASCII digits.

## 3. `Data(base64Encoded:)` accepts a non-canonical final quantum

**Kind: language.
Foundation gets three of the four rejections right, which is what makes the fourth easy to miss.**

Specification section 6.3 pins RFC 4648 section 4 and requires rejecting, by name, the URL-safe alphabet, absent or excess padding, any character outside the alphabet including a line break, and **a final quantum whose unused bits are non-zero**, which RFC 4648 section 3.5 identifies as the non-canonical case.

Measured:

| Input | `Data(base64Encoded:)` | Required |
|---|---|---|
| `SGVsbG8sIFJPQVg` (unpadded) | rejects | reject |
| `-_8=` (URL-safe alphabet) | rejects | reject |
| `SGVs\nbG8=` (line wrapped) | rejects | reject |
| `aGl=` (non-zero pad bits) | **accepts, 2 bytes** | **reject** |

A reader who spot-checks the first three concludes Foundation is sufficient.
The corpus does carry the fourth case, as `reject-bytes-base64-nonzero-pad-bits`, so an implementation that used Foundation here fails one vector out of 488 - which is exactly the margin this finding is about.

**What this library does.**
`Sources/ROAXCanon/Base64.swift` decodes by hand and checks the unused bits of the final quantum explicitly.
Under the ruled FHIR `base64Binary` binding this check is an **input-admissibility** condition and never the committed value: the octets are hashed, and a spelling outside the pinned form is rejected before it is decoded.

## 4. Swift `String` cannot hold an unpaired surrogate, and substitutes silently

**Kind: language.**

Specification section 3.2 rejects unpaired UTF-16 surrogates at the input boundary, and section 6.1 requires the rejection to happen before normalization.
dogtag's TypeScript SDK has the same requirement for the opposite reason: JavaScript strings *can* hold one and Rust strings cannot.

Swift is a third case.
`String(decoding: [0x0041, 0xD800, 0x0042], as: UTF16.self)` yields `A\u{FFFD}B`: the surrogate is replaced rather than rejected.

**So the rejection has to happen before the `String` exists**, or an input the specification refuses is converted into one that commits cleanly - and the substituted U+FFFD would be hashed as though the issuer had written it.

**What this library does.**
`UTF16Input.string(fromCodeUnits:)` validates surrogate pairs over the code units and throws.
The JSON scanner routes every `\u` escape through it, and gathers literal runs into UTF-16 before converting, so both the escaped and the raw path reach the same check.

## 5. No Apple API reports the Unicode version of its NFC tables

**Kind: language.
The pin is a declaration on this platform, and it cannot be anything else.**

Specification section 6.1 pins Unicode 15.1 and says an implementation whose NFC tables are from a different version MUST NOT claim conformance.
On Apple platforms:

- `precomposedStringWithCanonicalMapping` is the only NFC, and Foundation exposes no table version.
- `u_getUnicodeVersion` is not reachable through `dlsym`: probing `/usr/lib/libicucore.dylib` for `u_getUnicodeVersion_<major>` across ICU majors 55 to 90 finds no such symbol.
  Why it is absent was not established; what was measured is that the probe returns nothing.
- The Swift standard library's own property tables answer for characters assigned in **Unicode 16.0** - U+10D40 GARAY DIGIT ZERO reports `decimalNumber` rather than unassigned, as do U+105C0, U+11BC0 and U+1CC00 - so the tables are at least 16.0 and are demonstrably not the pinned 15.1.

**This is the same position the corpus is already in and is not a new risk.**
`corpus/README.md` records that reference implementation B generated agreeing vectors under Node's Unicode 16.0 tables against a corpus pinned and generated at 15.1, and `docs/conformance-corpus.md` class 16 states its own limit: it detects a version mismatch by declaration rather than by demonstration, because no character whose NFC form changed across the boundary has been identified.
This library agrees with all 27 class-4 vectors, all 20 class-16 vectors and both class-19 vectors while running 16.0-or-later tables, which is a fourth data point that these particular vectors are stable across that release boundary.

**What this library does.**
`NFC.declaredUnicodeVersion` is documented as the declared pin rather than a reading of the tables, and the doc comment says so at the point a reader would otherwise assume it was measured.

## 6. The forged-tree-size attack is unreachable through any committed vector

**Kind: corpus.
This is the stale class-9 row, confirmed from a fourth implementation.**

Specification section 11.1 records a measurement that corrected the specification: presenting the internal node `MTH(L[0:4])` as the leaf at index 0 with a **forged tree size of 2** verifies against the genuine root under RFC 9162 section 2.1.3.2, because that algorithm takes the tree size as an input rather than recovering it.

Reproduced here, on an 8-leaf tree, and both halves hold:

```
  internal node MTH(L[0:4]) presented as a leaf at index 0
    with the TRUE tree size 8   -> verification FAILS     (correct)
    with a FORGED tree size 2   -> verification SUCCEEDS
```

`corpus/README.md` already records that no committed `negativeProof` row carries attack `forged-tree-size`, and that the carrier cannot express one: those rows supply only a `leafHash`, not the path, tag, value and salt needed to drive the full disclosed-copy verification specification section 10 step 2 requires.

**This build confirms the gap from the other side.**
Every one of the 11 committed class-9 vectors passes against a verifier that has **no** leaf-hash recomputation at all, because they all attack the bare fold.
The defence the specification actually relies on is therefore not exercised by the corpus.

`CorpusGapTests.testForgedTreeSizeVerifiesBareButIsRefusedByFullVerification` is a library-local regression covering it.
**It does not close the gap.**
`corpus/README.md` says plainly that an implementation-specific regression may demonstrate the defence and does not make the missing release gate complete, and that is the correct reading: four libraries each with their own regression is four unrelated tests, not one arbiter.

## 7. Swift `String` equality is canonical equivalence, so the obvious duplicate-key check answers an open ambiguity by accident

**Kind: language and specification.
This is the finding this build exists to have produced, and no committed vector reaches it in either direction.**

Swift compares `String` by **canonical equivalence**, not by bytes, and `Hashable` agrees:

```swift
"\u{00e9}" == "e\u{0301}"          // true
Set(["\u{00e9}", "e\u{0301}"]).count   // 1
Array("\u{00e9}".utf8) == Array("e\u{0301}".utf8)   // false
```

Specification section 3.2 requires an implementation to reject "duplicate keys in a map".
The obvious Swift spelling of that check is a `Set<String>` of member names.
**That spelling rejects a record whose two member names are distinct raw keys agreeing only under NFC** - and it was the first thing this implementation did, caught by a test written for a different purpose.

That shape is exactly `corpus/README.md` ambiguity 6, recorded there as unruled:

> Specification sections 3.2 and 3.3 require raw map keys to be unique and emit complete leaf paths, while section 5 normalizes each KEY segment, so `{"é":{"a":1},"é":{"b":2}}` has neither a duplicate raw key nor a duplicate complete encoded leaf path even though the two intermediate paths encode identically.
> The Rust implementation accepts that shape, and no vector distinguishes acceptance from rejecting every intermediate-key collision.

**So the hazard is not that Swift is wrong; it is that Swift answers the question without being asked.**
A Rust or Python implementer has to type a normalization call to reach the rejecting reading, and typing one is a decision a reviewer can see.
A Swift implementer reaches the rejecting reading by writing the idiomatic thing, and reaches it in the **opposite direction from the rest of the family**, with nothing in the diff to review.
There is no vector on either side, so the corpus cannot catch it.

**What this library does, and why.**
`JSONScanner` keys its duplicate-detection set on the **raw UTF-8 bytes**, which matches the Rust implementation and the plain reading of "raw map keys are unique".
The choice is commented at the line, not just here, because the fix is one character wide and looks like a pessimization.

**The same language feature is correct one layer down, and the contrast is the useful part.**
`PathSegment`'s derived `Equatable` is also canonical equivalence, and there it is exactly right: `encodePath` commits `NFC(key)`, so two canonically equivalent keys always encode identically and segment equality coincides with encoded-path equality.
Both readings are pinned by tests (`testStringEqualityIsCanonicalEquivalenceAndDuplicateDetectionIsNot` and `testPathSegmentEqualityAgreesWithEncodedPathEquality`), so a future edit that "harmonizes" them breaks one.

**Recommended, and not done here because it is not this library's call.**
Ambiguity 6 should be ruled, and the ruling should land with a corpus vector on whichever side wins.
**Swift appears to be the only one of the named target languages that sets this trap, which is why it took four implementations to surface.**
Rust and Go compare strings by bytes, JavaScript and Kotlin/JVM by UTF-16 code units, and Python by code points; none of them makes two NFC-equivalent spellings equal by default.
So the three libraries that came before could not have hit it, and a reviewer reading those three would have no reason to look for it here.
A one-line rule in the specification and one vector on the winning side would remove the whole class, and would also give the next canonical-equivalence language something to fail against.

## 8. Specification section 3.3's empty-container rule is unsatisfiable against the committed corpus

**Kind: specification versus corpus.
Independently reproduced, and measured at exactly the same 2 vectors the earlier builds reported.**

Specification section 3.3 requires the exact selected map to authorize a structured path and observed kind before the flattener emits EMPTY_ARRAY or EMPTY_OBJECT, because assigning those tags earlier lets an unknown empty issuer extension bypass decision D7's fail-closed rule.

`corpus/type-maps/org.roax.corpus.synthetic.json` declares `a.b` for `jsonKind: "null"` alone, while `corpus/fixtures/records/structure-empty-array.json` and `structure-empty-object.json` both carry an empty container at `a.b`.
Under the specification both records fail closed and have no root; the corpus asserts a root for each.

Measured by running this library both ways:

| Reading | Result |
|---|---|
| Corpus reading, tags 6 and 7 assigned without map authorization | 488 pass, 0 fail |
| Specification reading, section 3.3 as written | 486 pass, **2 fail** - `record-structure-empty-array` and `record-structure-empty-object` |

Under specification section 1.1 that is a release-blocking corpus defect and the specification governs.
The narrow fix is a corpus edit - two authorizing rows in the synthetic map - rather than an implementation default.

**What this library does.**
`EmptyContainerPolicy` makes the choice explicit at the call site, with `.mapAuthorized` as the **default**, so following the specification is what a caller gets without asking.
The corpus runner selects the other reading and says so in its banner.
`CorpusConformanceTests.testSpecificationEmptyContainerReadingCostsExactlyTwoVectors` pins the cost at exactly 2, so a corpus fix shows up here as that assertion changing rather than as a mystery.

## 9. Section 3.3's zero-leaf MUST can never fire from a JSON record

**Kind: specification.
Restated rather than newly found; three independent implementations agreed before this one, and this is the fourth.**

Specification section 3.3 says a record contributing zero leaves of its own MUST be rejected at issuance.
But the same section emits a leaf for every empty container, so `{}` yields one EMPTY_OBJECT leaf and `[]` yields one EMPTY_ARRAY leaf.
There is no JSON record that contributes zero leaves, so the MUST is unreachable from the input boundary.

The check is implemented anyway, on the same reasoning specification section 9.1 gives for keeping `MTH([])`: a total function is easier to port than one with an undefined case, and a caller that reaches it has a defect worth failing loudly on rather than an input worth hashing.

## What this build did not find

Stated because a findings document that lists only hits is not checkable.

- **No disagreement with any committed vector**, under the corpus reading of finding 8.
  All 488 pass, including the four class-10 vectors against the reference checkout at the pinned commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`.
  The shipped vaccination sample commits at 91 leaves without an issuer key identifier and 92 with one; recovery commits at 69 and 70.
- **No disagreement about the two vectors that discriminate ruled decision D14a.**
  `normalization-nfc-key-end-to-end` and `record-guard-kelvin-key` both resolve through NFC, and both would fail closed under raw matching.
- **No ambiguity found in specification sections 5, 8 or 9.**
  Path encoding, the leaf preimage and the tree function were implemented from the text without a judgement call, and they were right first time against class 8's 173 vectors - 8 tree roots and 165 inclusion proofs - plus 86 leaf vectors and 28 path vectors.
  That is worth recording as evidence that those three sections are as implementable as section 1 claims.
- **The reason-code divergence `corpus/README.md` measured is real and this library adds to it.**
  This implementation names the fail-closed condition `type-map-fail-closed`, agreeing with the TypeScript and Rust libraries and differing from the reference implementations' `type-map-uncovered-path` and from Python's `type-unresolved`.
  A declared equivalence table in the runner maps one reference code to the one local code naming the same condition, so a rejection for a different reason still fails.
  Harmonizing the codes is an API change in four packages and was not made here.
