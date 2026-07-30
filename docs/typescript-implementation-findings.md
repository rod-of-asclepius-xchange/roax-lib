# Findings from the independent TypeScript implementation

This document records every place where the TypeScript implementation under `src/` disagreed with the conformance corpus, or where the specification admitted two honest readings.

It is written from the build of `ROAX-CANON/1` in TypeScript, done from [`docs/spec/roax-canon-1.md`](spec/roax-canon-1.md) alone.
`corpus/tools/roax_ref.py` and `corpus/tools/roax_ref.mjs` were deliberately not read while implementing, and neither was `corpus/tools/check_corpus.mjs`, which imports one of them.
The value of a third implementation is that it agrees without having read either, so the corpus was run only after each module was written.

Specification section 1.1 governs how these are classified: the specification is normative for meaning and the corpus is the executable arbiter, so where the two diverge the specification governs and the divergence is a release-blocking corpus defect rather than a wrinkle.

---

## 1. The corpus can only be passed through a type-map format this repository forbids for resolution

**Class:** specification-versus-corpus divergence, section 1.1.
It affects classes 5, 7, 10, 11, 13, 15 and 19.

Specification section 4.2 states that "the operative matcher is a structured-path DFA over KEY and INDEX segments, followed by an output selected by observed JSON kind, as defined in `docs/type-maps.md` section 3", and that it "MUST NOT parse or match a display path, because section 5.2 makes that representation non-authoritative".
The published artifacts are `type-maps/*.json` under `schemas/type-map-artifact-1.0.json`.

`schemas/type-map-1.0.json` is titled "Superseded draft ROAX display-pattern type map v1" and says of itself that it "MUST NOT be used to publish or resolve a type map because its display-pattern and first-match representation conflicts with the structured-path rules in spec sections 4.2 and 5.2".

Every committed vector that needs a type map resolves against `corpus/type-maps/<recordType>.json`, which is in exactly that superseded format.
There is no published artifact for `org.roax.corpus.synthetic` at all, so no structured-path DFA can resolve a single corpus record, and no `typeMapVector` carries the `typeMapId`, `typeMapVersion` or `schemaVersion` that section 4.2 selects a map by.

**Consequence for this implementation.**
`src/typemap.ts` defines a `TypeTagResolver` interface and one implementation of it, `LegacyPatternTypeMap`, over the superseded format, labelled with this finding at its definition.
No structured-path DFA resolver was written, because the corpus does not exercise one and the task scopes this build to the surface the corpus covers.

**This is not a defect this implementation can fix.**
Closing it means rebuilding the corpus against `schemas/conformance-corpus-2.0.json`, which requires the exact artifact identity on the type-map and record vectors, and publishing a synthetic artifact in the operative format.

---

## 2. The empty-container rule of section 3.3 is unsatisfiable against the committed corpus

**Class:** specification-versus-corpus divergence, section 1.1.
Measured: exactly 2 vectors of class 5.

Specification section 3.3 says, in the sentence added to guard decision D7:

> An object output is tag 7 EMPTY_OBJECT and an array output is tag 6 EMPTY_ARRAY, but only when the exact selected map authorizes that structured path and observed kind under section 4.2.
> Assigning tags 6 or 7 before map resolution would let an unknown empty issuer extension bypass decision D7's fail-closed rule.

`corpus/fixtures/records/structure-empty-array.json` and `structure-empty-object.json` both carry an empty container at the path `a.b`.
`corpus/type-maps/org.roax.corpus.synthetic.json` declares `a.b` for `jsonKind: "null"` and for nothing else, and its `a.**` entry is declared for `jsonKind: "string"`.
So under the specification's rule both records **fail closed and have no root at all**, while `record-structure-empty-array` and `record-structure-empty-object` assert one.

**Measured, by running this implementation both ways on a bare checkout**, where class 10 reports 2 skipped because its records live outside this repository.
The `mechanical` row is the `npm test` default that section 10 below reports; neither row was run against a reference checkout, so no `map-authorized` count with those records is claimed here.

| Empty-container policy | Corpus result |
|---|---|
| `mechanical` - tag 6 or 7 from the observed kind, without consulting the map | 680 pass, 0 fail, 2 skipped |
| `map-authorized` - specification section 3.3 | 676 pass, **2 fail**, both class 5, 2 skipped |

The two rows differ by four assertions where only two vectors flip, which is not a third failure hiding somewhere: a record vector asserts `leafCount` and `root` separately, and a throw out of `commitRecord` emits one failure in place of both passes (`conformance/run.ts:525-528`).

The two failures are `record-structure-empty-array` and `record-structure-empty-object`, each with `type-map-fail-closed: no binding in org.roax.corpus.synthetic for kind array|object at a.b`.

**The same gap is visible from the other side.**
`docs/conformance-corpus.md` class 11 states that the fail-closed rows "MUST cover ... an unknown empty array and empty object", and the committed corpus carries neither.
If it did, that vector and these two record vectors would contradict each other directly.

**How this implementation handles it.**
`src/flatten.ts` exposes `EmptyContainerPolicy` with both readings and documents which is which.
The library default is `'map-authorized'`, because the specification governs; the conformance runner defaults to `'mechanical'`, because that is what reproduces the committed roots, and `ROAX_EMPTY_CONTAINERS=map-authorized` runs the other way so the measurement above is reproducible.
The code does not silently pick one.

---

## 3. Specification section 10 step 1 cannot be discharged for `hl7.fhir.bundle` against this corpus

**Class:** specification-versus-corpus divergence, section 1.1.
Measured: 7 vectors of class 14, of which 6 disclose the record leaf whose tag cannot be checked.

Specification section 10 requires that for each disclosed leaf a verifier "checks a record leaf's tag against the exact selected map under section 4.2".

`corpus/type-maps/` carries four maps: the synthetic one and the three MOH profiles.
There is **no `hl7.fhir.bundle` map**, and 6 of the 7 committed `floor-hl7-fhir-bundle-*` envelope fixtures disclose a `resourceType` record leaf.
A verifier that hard-requires the tag check therefore rejects those 6 with `type-map-fail-closed`, including the two the corpus expects to accept.
The seventh, `floor-hl7-fhir-bundle-omits-resourceType`, discloses no record leaf at all, so the check never fires and it is rejected on `minimum-disclosure-floor` whether the requirement is on or off.

**7 is the count against the committed corpus and 8 is the count against the class definition**, so a reader comparing the two is not looking at a miscount.
Class 14 defines the floor as five reserved paths plus the profile's, the committed fixtures carry four, and the missing `roax.typeMap.id` omission fixture is the eighth.
Section 9 below records the same difference from the other side, and closing it is corpus-rebuild work.

**How this implementation handles it.**
`verifyEnvelope` takes an optional resolver per `recordType`.
When one is available the disclosed record leaves' tags are checked against it; when none is, the verifier records that step 1 was not discharged rather than passing silently.
The runner reports it as a note on class 14.

### One further gap in step 1, and one that was reported here and has since been closed

Neither was exploitable, because step 2 recomputes the leaf hash from the disclosed tag and a wrong tag therefore breaks the inclusion proof.
Both are recorded because they are the same shape as the gap above, and because a reader who finds one undocumented will not trust the other.

- **CLOSED: a disclosed INTEGER, DECIMAL or BYTES leaf's tag is now checked against the map.**
  This was reported as a gap on the reasoning that the map's output is selected by OBSERVED JSON KIND and that the mapping from tag back to kind is not one to one, kind `number` covering INTEGER and DECIMAL and kind `string` covering STRING and BYTES.
  That reasoning was wrong on its own terms, and visibly so: tag 2 STRING was checked through exactly the kind said to be ambiguous.
  The direction the check needs is tag to KIND, which is total, and it is the direction `carrierFromJson` in `src/value.ts` already fixes at issuance.
  Given a kind the map yields exactly one tag, so the leaf's own tag names the kind to look its path up under and the single tag that comes back either equals it or contradicts it.
  The cost of the earlier reading was one-sided: a leaf mis-issued as BYTES at a path bound to STRING for kind `string` was accepted, while the same mistake the other way round was caught.
  `observedKindForTag` in `src/envelope.ts` is now total over every tag a record leaf can carry and returns `undefined` for tag 8 BLOB_REF alone, which implies no observed JSON kind; the caller fails closed on that rather than skipping, and tag 8 is already rejected as the first check in the same loop.
  Invisible in the corpus either way: all 318 disclosed leaves across its 54 envelope fixtures are tag 2 STRING, so `test/unit.ts` is the only coverage and carries one retag in each direction.
- **The reserved-leaf branch of step 1 is not implemented.**
  Section 10 step 1 reads "checks a record leaf's tag against the exact selected map under section 4.2, **or checks a reserved leaf against the fixed table in section 11.2**".
  This implementation short-circuits both branches for a reserved path: `isReservedPath` returns true and no comparison against the six-row table happens.
  The four bound identity leaves are caught one step later by the outer-identity binding, and every reserved leaf is a STRING whose tag a wrong value would break the proof over, so this is defence in depth rather than a hole - but the table check itself is absent.

`isReservedPath` compares the key RAW, where `assertRecordPathAllowed` compares its NFC form.
The difference is unobservable for today's prefix, for exactly the reason specification section 11.2 states about its own guard: no character normalizes into `roax.`.
It is noted rather than harmonized, because normalizing one side and not the other is worse than either.

---

## 4. Class 9 requires a verification path its own vector shape cannot express

**Class:** internal contradiction in the corpus definition.
It affects all 11 class-9 vectors.

`docs/conformance-corpus.md` class 9 states:

> **Consequence for how this class is run.**
> These vectors MUST be driven through the full disclosed-copy verification path, not through a bare fold primitive.
> A runner that hands `verifyInclusion` a leaf hash directly is testing the primitive dogtag documents as proving nothing on its own.

`negativeProofVector` in `schemas/conformance-corpus-1.0.json` requires exactly `name, class, attack, leafHash, index, treeSize, auditPath, root` and forbids everything else.
It carries no `segments`, no `tag`, no `value` and no `salt`, so **there is nothing to recompute a leaf hash from** and the disclosed-copy path cannot be entered at all.

The requirement is unsatisfiable from the vector shape as committed, not merely unmet.
All 11 vectors do reject under the fold primitive, so the class passes; what it does not do is test the defence the class says it is about.

Closing it means giving `negativeProofVector` the disclosed-leaf fields, or expressing these vectors as `envelopeVector` fixtures, and either is a corpus rebuild.

---

## 5. `ROAX-CANON/1` pins Unicode 15.1 and no stock JavaScript runtime provides it

**Class:** implementability finding for this language.

Specification section 6.1 pins Unicode 15.1 and states that an implementation whose NFC tables come from a different version "MAY produce a different root ... and MUST NOT claim conformance to `ROAX-CANON/1`".

`String.prototype.normalize` uses the runtime's bundled ICU and exposes no version selector.
Node v22.21.0 bundles ICU 77.1, which is Unicode 16.0.
Satisfying the pin strictly would mean shipping a full NFC implementation with 15.1 tables as library data, which is a substantial dependency for a property that no committed vector can currently observe.

**This implementation declares the mismatch rather than claiming the pin.**
`describeUnicodeEnvironment` in `src/bytes.ts` reports the pinned version and the runtime's, and the conformance runner prints the declaration on every run.
All 20 class-16 vectors and both class-19 assertions pass under 16.0 tables, which agrees with `corpus/README.md`'s measurement that its Node implementation also agreed on every vector while running 16.0.
Class 16 is explicit that it detects a version mismatch by declaration rather than by demonstration, and this is the declaration.

---

## 6. Ambiguities carried forward unchanged, with the reading this implementation took

These were reached independently and agree with the readings `corpus/README.md` already records.
Agreement reached separately is corroboration; it is not a second opinion on whether the specification is clear, and none of them is settled by a vector.

| # | Ambiguity | Reading taken here | Why |
|---|---|---|---|
| 1 | Does the 1024-digit bound govern INTEGER as well as DECIMAL? Section 6.2 states it under *Canonical decimal* and its own justification counts "class 2's 40-digit integer" against it. | Applied to both. | An unbounded INTEGER is an unbounded allocation on hostile input. No vector discriminates. |
| 2 | What does the bound count - the padded form, or the form after output-grammar normalization? | The padded form, BEFORE normalization. | The literal reading, and the memory-safe one. Under it `0e99999` is rejected; under the other it canonicalizes to `0`. No vector carries `0e99999`. Pinned at the edge by `1e1023` accepted and `1e1024` rejected. |
| 3 | Does type-map LOOKUP match over an NFC-normalized key or over the bytes as received? This is decision D14 and it is OPEN. | Raw, with no `nfc()` on either side. | Adding one would rule D14 silently. The synthetic map carries the Kelvin key under both spellings so nothing depends on the answer. |
| 4 | The type-map `pattern` field is display notation, so it cannot address a key containing `.`, `[` or `]` - keys section 5 deliberately admits. | An ambiguous pattern is REJECTED at map-compile time rather than guessed at. | A guess binds the wrong path silently. |

One reading was taken that the corpus does not record: **`**` stands for one or more remaining segments rather than zero or more.**
It is unexercised - `a.**` is the only instance in any committed map and no record or type-map vector reaches it - so nothing pins it either way.

---

## 7. Section 3.3's zero-leaf rejection is unreachable under the flatten it is stated beside

**Class:** an internal redundancy in the specification, found by writing a test for the rule.
Harmless, and worth recording because a reader will otherwise look for the case it guards.

Specification section 3.3 states:

> A record that contributes zero leaves of its own MUST be rejected at issuance rather than anchored.

No record can contribute zero leaves under the `flatten` stated four paragraphs above it.
An empty map emits a leaf at the empty path, an empty array emits one, a non-empty container recurses to at least one scalar, and a scalar emits itself.
So `{}` is a ONE-leaf record whose leaf sits at `encodePath([]) = 00000000`, not an empty one, and the tree floor of 6 that the same paragraph derives is reached by every record rather than approached by some.

This is the same shape as `MTH([])`, which section 9.1 keeps only so the function is total and says outright is unreachable.
The difference is that section 9.1 says so and section 3.3 does not, so the zero-leaf sentence reads as a guard against a reachable state.
`leafSet` in `src/flatten.ts` keeps the check on the same footing the specification gives `MTH([])`, and `test/unit.ts` pins the `{}` behaviour so nobody later "fixes" it into a rejection.

---

## 8. Two rules the specification states that no committed vector exercises

Recorded so a passing run does not read as coverage it does not have.

- **Tag 8 `BLOB_REF`, and it is TWO rejections rather than one.**
  Specification section 6.5 reads: "An implementation MUST reject a record whose type map binds any path to tag 8, and MUST reject an envelope carrying a tag-8 leaf."
  `docs/conformance-corpus.md` class 11 mandates a row for the first half.
  No committed `typeMapVector` carries `expectMapRejected` and no committed envelope fixture carries a tag-8 leaf, so neither half is reached by a vector.
  **Both halves are unit-tested**, and the envelope half takes two tests rather than one: that a tag-8 leaf is refused both with a resolver available and without one, and that a tag-8 leaf carrying NO value still reports `blob-ref-not-selectable`.
  What the guard is worth was measured by deleting it, across both verifier configurations and all three value shapes a tag-8 leaf can carry, rather than reasoned about.
  Without it a verifier holding a map still fails closed on `blob-ref-not-selectable` for a string and for a BLOB_REF-shaped value, through the uninvertible-tag branch described below, and reports `disclosed-leaf-named-without-value` for a valueless leaf.
  A verifier holding no map reports `value-type-mismatch` for a string, the same `disclosed-leaf-named-without-value` for a valueless leaf, and for a BLOB_REF-shaped value reaches the inclusion proof with nothing before it having objected.
  That last one is the case the paragraph below describes: it failed on `inclusion-proof-failed` only because the root under test does not commit such a leaf, which is a property of the fixture rather than a rule being enforced.
  The two need separate code, which is the part that is easy to miss: the record half also covers a FULL copy transitively, because re-flattening one reaches `carrierFromJson`, but a disclosed copy is never re-flattened.
  Its leaves are taken as given, so a tag-8 leaf would pass the named-without-value check, reach `encodeValue`, and verify against the root.
  The map check does not stop it either, and would not even for a verifier holding a map: `observedKindForTag` returns nothing for tag 8, since the tag implies no observed JSON kind, so there is no kind to look the path up under.
  The rejection is therefore the first check in the per-leaf loop of `verifyDisclosedCopy`, ahead of the named-without-value check, so that a tag-8 leaf carrying no value still reports `blob-ref-not-selectable` rather than a reason naming a different defect.
  The map check's own uninvertible-tag branch fails closed with the same code, which makes it a second line rather than the line: it is reached only when a resolver is available, and a verifier with none would otherwise pass the leaf straight to `encodeValue`.
- **The full-copy `leafCount` disagreement rule.**
  Specification section 11.1 requires that in a full copy "a derived count that disagrees with the `leafCount` field MUST be a rejection".
  The nearest committed vector, `full-copy-salts-length-not-leaf-count`, is caught one step earlier by the salts-length rule of class 17, so the derived-count comparison itself is unexercised.
  It is implemented and unit-tested.
- **The base64 rules of section 6.3.**
  RFC 4648 section 4 with padding, no line wrapping, and a final quantum whose unused bits are zero.
  No version-1 profile binds `BYTES`, so no vector reaches `decodeBase64Strict`.
  It is implemented and unit-tested, including the non-canonical final quantum that RFC 4648 section 3.5 identifies.
- **The `BYTES` carrier form, which is hex and not the record's base64.**
  The two are different spellings of the same bytes and the code had them confused: `carrierFromJson` kept the base64 and `encodeValue` decoded it, so a disclosed tag-5 leaf was emitted as `AAECAw==` where both envelope schemas require `^([0-9a-f]{2})*$` (`schemas/envelope-1.0.json:259-264`, `schemas/envelope-2.0.json:260-265`).
  That copy verified against its own root while being schema-invalid, and a schema-valid hex carrier was rejected or decoded as different bytes - the failure was symmetric and silent.
  Base64 is now decoded once, at record projection in `carrierFromJson`, and `encodeValue` reads strict lowercase even-length hex through `fromHex`.
  **No committed vector moved, because no vector carries a tag-5 value at all**: the conformance total is unchanged at 680 passed, 0 failed, 2 NOT RUN, which is the measurement that shows the committed bytes and roots were preserved.
  That covers the two class-10 vectors this run could not execute as well, and by argument rather than by measurement: no map in `corpus/type-maps/` binds any path to tag 5, so the recovery record cannot reach the changed code at all.
  **The independent Rust library already reads it this way**, which is the strongest evidence available that the specification says one thing here and that the TypeScript side was the outlier: `rust/src/value.rs:54` decodes canonical base64 at record projection, `:157-158` requires an envelope carrier to be hex that survives a re-encode round trip, so uppercase is refused there too, and `:180` emits `hex::encode` into a disclosed leaf.
  **Because no published map selects `BYTES`, synthetic coverage is the only coverage possible** and is therefore required rather than optional - nothing in `type-maps/`, `corpus/type-maps/` or the corpus reaches the path.
  `test/unit.ts` carries the base64-to-hex projection with its non-canonical rejections, strict hex decoding including the uppercase, odd-length and non-hex cases, an issue-disclose-parse-verify round trip under a synthetic tag-5 map that emits `00010203`, empty bytes carried the whole way as `""`, and a check of the emitted carrier against the tag-5 pattern read out of both live envelope schema files rather than restated in the test.
  **One value in that round trip is letter-bearing on purpose**, `q83v` emitting `abcdef`, because `00010203` and `""` are unchanged by `toUpperCase` and so satisfy every other assertion here even if `toHex` emits uppercase nibbles - which the case-sensitive schema pattern would then reject.
  Measured rather than reasoned about: uppercasing the carrier in `carrierFromJson` fails exactly those two tests, 34 passed and 2 failed, both on `envelope-malformed: a BYTES value is not lowercase hex of even length`.
  That the same mutation left the suite green BEFORE this value was added to the fixture is the measurement recorded in the commit that added it, not one re-run here.

---

## 9. The envelope carries no schema-version discriminator, so one binding is waivable by deletion

**Closed in code as far as the envelope shape allows, with a residue that cannot be closed there.**

Specification section 11.2 marks `roax.typeMap.id` mandatory to disclose and says that withholding a mandatory reserved leaf "does not produce a weaker proof; it produces no proof".
`schemas/envelope-2.0.json` makes the outer `typeMap` member required for the same reason.
The verifier in `src/envelope.ts` originally took the MEMBERSHIP of that binding, and with it the reserved half of the minimum-disclosure floor, from the outer `typeMap` member alone.

That was an asymmetry inside one function rather than a missing feature.
The same function selects the floor TABLE from the COMMITTED `roax.recordType` leaf specifically so that no outer field selects anything before it has been authenticated, and then let an outer field decide whether a binding applied at all.
The sequence it admitted: a holder of an envelope-2.0 disclosed copy deletes the top-level `typeMap` member and withholds the `roax.typeMap.id` leaf.
Nothing then binds it, `mandatoryReservedPaths` omits it from the floor, and the copy verifies.

**What this was not.**
It was not forgeable against a genuine root.
The resolved tag is inside the leaf preimage, so a copy verified under the wrong map fails rather than passing - the exposure was that a stated MUST became waivable by editing an unauthenticated field, not that a wrong answer could be produced.

**What is now closed.**
The identity is decided from the committed side in both directions.
An outer `typeMap.id` with no committed leaf is `outer-identity-mismatch`, as before.
A committed `roax.typeMap.id` leaf with no outer member is now `outer-identity-mismatch` too, which is the half that was missing.
Because those two directions settle the member against the root, the reserved half of the floor is now selected from an authenticated fact rather than from a hint.

**The residue, stated at the strength of the evidence.**
The remaining case is both halves absent at once, and it cannot be separated from a conforming `schemas/envelope-1.0.json` copy, which predates the binding and is legitimately verifiable.
The envelope shape of specification section 11.1 carries no discriminator for which envelope schema version a document was issued under.
This was checked rather than assumed: `canon` is `const: "ROAX-CANON/1"` in `schemas/envelope-1.0.json` and in `schemas/envelope-2.0.json` alike, and the outer `schemaVersion` is the RECORD profile's version, which `schemas/envelope-2.0.json` describes as opaque to the protocol.

So the residue is reported rather than waived.
A disclosed copy carrying neither half adds an `undischarged` entry naming both readings, on every such verification, which is the same treatment findings 3 and 5 give their gaps.
A deployment that issues and accepts only envelope-2.0 documents closes it outright by setting `requireTypeMapIdentity` on its verifier configuration.
That knob defaults to permissive, and the default is a statement about envelope-1.0 rather than about the binding: failing closed by default would reject conforming documents rather than forged ones, and `src/envelope.ts` reads both schema versions deliberately.

**A FULL copy with no `typeMap` member reports too, and it is a different statement.**
The option is read beside the verifier's other allow-lists rather than inside either copy-kind path, so a deployment that sets it refuses both kinds; scoping it to disclosed copies alone would have told that deployment it had opted out of `schemas/envelope-1.0.json` while it was still accepting one.
What the two reports say differs, because what is at stake differs.
A full copy is re-flattened, and the rebuild takes the reserved leaves from the identity, so removing the member removes a leaf with it.
Measured on a copy this library issued, that fails with `leaf-count-mismatch`, because the derived count is checked before the root is; editing `leafCount` to match moves the rejection to `salts-length-not-leaf-count`, and dropping the corresponding salt entry moves it to `root-mismatch`.
Which of the three fires depends on what else the edit changed, and all three are rejections.
Nothing there is waivable by deletion, and the entry says so: what is undischarged is that the document binds no type-map artifact at all, not that one may have been removed.
The stripped-versus-envelope-1.0 ambiguity is specific to a disclosed copy, which is never re-flattened.

All 54 committed envelope fixtures carry no `typeMap` member and no `roax.typeMap.id` leaf, so what the corpus exercises today is the residue rather than either closed direction, and **neither closed direction is asserted by a vector.**
The round trip through `issueFullCopy` and `discloseFrom` in `test/unit.ts` does commit and disclose the leaf, so the both-present direction is exercised there incidentally; the leaf-without- member direction is not exercised anywhere and is recorded here for that reason.
Closing the corpus difference is corpus-rebuild work: class 14 now defines five reserved paths where the committed fixtures carry four.

---

## 10. What was measured

Node v22.21.0, TypeScript 5.9.3, `SHA-256`, corpus `1.0.0`.

**Every number in this table was re-measured on the commit that carries it.**
Nothing here is carried forward from an earlier run.

| Run | Result |
|---|---|
| `npm test`, the default | **680 assertions, 0 failures, 2 NOT RUN** - class 10, whose records live outside this repository |
| `ROAX_EMPTY_CONTAINERS=map-authorized`, the section 3.3 reading | **676 passed, 2 failed, 2 NOT RUN**, exit 1 |
| `test/unit.ts` | **36 tests, 0 failures** |

The runner's total line spells the third column `skipped` while the per-vector note for each of those 2 assertions reads `NOT RUN` and names its reason; they are the same 2 assertions, and neither spelling adds them to the passed count.

**The corpus runs were made under `emptyContainerPolicy: 'mechanical'`, which is the corpus's rule and NOT specification section 3.3's.**
Finding 2 above gives that measurement in full, and the second row is it: the two failures are `record-structure-empty-array` and `record-structure-empty-object`, both on `type-map-fail-closed: no binding in org.roax.corpus.synthetic for kind array|object at a.b`.
A green corpus is therefore evidence of agreement with the committed vectors and is not, on its own, evidence of conformance to section 3.3 - the two are mutually exclusive as things stand.
The runner DECLARES the active policy on every run, beside the Unicode declaration and for the same reason: a total line read on its own must not stand for a conformance claim the run did not make.

### Class 10 is NOT RUN here, and 684/0/0 is not claimed

**Class 10 did not execute in any run recorded above, and its 2 assertions are counted as NOT RUN rather than as passed.**
An earlier revision of this section carried a second corpus row - `ROAX_REFERENCE_RECORDS=<dir> npm run conformance` giving 684 assertions, 0 failures, 0 skipped across all 19 classes - and that row has been removed rather than restated, because it was not reproducible on this machine and a measurement that cannot be reproduced must not sit in a table of measurements as though it were current.

The class needs a record this repository deliberately does not vendor.
Its two vectors, the real Singapore MOH recovery-healthcert records at 69 and 70 leaves, resolve against `references/schemata/src/sg/gov/moh/recovery-healthcert/2.0/sample-data.ts#sampleDocument`, which lives in a third-party checkout that `.gitignore` excludes and that no part of this repository may copy in.
To run it:

1. Extract the record with `corpus/tools/extract_reference_record.py --out <dir>/sg.gov.moh.recovery-healthcert.json`, pointed at a reference checkout.
   That utility is a data-extraction tool and NOT one of the two reference implementations, so reading it while writing a library does not compromise the independence rule.
2. Set **`ROAX_REFERENCE_RECORDS=<dir>`**, which is the one flag that enables the class.

**The filename inside that directory is `<authority>.<profile>.json` and is this runner's contract rather than the corpus's**, since `recordVector` names only the path inside the reference checkout and the extraction utility writes wherever `--out` says.
A file under any other name leaves the class NOT RUN.

What IS verified here is the gate rather than the class.
The two ways it cannot run are reported apart, because they have different remedies: the variable unset names the extraction command to run, and the variable set with the derived filename absent names the exact path that was probed and the contract that produced it.
Neither is ever counted toward the passed total, and neither is reported green unrun.

Both gates fail loudly on a regression, which was verified rather than assumed: restoring dogtag's trailing-zero strip to `canonicalizeDecimal` makes `npm test` exit 1, with 16 class-1 failures in the corpus and the `0.010` unit test failing first.

The roots this implementation produces are byte-identical to the committed ones on every vector that carries a root **and that ran**.
That excludes the two class-10 MOH vectors, whose roots were not compared in any run recorded here.
