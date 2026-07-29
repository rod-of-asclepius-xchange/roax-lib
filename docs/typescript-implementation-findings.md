# Findings from the independent TypeScript implementation

This document records every place where the TypeScript implementation under `src/` disagreed with
the conformance corpus, or where the specification admitted two honest readings.

It is written from the build of `ROAX-CANON/1` in TypeScript, done from
[`docs/spec/roax-canon-1.md`](spec/roax-canon-1.md) alone.
`corpus/tools/roax_ref.py` and `corpus/tools/roax_ref.mjs` were deliberately not read while
implementing, and neither was `corpus/tools/check_corpus.mjs`, which imports one of them.
The value of a third implementation is that it agrees without having read either, so the corpus was
run only after each module was written.

Specification section 1.1 governs how these are classified: the specification is normative for
meaning and the corpus is the executable arbiter, so where the two diverge the specification
governs and the divergence is a release-blocking corpus defect rather than a wrinkle.

---

## 1. The corpus can only be passed through a type-map format this repository forbids for resolution

**Class:** specification-versus-corpus divergence, section 1.1. It affects classes 5, 7, 10, 11,
13, 15 and 19.

Specification section 4.2 states that "the operative matcher is a structured-path DFA over KEY and
INDEX segments, followed by an output selected by observed JSON kind, as defined in
`docs/type-maps.md` section 3", and that it "MUST NOT parse or match a display path, because
section 5.2 makes that representation non-authoritative".
The published artifacts are `type-maps/*.json` under `schemas/type-map-artifact-1.0.json`.

`schemas/type-map-1.0.json` is titled "Superseded draft ROAX display-pattern type map v1" and says
of itself that it "MUST NOT be used to publish or resolve a type map because its display-pattern
and first-match representation conflicts with the structured-path rules in spec sections 4.2 and
5.2".

Every committed vector that needs a type map resolves against `corpus/type-maps/<recordType>.json`,
which is in exactly that superseded format.
There is no published artifact for `org.roax.corpus.synthetic` at all, so no structured-path DFA
can resolve a single corpus record, and no `typeMapVector` carries the `typeMapId`,
`typeMapVersion` or `schemaVersion` that section 4.2 selects a map by.

**Consequence for this implementation.** `src/typemap.ts` defines a `TypeTagResolver` interface and
one implementation of it, `LegacyPatternTypeMap`, over the superseded format, labelled with this
finding at its definition.
No structured-path DFA resolver was written, because the corpus does not exercise one and the task
scopes this build to the surface the corpus covers.

**This is not a defect this implementation can fix.** Closing it means rebuilding the corpus
against `schemas/conformance-corpus-2.0.json`, which requires the exact artifact identity on the
type-map and record vectors, and publishing a synthetic artifact in the operative format.

---

## 2. The empty-container rule of section 3.3 is unsatisfiable against the committed corpus

**Class:** specification-versus-corpus divergence, section 1.1. Measured: exactly 2 vectors of
class 5.

Specification section 3.3 says, in the sentence added to guard decision D7:

> An object output is tag 7 EMPTY_OBJECT and an array output is tag 6 EMPTY_ARRAY, but only when
> the exact selected map authorizes that structured path and observed kind under section 4.2.
> Assigning tags 6 or 7 before map resolution would let an unknown empty issuer extension bypass
> decision D7's fail-closed rule.

`corpus/fixtures/records/structure-empty-array.json` and `structure-empty-object.json` both carry
an empty container at the path `a.b`.
`corpus/type-maps/org.roax.corpus.synthetic.json` declares `a.b` for `jsonKind: "null"` and for
nothing else, and its `a.**` entry is declared for `jsonKind: "string"`.
So under the specification's rule both records **fail closed and have no root at all**, while
`record-structure-empty-array` and `record-structure-empty-object` assert one.

**Measured, by running this implementation both ways.**

| Empty-container policy | Corpus result |
|---|---|
| `mechanical` - tag 6 or 7 from the observed kind, without consulting the map | 617 pass, 0 fail |
| `map-authorized` - specification section 3.3 | 615 pass, **2 fail**, both class 5 |

The two failures are `record-structure-empty-array` and `record-structure-empty-object`, each with
`type-map-fail-closed: no binding in org.roax.corpus.synthetic for kind array|object at a.b`.

**The same gap is visible from the other side.** `docs/conformance-corpus.md` class 11 states that
the fail-closed rows "MUST cover ... an unknown empty array and empty object", and the committed
corpus carries neither.
If it did, that vector and these two record vectors would contradict each other directly.

**How this implementation handles it.** `src/flatten.ts` exposes `EmptyContainerPolicy` with both
readings and documents which is which. The library default is `'map-authorized'`, because the
specification governs; the conformance runner defaults to `'mechanical'`, because that is what
reproduces the committed roots, and `ROAX_EMPTY_CONTAINERS=map-authorized` runs the other way so
the measurement above is reproducible.
The code does not silently pick one.

---

## 3. Specification section 10 step 1 cannot be discharged for `hl7.fhir.bundle` against this corpus

**Class:** specification-versus-corpus divergence, section 1.1. It affects 8 vectors of class 14.

Specification section 10 requires that for each disclosed leaf a verifier "checks a record leaf's
tag against the exact selected map under section 4.2".

`corpus/type-maps/` carries four maps: the synthetic one and the three MOH profiles.
There is **no `hl7.fhir.bundle` map**, and the eight `floor-hl7-fhir-bundle-*` envelope fixtures
disclose a `resourceType` record leaf.
A verifier that hard-requires the tag check therefore rejects all eight, including the two the
corpus expects to accept.

**How this implementation handles it.** `verifyEnvelope` takes an optional resolver per
`recordType`. When one is available the disclosed record leaves' tags are checked against it; when
none is, the verifier records that step 1 was not discharged rather than passing silently. The
runner reports it as a note on class 14.

### Two further gaps in step 1, in the same family and stated for the same reason

Neither is exploitable, because step 2 recomputes the leaf hash from the disclosed tag and a wrong
tag therefore breaks the inclusion proof. Both are recorded because they are the same shape as the
gap above, and because a reader who finds one undocumented will not trust the other.

- **A disclosed INTEGER, DECIMAL or BYTES leaf's tag is not checked against the map.** The map's
  output is selected by OBSERVED JSON KIND, and the mapping from tag back to kind is not one to
  one: kind `number` covers INTEGER and DECIMAL, and kind `string` covers STRING and BYTES. A
  disclosed copy carries the tag and not the observed kind, so the lookup cannot be inverted for
  those tags. `observedKindForTag` in `src/envelope.ts` returns `undefined` for them and the check
  is skipped. Invisible in the corpus, where every disclosed record leaf is tag 2 STRING.
- **The reserved-leaf branch of step 1 is not implemented.** Section 10 step 1 reads "checks a
  record leaf's tag against the exact selected map under section 4.2, **or checks a reserved leaf
  against the fixed table in section 11.2**". This implementation short-circuits both branches for
  a reserved path: `isReservedPath` returns true and no comparison against the six-row table
  happens. The four bound identity leaves are caught one step later by the outer-identity binding,
  and every reserved leaf is a STRING whose tag a wrong value would break the proof over, so this
  is defence in depth rather than a hole - but the table check itself is absent.

`isReservedPath` compares the key RAW, where `assertRecordPathAllowed` compares its NFC form. The
difference is unobservable for today's prefix, for exactly the reason specification section 11.2
states about its own guard: no character normalizes into `roax.`. It is noted rather than
harmonized, because normalizing one side and not the other is worse than either.

---

## 4. Class 9 requires a verification path its own vector shape cannot express

**Class:** internal contradiction in the corpus definition. It affects all 11 class-9 vectors.

`docs/conformance-corpus.md` class 9 states:

> **Consequence for how this class is run.** These vectors MUST be driven through the full
> disclosed-copy verification path, not through a bare fold primitive. A runner that hands
> `verifyInclusion` a leaf hash directly is testing the primitive dogtag documents as proving
> nothing on its own.

`negativeProofVector` in `schemas/conformance-corpus-1.0.json` requires exactly
`name, class, attack, leafHash, index, treeSize, auditPath, root` and forbids everything else.
It carries no `segments`, no `tag`, no `value` and no `salt`, so **there is nothing to recompute a
leaf hash from** and the disclosed-copy path cannot be entered at all.

The requirement is unsatisfiable from the vector shape as committed, not merely unmet.
All 11 vectors do reject under the fold primitive, so the class passes; what it does not do is test
the defence the class says it is about.

Closing it means giving `negativeProofVector` the disclosed-leaf fields, or expressing these
vectors as `envelopeVector` fixtures, and either is a corpus rebuild.

---

## 5. `ROAX-CANON/1` pins Unicode 15.1 and no stock JavaScript runtime provides it

**Class:** implementability finding for this language.

Specification section 6.1 pins Unicode 15.1 and states that an implementation whose NFC tables come
from a different version "MAY produce a different root ... and MUST NOT claim conformance to
`ROAX-CANON/1`".

`String.prototype.normalize` uses the runtime's bundled ICU and exposes no version selector.
Node v22.21.0 bundles ICU 77.1, which is Unicode 16.0.
Satisfying the pin strictly would mean shipping a full NFC implementation with 15.1 tables as
library data, which is a substantial dependency for a property that no committed vector can
currently observe.

**This implementation declares the mismatch rather than claiming the pin.**
`describeUnicodeEnvironment` in `src/bytes.ts` reports the pinned version and the runtime's, and
the conformance runner prints the declaration on every run.
All 20 class-16 vectors and both class-19 assertions pass under 16.0 tables, which agrees with
`corpus/README.md`'s measurement that its Node implementation also agreed on every vector while
running 16.0.
Class 16 is explicit that it detects a version mismatch by declaration rather than by
demonstration, and this is the declaration.

---

## 6. Ambiguities carried forward unchanged, with the reading this implementation took

These were reached independently and agree with the readings `corpus/README.md` already records.
Agreement reached separately is corroboration; it is not a second opinion on whether the
specification is clear, and none of them is settled by a vector.

| # | Ambiguity | Reading taken here | Why |
|---|---|---|---|
| 1 | Does the 1024-digit bound govern INTEGER as well as DECIMAL? Section 6.2 states it under *Canonical decimal* and its own justification counts "class 2's 40-digit integer" against it. | Applied to both. | An unbounded INTEGER is an unbounded allocation on hostile input. No vector discriminates. |
| 2 | What does the bound count - the padded form, or the form after output-grammar normalization? | The padded form, BEFORE normalization. | The literal reading, and the memory-safe one. Under it `0e99999` is rejected; under the other it canonicalizes to `0`. No vector carries `0e99999`. Pinned at the edge by `1e1023` accepted and `1e1024` rejected. |
| 3 | Does type-map LOOKUP match over an NFC-normalized key or over the bytes as received? This is decision D14 and it is OPEN. | Raw, with no `nfc()` on either side. | Adding one would rule D14 silently. The synthetic map carries the Kelvin key under both spellings so nothing depends on the answer. |
| 4 | The type-map `pattern` field is display notation, so it cannot address a key containing `.`, `[` or `]` - keys section 5 deliberately admits. | An ambiguous pattern is REJECTED at map-compile time rather than guessed at. | A guess binds the wrong path silently. |

One reading was taken that the corpus does not record: **`**` stands for one or more remaining
segments rather than zero or more.** It is unexercised - `a.**` is the only instance in any
committed map and no record or type-map vector reaches it - so nothing pins it either way.

---

## 7. Section 3.3's zero-leaf rejection is unreachable under the flatten it is stated beside

**Class:** an internal redundancy in the specification, found by writing a test for the rule.
Harmless, and worth recording because a reader will otherwise look for the case it guards.

Specification section 3.3 states:

> A record that contributes zero leaves of its own MUST be rejected at issuance rather than
> anchored.

No record can contribute zero leaves under the `flatten` stated four paragraphs above it.
An empty map emits a leaf at the empty path, an empty array emits one, a non-empty container
recurses to at least one scalar, and a scalar emits itself.
So `{}` is a ONE-leaf record whose leaf sits at `encodePath([]) = 00000000`, not an empty one, and
the tree floor of 6 that the same paragraph derives is reached by every record rather than
approached by some.

This is the same shape as `MTH([])`, which section 9.1 keeps only so the function is total and says
outright is unreachable.
The difference is that section 9.1 says so and section 3.3 does not, so the zero-leaf sentence
reads as a guard against a reachable state.
`leafSet` in `src/flatten.ts` keeps the check on the same footing the specification gives
`MTH([])`, and `test/unit.ts` pins the `{}` behaviour so nobody later "fixes" it into a rejection.

---

## 8. Two rules the specification states that no committed vector exercises

Recorded so a passing run does not read as coverage it does not have.

- **Tag 8 `BLOB_REF` map rejection.** Specification section 6.5 requires an implementation to
  reject a type map binding any path to tag 8, and `docs/conformance-corpus.md` class 11 mandates
  a row for it. No committed `typeMapVector` carries `expectMapRejected`, so the `oneOf` branch
  that exists for it is unreached. This implementation performs the rejection at map-compile time
  and it is covered by a unit test rather than by a vector.
- **The full-copy `leafCount` disagreement rule.** Specification section 11.1 requires that in a
  full copy "a derived count that disagrees with the `leafCount` field MUST be a rejection". The
  nearest committed vector, `full-copy-salts-length-not-leaf-count`, is caught one step earlier by
  the salts-length rule of class 17, so the derived-count comparison itself is unexercised. It is
  implemented and unit-tested.
- **The base64 rules of section 6.3.** RFC 4648 section 4 with padding, no line wrapping, and a
  final quantum whose unused bits are zero. No version-1 profile binds `BYTES`, so no vector
  reaches `decodeBase64Strict`. It is implemented and unit-tested, including the non-canonical
  final quantum that RFC 4648 section 3.5 identifies.

---

## 9. What was measured

Node v22.21.0, TypeScript 5.9.3, `SHA-256`, corpus `1.0.0`.

**Both corpus numbers are given, because the higher one is not reproducible on a bare checkout.**

| Run | Result |
|---|---|
| `npm test`, the default | **680 assertions, 0 failures, 2 SKIPPED** - class 10, whose records live outside this repository |
| `ROAX_REFERENCE_RECORDS=<dir> npm run conformance` | **684 assertions, 0 failures, 0 skipped**, all 19 classes |
| `test/unit.ts` | **21 tests, 0 failures** |

**Both were run under `emptyContainerPolicy: 'mechanical'`, which is the corpus's rule and NOT
specification section 3.3's.** Finding 2 above gives the measurement in full: under section 3.3 the
same run is 615 passed and 2 failed. A green corpus is therefore evidence of agreement with the
committed vectors and is not, on its own, evidence of conformance to section 3.3 - the two are
mutually exclusive as things stand.

Class 10 - the two real Singapore MOH recovery-healthcert vectors at 69 and 70 leaves - passes
against a record extracted from a reference checkout outside this repository with
`corpus/tools/extract_reference_record.py`, which is a data-extraction utility and not one of the
two reference implementations. Nothing from that checkout is committed.
Without `ROAX_REFERENCE_RECORDS` the class reports 2 skipped and is never reported green unrun.

Both gates fail loudly on a regression, which was verified rather than assumed: restoring dogtag's
trailing-zero strip to `canonicalizeDecimal` makes `npm test` exit 1, with 16 class-1 failures in
the corpus and the `0.010` unit test failing first.

The roots this implementation produces are byte-identical to the committed ones on every vector
that carries a root, including both MOH ones.
