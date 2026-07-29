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

- **Tag 8 `BLOB_REF`, and it is TWO rejections rather than one.** Specification section 6.5 reads:
  "An implementation MUST reject a record whose type map binds any path to tag 8, and MUST reject
  an envelope carrying a tag-8 leaf."
  `docs/conformance-corpus.md` class 11 mandates a row for the first half.
  No committed `typeMapVector` carries `expectMapRejected` and no committed envelope fixture
  carries a tag-8 leaf, so neither half is reached by a vector.
  The record half is unit-tested; **the envelope half is currently asserted by neither a vector nor
  a unit test**, and is recorded here rather than left to read as covered.
  The two need separate code, which is the part that is easy to miss: the record half also covers
  a FULL copy transitively, because re-flattening one reaches `carrierFromJson`, but a disclosed
  copy is never re-flattened.
  Its leaves are taken as given, so a tag-8 leaf would pass the named-without-value check, skip the
  map check - `observedKindForTag` returns nothing for tag 8, since the tag implies no observed
  JSON kind - reach `encodeValue`, and verify against the root.
  The rejection is therefore the first check in the per-leaf loop of `verifyDisclosedCopy`, ahead
  of the named-without-value check, so that a tag-8 leaf carrying no value still reports
  `blob-ref-not-selectable` rather than a reason naming a different defect.
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

## 9. The envelope carries no schema-version discriminator, so one binding is waivable by deletion

**Closed in code as far as the envelope shape allows, with a residue that cannot be closed there.**

Specification section 11.2 marks `roax.typeMap.id` mandatory to disclose and says that withholding
a mandatory reserved leaf "does not produce a weaker proof; it produces no proof".
`schemas/envelope-2.0.json` makes the outer `typeMap` member required for the same reason.
The verifier in `src/envelope.ts` originally took the MEMBERSHIP of that binding, and with it the
reserved half of the minimum-disclosure floor, from the outer `typeMap` member alone.

That was an asymmetry inside one function rather than a missing feature.
The same function selects the floor TABLE from the COMMITTED `roax.recordType` leaf specifically so
that no outer field selects anything before it has been authenticated, and then let an outer field
decide whether a binding applied at all.
The sequence it admitted: a holder of an envelope-2.0 disclosed copy deletes the top-level
`typeMap` member and withholds the `roax.typeMap.id` leaf.
Nothing then binds it, `mandatoryReservedPaths` omits it from the floor, and the copy verifies.

**What this was not.** It was not forgeable against a genuine root.
The resolved tag is inside the leaf preimage, so a copy verified under the wrong map fails rather
than passing - the exposure was that a stated MUST became waivable by editing an unauthenticated
field, not that a wrong answer could be produced.

**What is now closed.** The identity is decided from the committed side in both directions.
An outer `typeMap.id` with no committed leaf is `outer-identity-mismatch`, as before.
A committed `roax.typeMap.id` leaf with no outer member is now `outer-identity-mismatch` too,
which is the half that was missing.
Because those two directions settle the member against the root, the reserved half of the floor is
now selected from an authenticated fact rather than from a hint.

**The residue, stated at the strength of the evidence.** The remaining case is both halves absent
at once, and it cannot be separated from a conforming `schemas/envelope-1.0.json` copy, which
predates the binding and is legitimately verifiable.
The envelope shape of specification section 11.1 carries no discriminator for which envelope schema
version a document was issued under.
This was checked rather than assumed: `canon` is `const: "ROAX-CANON/1"` in
`schemas/envelope-1.0.json` and in `schemas/envelope-2.0.json` alike, and the outer `schemaVersion`
is the RECORD profile's version, which `schemas/envelope-2.0.json` describes as opaque to the
protocol.

So the residue is reported rather than waived.
A disclosed copy carrying neither half adds an `undischarged` entry naming both readings, on every
such verification, which is the same treatment findings 3 and 5 give their gaps.
A deployment that issues and accepts only envelope-2.0 documents closes it outright by setting
`requireTypeMapIdentity` on its verifier configuration.
That knob defaults to permissive, and the default is a statement about envelope-1.0 rather than
about the binding: failing closed by default would reject conforming documents rather than forged
ones, and `src/envelope.ts` reads both schema versions deliberately.

**A FULL copy with no `typeMap` member reports too, and it is a different statement.**
The option is read beside the verifier's other allow-lists rather than inside either copy-kind
path, so a deployment that sets it refuses both kinds; scoping it to disclosed copies alone would
have told that deployment it had opted out of `schemas/envelope-1.0.json` while it was still
accepting one.
What the two reports say differs, because what is at stake differs.
A full copy is re-flattened, and the rebuild takes the reserved leaves from the identity, so
removing the member removes a leaf with it.
Measured on a copy this library issued, that fails with `leaf-count-mismatch`, because the derived
count is checked before the root is; editing `leafCount` to match moves the rejection to
`salts-length-not-leaf-count`, and dropping the corresponding salt entry moves it to
`root-mismatch`.
Which of the three fires depends on what else the edit changed, and all three are rejections.
Nothing there is waivable by deletion, and the entry says so: what is undischarged is that the
document binds no type-map artifact at all, not that one may have been removed.
The stripped-versus-envelope-1.0 ambiguity is specific to a disclosed copy, which is never
re-flattened.

All 54 committed envelope fixtures carry no `typeMap` member and no `roax.typeMap.id` leaf, so what
the corpus exercises today is the residue rather than either closed direction, and **neither closed
direction is asserted by a vector.**
The round trip through `issueFullCopy` and `discloseFrom` in `test/unit.ts` does commit and
disclose the leaf, so the both-present direction is exercised there incidentally; the leaf-without-
member direction is not exercised anywhere and is recorded here for that reason.
Closing the corpus difference is corpus-rebuild work: class 14 now defines five reserved paths
where the committed fixtures carry four.

---

## 10. What was measured

Node v22.21.0, TypeScript 5.9.3, `SHA-256`, corpus `1.0.0`.

**Both corpus numbers are given, because the higher one is not reproducible on a bare checkout.**

| Run | Result |
|---|---|
| `npm test`, the default | **680 assertions, 0 failures, 2 SKIPPED** - class 10, whose records live outside this repository |
| `ROAX_REFERENCE_RECORDS=<dir> npm run conformance` | **684 assertions, 0 failures, 0 skipped**, all 19 classes |
| `test/unit.ts` | **22 tests, 0 failures** |

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
