# The ROAX conformance corpus

**Status:** first cut.
504 vectors, all 21 classes reachable, 16 complete, 4 partial and 1 stale.
**Normative definition:** [`docs/conformance-corpus.md`](../docs/conformance-corpus.md).
**Schema:** [`schemas/conformance-corpus-1.0.json`](../schemas/conformance-corpus-1.0.json).
**Specification:** [`docs/spec/roax-canon-1.md`](../docs/spec/roax-canon-1.md), which governs where the two disagree (specification section 1.1).

This directory is the executable arbiter.
If ROAX ships five independent libraries it is the whole enforcement mechanism for cross-language agreement, not a safety net.

## What is here

| Path | What it is |
|---|---|
| `conformance-corpus-1.0.json` | The vector file. The deliverable. |
| `type-maps/*.json` | The type maps class 10 and class 11 are asserted against. Three are derived from the reference schemas with a citation on every entry; one is authored for the synthetic fixtures and says so. |
| `fixtures/records/*.json` | Synthetic records for classes 5, 7, 13, 15, 19, 20 and 21. Authored here; no reference sample is reproduced. Class 21 adds no record of its own: it reuses two of these under both leaf orderings, so the two roots differ for the ordering and for nothing else. |
| `fixtures/envelopes/*.json` | Envelopes for classes 11, 14, 15, 17, 18 and 20. Generated. Class 20's four are the copies a conforming implementation must REPRODUCE rather than merely verify. |
| `fixtures/salts/*.json` | The committed per-leaf salt sets. **Inputs, not generated fixtures**: under decision D4b a salt is an independent CSPRNG draw that nothing can re-derive (specification section 7), so a fresh build cannot recompute one and comparing it against a fresh draw would fail forever. Drawn once by `build_corpus.py --draw-salts` and committed; a build that finds one missing FAILS rather than drawing, because a drawn-on-demand salt would give one machine a root no other machine could reproduce. Class 10's sets pair positionally, everything else by path - `docs/conformance-corpus.md` class 10 says why, and why harmonizing them toward positional envelopes would be the unsafe direction. |
| `tools/` | Two independent implementations, the generator, the runner and the schema validator. |

**No reference schema or sample is copied into this repository.**
Class 10 names the MOH samples by module and export in a checkout that lives outside this repository by design, and `tools/extract_reference_record.py` converts one to JSON text in a scratch directory when a runner needs it.

## Running it

```sh
corpus/tools/run.sh --references /path/to/schemata --modules /path/to/node_modules
```

Both arguments are optional so that the runnable subset remains useful, but an omitted dependency makes the gate incomplete rather than successful.

- Without `--references`, class 10 reports `NOT RUN`, names the exact `--references` flag that enables it, and contributes zero assertions.
  It never reports green unrun.
- Without `--modules` (holding `ajv@8` and `ajv-formats`), the JSON Schema validation step reports `NOT RUN` and names the exact `--modules` flag that enables it.
  Ajv is installed outside this tree deliberately: the root `package.json` is the TypeScript library's and is not a place for schema tooling, as `AGENTS.md` records.

The exit status distinguishes the three gate outcomes:

| Status | Meaning |
|---:|---|
| 0 | Every check and vector ran and passed. |
| 1 | At least one check ran and failed. |
| 2 | Nothing failed, but at least one check or vector was `NOT RUN`. |

On the committed tree, the fully configured command above measures 504 vectors, 1,186 implementation-B assertions, and 112 JSON Schema verdicts.
**Each of the last two needs an input that lives outside this tree, and the two are missing in different ways**, neither of which is drift.
Without the pinned third-party reference checkout, `check_corpus.mjs` still runs and passes 1,178 assertions while reporting class 10's four vectors NOT RUN; supplying the checkout adds the 8 assertions those vectors carry.
Without an Ajv 8 and `ajv-formats` installed outside this tree and named by `--modules` or `ROAX_NODE_MODULES`, `validate_schemas.mjs` emits no verdict at all and exits 2, which `run.sh` reports as step 4 NOT RUN rather than as a lower count; with one it emits 112 verdict lines - the corpus file, the four corpus type maps, the 69 envelope fixtures and its 38 conditional probes - and exits 0.

`build_corpus.py --check` and `check_corpus.mjs` use the same three-way status.
In particular, each exits 2 when the committed external record vectors were not checked.
Run `corpus/tools/test_gate_status.sh` for the dependency-matrix and direct-tool regression checks; it uses scratch files only and never rewrites the corpus or its fixtures.

`run.sh` does five things.
The third is the cross-implementation comparison:

1. implementation A rebuilds the corpus, the generator-owned record and envelope fixtures, and the synthetic type map, then compares those outputs with the committed files, writing nothing;
2. implementation B shape-validates every committed salt-set input and recomputes the derived fields of every runnable committed vector, while a `NOT RUN` vector is copied through and excluded from the cross-implementation claim;
3. the emitted file is compared byte for byte with the committed corpus, with copied-through `NOT RUN` vectors identified as unchecked;
4. Ajv validates the corpus file and every committed type map, checks each envelope fixture against its expected schema verdict, and probes both directions of the schemas' conditionals with synthesized whole-corpus documents, because a conditional that never fires compiles perfectly and asserts nothing;
5. both implementations self-test their declared profile value rules.

Step 1 alone would only prove that one program is self-consistent.
Step 3 covers only rows generated into the committed corpus.
It does not claim that profiles or rows absent from that corpus were cross-checked.

**Step 5 is outside the corpus on purpose, and it is the only step that is.**
Ruled decision D13a keeps value-domain validation in a separate, independently versioned layer rather than in the canonicalization layer, so a corpus vector for a rule like the vaccination `dose` positive-integer narrowing would demand it from five implementations that by that ruling do not carry it.
The corpus pins the accept case through class 10, where the shipped sample's `dose` values are 1 and 2, and step 5 pins the refusals in the layer that owns them.
The discriminating values are `0` and the negatives, because a fractional value is already refused one layer down by the specification section 6.2 INTEGER grammar.

Step 1 covers the generator-owned fixtures because the corpus vectors reference them by path, and a corpus that round-trips over a hand-edited fixture is not a pass.
The generator builds each fixture's bytes, runs the verifier on **those bytes** rather than on the file, and then compares.
It used to write first and compare afterwards, which erased the edit it existed to catch.

The salt sets are committed random inputs, not generator-owned fixtures, so no check regenerates them.
Step 2 scans every `.json` file under `fixtures/salts/` and enforces the closed shape for its declared pairing, including canonical path segments and indices, unique encoded paths, positional `leafCount` cardinality, and lowercase 32-hex salts.
The path-paired shape follows `schemas/envelope-1.0.json` `$defs.leafSalt`, and the positional shape is the corpus-only carrier defined by `docs/conformance-corpus.md` class 10.
Vector execution then consumes the referenced set and checks the resulting leaf count and root.
These checks validate the carrier and its use; they neither regenerate a random draw nor measure its CSPRNG entropy (specification section 7).

Exactly what step 1 verifies, and nothing more:

| Artifact | Compared byte for byte | Directory scanned for extras |
|---|---|---|
| `corpus/conformance-corpus-1.0.json` | yes | n/a |
| `fixtures/records/*.json` | yes | yes |
| `fixtures/envelopes/*.json` | yes | yes |
| `type-maps/org.roax.corpus.synthetic.json` | yes | **no** |
| `type-maps/sg.gov.moh.*.json` | **no** | **no** |

The two scanned directories are compared as a **set**, because a byte comparison of the files the generator produces cannot see an EXTRA one - a renamed vector leaves the old file behind, referenced by no vector and reported by nothing.
`type-maps/` is not scanned because the generator does not own it: it writes the synthetic map, `build_type_maps.py` writes the other three, and a set comparison would call those three orphans.
Only `.json` is considered, so a gitignored `.DS_Store` cannot fail the check.

**Step 1 does not cover the three derived MOH type maps.**
Those are produced by `tools/build_type_maps.py`, a separate tool with no check mode, and no step of `run.sh` regenerates or compares them; step 4 only validates them against `schemas/type-map-1.0.json`.
Regenerate them by hand against a reference checkout after touching that tool.
The fourth map, `org.roax.corpus.synthetic.json`, is authored by the corpus generator and *is* compared by step 1.

### Every vector group must be CONSUMED, and an unknown one is a failure

A runner that does not know a group reads it as zero vectors and reports the same green it reported before the group existed.
That is worse than a coverage gap, because the per-class report cannot see it either: the class the group serves simply does not appear.

So every runner here enumerates the groups the corpus file carries and FAILS on one it does not consume.
`corpus/tools/check_corpus.mjs`, the TypeScript, Python, Swift and Kotlin runners each hold an explicit list, and `rust/tests/conformance_corpus.rs` uses serde's `deny_unknown_fields`, whose default of IGNORING an unknown member is exactly the quiet skip.
The guard was added BEFORE class 20 rather than with it, so that each runner went red for a reason its author controlled instead of quietly staying green.

### Checking an implementation that is not one of these two

The runner to port is [`tools/check_corpus.mjs`](tools/check_corpus.mjs).
It consumes every vector class and nothing else, and it is written to be read as the specification of what conformance means operationally.
The procedure per class:

| Vector array | What an implementation must do |
|---|---|
| `encodePath` | `encodePath(segments)` equals `encodedHex`; the display path equals `displayPath`. |
| `encodeValue` | `encodeValue(tag, input)` equals `encodedHex`. |
| `reject` | The input MUST error. The `reason` is the reference reason code; an implementation with its own taxonomy should map to it rather than ignore it. |
| `leaf` | `leafHash(segments, tag, value, saltHex)` equals `leafHash`. The salt is an INPUT: decision D4 is ruled D4b, so nothing derives one (specification section 7). |
| `record` | Flatten the record, union the reserved leaves, order by encoded path, take each leaf's salt from the set `saltsFile` names in the shape `saltPairing` declares; the leaf count then equals `leafCount` and the root equals `root`. A vector may instead carry the whole thing as one full envelope copy, naming `envelopeFile` and no salt set; a runner that does not implement that schema-valid carrier fails with exit 1 rather than reporting it `NOT RUN`. |
| `unlinkability` | Perform `trials` independent issuances at the paths given, with YOUR OWN generator, and assert the three relations. Nothing is compared against a pinned value, because under D4b there is none to pin. |
| `roundTrip` | ISSUE a full copy from `recordFile` under the salts `saltsFile` names, compare it with `expectedFullCopyFile`, derive a disclosed copy revealing exactly `disclosePaths` from the SAME commitment, compare it with `expectedDisclosedCopyFile`, and then verify BOTH through YOUR OWN verifier. This is the one group that runs an implementation against its own OUTPUT; every other group runs its verifier against bytes this generator wrote. Compare SEMANTICALLY - member order, `displayPath`, the order of `disclosure.leaves` and the order of a full copy's `salts` are not specified, so key those two arrays by leaf index and by structured path and drop `displayPath` on both sides - while keeping every number's source text and every other member exact. |
| `tree` | `MTH(leafHashes)` equals `root`. |
| `inclusion` | Verifying `(leafHash, index, treeSize, auditPath, root)` returns `expect`. Generating the audit path for `index` reproduces `auditPath`. |
| `negativeProof` | Verification MUST fail. |
| `typeMap` | Resolving `segments` at `jsonKind` against `type-maps/<recordType>.json` yields `expectTag`, or fails closed when `expectFailClosed`. |
| `normalization` | Build a root over `recordFileNFD` and over `recordFileNFC`, both under the ONE salt set `saltsFile` names, so any difference between the two roots is normalization and nothing else. The two agree iff `expectSameRoot`, and the root equals `root`. |
| `envelope` | Verifying `envelopeFile` returns `expectAccept`, **and rejects for `reason`**. The reason is not decoration here: several fixtures are rejectable for more than one cause, so a boolean alone would pass an implementation that never ran the check the vector is about. `guard-reject-reserved-collision` is the clearest case - the record it carries cannot be hashed at all, so its envelope holds a placeholder root, and an implementation that skips the reserved-namespace guard rejects it on `root-mismatch` and looks correct. |
| `ordering` | Commit `recordFile` TWICE under the one salt set `saltsFile` names, once per key of `orderings`, and for each side reproduce its `leafCount`, its `root`, its `leafHashes` in TREE order and its `displayPaths` in TREE order. Then assert across the two sides: the roots DIFFER, and the two leaf-hash sets are **disjoint**. Disjointness is the stronger assertion and is what section 9.5's H1 buys - a runner checking only the roots would pass an implementation that permuted one leaf set into the other tree. The `hash` side carries one more leaf than the `path` side, because a non-default ordering also commits `roax.ordering` (specification section 11.2). |

### Input escape forms

Three values cannot appear literally in a JSON file, so `input` may carry one of these instead of a plain JSON value.
Everything else is literal.

| Form | Means |
|---|---|
| `{"$utf16": ["0041", "d800"]}` | A string built from those UTF-16 code units. This is how an unpaired surrogate is carried: a conforming JSON writer cannot emit one as well-formed UTF-8. |
| `{"$segments": [ ... ]}` | A path. Used where the corpus schema's own `segments` definition cannot express the vector - see "Known corpus schema limits". A segment's `key` may itself be a `$utf16` object. |
| `{"$jsonText": "..."}` | Record text to be handed to the implementation's JSON reader, for rejections that happen at the parser boundary rather than at a tag. A reject vector that ALSO carries a `recordType` means something more - see below. |

### A reject vector with a `recordType` is a whole-record rejection

`rejectVector.recordType` is optional, and its presence changes how a runner must consume the vector.
Absent, the vector goes to the value encoder or the path encoder in the carrier form its `tag` or `segments` names.
Present, the `input` is a whole record as `{"$jsonText": ...}` and the runner MUST flatten it through the **committed** type map for that `recordType`.

**The shape exists because three of the five type bindings ruled on 2026-07-30 are stated as rejections rather than as tags**, and a tag-bearing reject vector cannot reach any of them: it arrives at the value encoder already in the CARRIER form, so it can never exercise a rejection that happens where a RECORD value is converted into that carrier.
That is where the ruled `base64Binary` input-admissibility rejections live, and where the ruled FHIR primitive-array null-placeholder rejection lives.

**The map must be the committed one and never a resolve-everything stand-in.**
Several of these vectors assert that a path has NO binding for an observed kind, and a permissive map makes exactly those unfalsifiable.
No record identity is carried, because flattening needs none: the assertion is a rejection at the record boundary and not a tree.

### The reason-code divergence these vectors found

**Four implementations name the fail-closed condition four different ways, and non-canonical base64 two ways.**
The record-shaped reject vectors above are the first vectors whose `reason` is either condition, so the corpus had never been able to see this.

| Condition | `roax_ref.py`, `roax_ref.mjs` | TypeScript library | Python library | Rust library |
|---|---|---|---|---|
| No binding for the observed kind | `type-map-uncovered-path` | `type-map-fail-closed` | `type-unresolved` | `type-map-fail-closed` |
| base64 outside the pinned form | `base64-not-canonical` | `base64-not-canonical` | `base64-not-canonical` | `invalid-base64` |

A corpus `reason` is the reference implementations' spelling and is not a normative code, so each library's runner carries a **declared** equivalence table beside this measurement rather than a loosened comparison: it maps one reference code to the one local code naming the same condition, and a rejection for a different reason still fails.
Rust's went into the `canonical_rejection_reason` mapper that already existed for exactly this.

Harmonizing the codes themselves is a library API change in four packages and was not made here: the Swift library, added after this was measured, names the two conditions `type-map-fail-closed` and `base64-not-canonical`, so it carries an equivalence table of its own rather than a fifth spelling.

### How the tree class generates its leaves

Class 8 tests `MTH` and the RFC 9162 split rule, not leaf construction, so its leaves are `SHA-256("ROAX-CORPUS/1.0.0/tree/<n>/<i>")`.
A consumer never needs this rule, because every tree vector carries its leaf hashes explicitly; it is written down so both reference implementations regenerate identical trees.
Inclusion and negative-proof vectors are derived from the tree vector named `tree-n<size>`.

## Coverage, class by class

Counts are vectors in the file, measured by `build_corpus.py --report`.

| Class | Vectors | Status |
|---:|---:|---|
| 1 FHIR decimals | 44 | complete |
| 2 integers beyond 2^53 | 12 | complete |
| 3 rejection vectors | 29 | complete. Includes the five record-shaped rows the ruled FHIR `base64Binary` BYTES binding needs: four non-canonical base64 spellings and a JSON number at the BYTES-bound path - see below.
| 4 Unicode | 27 | complete |
| 5 structure | 10 | complete. The tenth is `reject-fhir-primitive-array-null-placeholder`, which makes the ruled ABSENCE of a NULL binding checkable - see below.
| 6 path | 40 | complete |
| 7 type tags | 21 | complete. Grew with the ruled `base64Binary` BYTES semantics: a record committing a BYTES leaf and a STRING leaf from the same base64 characters, plus the isolated encoding pair that separates the two readings - see below.
| 8 tree shape | 173 | complete |
| 9 negative proof vectors | 11 | **stale - the forged-size, full-disclosure row is absent** |
| 10 the three real MOH records | 4 | **partial - 2 of 3 records.** The vaccination sample commits since its two bindings were ruled; PDT stays uncommittable - see below |
| 11 the schema binding | 24 | **partial - the two FHIR fail-closed rows are inexpressible.** Includes the three unknown-algorithm and unknown-profile fail-closed vectors: specification section 12.2 calls that "the same rule section 4.2 applies to an unknown path, applied one level up", and section 4.2 is what this class tests - see below |
| 12 cross-record unlinkability | 3 | complete. Behavioural rather than pinned: the runner draws and asserts. Detects a deterministic or reused salt; it CANNOT detect a weak CSPRNG, and no fixed vector file can. |
| 13 reference-schema hazards | 2 | **partial - the `$id` half is inexpressible** |
| 14 minimum-disclosure floor | 42 | complete. The four outer-identity vectors this row used to count are class 18 now - see below. Grew by the 8 `typemap-floor-*` vectors, one accept and one omit per profile, which are the first fixtures here to carry a `typeMap` member at all. |
| 15 reserved-namespace guard | 20 | complete |
| 16 Unicode version sensitivity | 20 | complete, at the strength class 16 itself states |
| 17 withheld-leaf salt | 9 | complete. The ninth is `salt-leak-disclosed-copy-with-wrong-typed-salts`, which fails a verifier that reads a present-but-wrong-typed member as absent and thereby switches its own guard off |
| 18 outside-the-root authority | 6 | **partial - the identity rows and the two type-map binding rows; the registry rows are a named gap** |
| 19 NFC end to end, with a root | 2 | complete - both the value site and the key site, the latter buildable since decision D14 was ruled D14a |
| 20 issue-then-verify round trip | 2 | complete. The only class that runs an implementation against its own PRODUCED envelope - see below |
| 21 leaf ordering | 3 | complete. One record under BOTH orderings, asserting two roots that differ and two disjoint leaf-hash sets - see below |

### A build without `--references` carries the class-10 vectors forward, and says so

**Before this, `python3 corpus/tools/build_corpus.py` with no reference checkout wrote a corpus with the four class-10 vectors DELETED.**
Anyone rebuilding for an unrelated reason silently removed the only end-to-end coverage of a real national profile, and the diff looked like an ordinary regeneration.
They are now carried forward verbatim and the operator is told, by name, that they were not recomputed.

> **The trade this makes, stated rather than left to be found.**
> The carry-forward reads the file it is about to write, so under `--check` those four vectors are compared against themselves.
> That inverts the rule `corpus/tools/synthetic_records.py` states for record fixtures - "reading the file would make a hand-edited fixture agree with itself, which is what check mode exists to catch" - and it is accepted here only because the alternative is deleting committed evidence.
> The run prints the note in BOTH modes and still exits 2, so the self-agreement is disclosed rather than hidden, and a canonicalization change is validated only by a build with `--references`.

### Class 21 is what stops the second leaf ordering existing only in prose

**Specification section 9 made leaf ordering a per-record choice on 2026-08-02, under the amended decision D5.**
Every other class in this file runs under `path` ordering and would run identically if `hash` ordering had been specified and never implemented.

Each of the three vectors carries one record, one salt set and one identity, and asserts what that record commits under BOTH orderings.
The two cross-ordering assertions are the load-bearing ones: the roots differ, and the two leaf-hash sets are **disjoint**, which is stronger.
Disjointness is what proves the difference is not a permutation of one leaf set into another tree, and it holds because the ordering sits inside `DOMAIN` and therefore inside every leaf preimage (specification section 9.5, H1).

**One salt set serves both sides deliberately.**
It is drawn over the hash-ordered leaf set, which is a superset because that side also emits the conditional `roax.ordering` leaf.
Two salt sets would make the roots differ for a reason that has nothing to do with ordering, which is the confounding the class exists to exclude.

**What building it found, in a library that had passed 501 vectors.**
Kotlin's `commitWithSaltsByPath` learns the leaf order from a placeholder-salt pass and then consumes real salts positionally.
Once `commit` returned TREE order, that placeholder pass gave a hash order computed over placeholder salts, so every real salt would have paired with the wrong leaf and produced a plausible wrong root rather than an error.
Under `path` ordering the re-sort that fixes it is the identity, which is exactly why no vector could see it before this class existed.

**The corpus grew by 3 vectors and not one committed expected value moved.**
`path` ordering contributes the empty domain suffix and emits no ordering leaf, so the amendment is additive by construction: 501 vectors to 504, with 174 existing vectors gaining a declared `ordering` field and nothing recomputed.
That is what makes `corpusVersion` a MINOR bump to 1.2.0 rather than a major one.

### Classes 14, 18 and 20 grew because two blind spots were proven rather than argued

Both were found by a person reading an implementation, not by this corpus, and both are recorded here because the shape recurs.

**Blind spot 1: nothing ran an implementation against its own OUTPUT.**
Every envelope fixture in this directory is produced by `corpus/tools/build_corpus.py`, so classes 14, 15, 17 and 18 all run a library's VERIFIER against a third party's bytes.
A library could therefore issue a disclosed copy its own verifier refused and pass all 488 vectors - and one did, omitting every revealed leaf's per-tag value carrier and failing on `disclosed-leaf-named-without-value`, a condition class 17 names in a committed vector.
Class 20 closes it: issue, disclose, compare against the committed copies, and verify your own output.

**Blind spot 2: no committed fixture carried a `typeMap` member**, so nothing reached the specification section 4.2 binding in either direction.
A verifier could gate the whole check on that member - which the HOLDER supplies - and no vector would notice.
`typemap-floor-*` and the two `identity-outer-type-map-*` rows close it.
The governing rule is worth stating once: **a check whose execution is controlled by the party it constrains is not a check.**

**What extending the corpus then measured across the five libraries**, listed because a corpus change that turns a merged library red is the finding rather than an obstacle:

| Library | Outcome |
|---|---|
| Rust | Not exploitable, but its runner chose the envelope generation from the presenter-supplied `typeMap` member, and the copy with that member stripped was refused by the reserved-namespace guard rather than by the binding. `reserved_leaf_set_for` now selects from what the envelope COMMITS. |
| TypeScript | Passed both binding families. Its `VerifierConfig` could declare a profile known and then fail closed on the same profile at the floor, with the same `profile-unknown` code for a different reason; `floorFor` closes that. |
| Python | **Accepted all four type-map binding attacks.** It had no binding at all outside a verifier configuration nothing set. Fixed. |
| Swift | Passed. This is where both blind spots were found. |
| Kotlin | Accepted a copy withholding `roax.typeMap.id` while the outer member named one, and emitted AND read the tag-5 BYTES disclosure carrier as base64 rather than lowercase hex. Both fixed; the second was caught by class 20 and by nothing else, because no committed disclosed fixture carries a BYTES leaf. |

**The single most useful thing class 20 found is none of the above.**
The TypeScript library refused to ISSUE an envelope without `roax.typeMap.id` and the Python library refused to issue one WITH it.
Two shipped libraries held mutually exclusive issuance rules, both passed all 488 vectors, and no verifying-side vector could ever have found it.
Specification section 11.2 settles the question - that leaf is emitted ALWAYS - so Python's refusal was narrowed to the thing it actually needs, which is artifact resolution rather than issuance.

### Class 10 is partial, and the reason is a finding rather than an omission

The recovery and vaccination healthcerts have vectors.
The PDT sample **cannot be committed at all** under the fail-closed rule of specification section 4.2, because its reference schema does not determine a ROAX type tag for every scalar the sample contains: its root object declares seven members and does not close itself, so `$template`, `attachments`, `issuers` and `notarisationMetadata` - all four present in its own shipped sample - are permitted and undeclared.
That is twenty unbound `(pattern, jsonKind)` pairs.

Binding them here would be an authored ruling, and an authored ruling inside the corpus is the exact defect `docs/conformance-corpus.md` section 1.2 forbids: every implementation built against the corpus would inherit it as though it were settled.
So those paths appear as class 11 **fail-closed** vectors, which is a real assertion on real paths, and the roots wait for a ruling.
The ruling those 20 pairs need is a versioned PDT composition profile rather than 20 authored bindings, because the endorsed sample does not define the composition's full path language (`docs/type-maps.md` section 1.2).
Nobody has ruled one.

**The vaccination row was in the same state until 2026-07-30 and is not any more.**
Its two blocking paths were ruled - `notarisationMetadata.signedEuHealthCerts[*].dose` INTEGER at evidence grade Strong and `expiryDateTime` STRING at grade Moderate - so the sample now commits at 91 leaves without an issuer key identifier and 92 with one (`docs/type-maps.md` section 1.1).
That is a ruling arriving from a document and reaching the corpus, which is the order section 1.2 requires; it is not the corpus deciding anything.
The `dose` ruling also carries a positive-integer profile narrowing, which is **not** in the canonicalization layer under ruled decision D13a and is therefore not a corpus vector: it is declared by `docs/profiles/vaccination-healthcert.md` section 6, executable in `tools/profile_rules.py` and `profile_rules.mjs`, and self-tested by `run.sh` step 5.
What the corpus pins is the accept case, since the sample's `dose` values are 1 and 2.

`tools/build_type_maps.py` produces the vectors the moment the remaining bindings exist.
Nothing else is blocking.

### Class 11 is partial, and the two missing rows are inexpressible rather than merely absent

`docs/conformance-corpus.md` class 11 requires the fail-closed rows to cover FHIR `Narrative.div` and FHIR `base64Binary`, and none of the 21 committed `typeMap` vectors does.
That gap predates the 2026-07-30 rulings and is not closable here: `corpus/type-maps/` carries no map for `hl7.fhir.bundle` at all, and a fail-closed vector has to name an exact map to fail closed against.
It is the same corpus defect that leaves specification section 10 step 1 undischargeable for that `recordType`, recorded in `docs/typescript-implementation-findings.md`.
So the row is the sibling of class 13's `$id` half below: the assertion is real and the carrier for it does not exist.

Two wrong ways to close it, both of which `docs/conformance-corpus.md` section 1.2 forbids.
Authoring FHIR class-11 vectors would need a corpus-side FHIR map, and writing one invents bindings for paths the rulings deliberately left out of the operative artifacts (`docs/type-maps.md` section 1.6).
Trimming the requirement to match the vectors settles the same question from the other side.
The requirement therefore stands and this row stays partial until a corpus-side map for `hl7.fhir.bundle` exists.

**The unknown empty array and empty object that requirement also names are absent for a different reason**, which is the release-blocking section 3.3 divergence recorded in `docs/typescript-implementation-findings.md` and `python/FINDINGS.md` item 1, not a missing map.
Both halves have to close before this class is complete.

### The floor is over segments, and the outer identity does not select it alone

Two things that are easy to get wrong in the same place, and a corpus is the only place either can be pinned.
The first is class 14's.
The second is class 18's: the four identity vectors sat in class 14 only because class 18 did not exist yet, and they moved when decision D8 created it.

**A floor path is SEGMENTS, never display notation.**
`docs/profiles/vaccination-healthcert.md` section 4 writes `notarisationMetadata.reference`, and specification section 5.2 is explicit that a display path is for humans and is never parsed back.
Read as a single key, that floor entry asks for a leaf whose key is literally the eighteen-character dotted string.
No record has one, so the floor matches nothing and is **silently unenforced** while every vector built the same way agrees with it.
`envelope.py` and `envelope.mjs` therefore carry the floor as segments in both implementations, and `floor-sg-gov-moh-vaccination-healthcert-*` reveals two segments.

**The outer `recordType` selects the floor, so it cannot be trusted to.**
Specification section 11.3 states normatively that a field outside the root is a hint and never authority, and section 11.2 commits `recordType`, `schemaVersion`, `recordId` and `issuer.id` as leaves so a disclosed copy can be checked against them.
pdt's floor is a strict **subset** of recovery's, which adds `validUntil`, so a holder of a recovery copy who relabels the envelope as pdt discloses pdt's floor, withholds the expiry, and every inclusion proof still verifies against the genuine recovery root.
`identity-outer-record-type-downgrade` carries exactly that copy and the other three carry a mismatch in each remaining reserved field; all four reject with `outer-identity-mismatch`.
Measured: with the binding removed, all four are **accepted**.
Those four plus the two `identity-outer-type-map-*` binding rows are the whole of class 18 as built, and all six carry no `verifierConfig` because the envelope alone determines each of them.

#### The identity binding runs BEFORE the floor, and that order is required

The **ordering** below is a stated requirement, not one of the open ambiguities, because it is derived rather than chosen.
Section 11.3 says a field outside the root is never authority; it follows that authority is established before an outer field is used to **select** anything.
Choosing the floor from the envelope's `recordType` and validating it afterwards is trust-then-verify - the same shape as the dogtag scar section 11.3 records - and is safe today only by accident of the current rules rather than by construction.
So a disclosed copy is verified in this order:

1. every disclosed leaf is recomputed and its inclusion proof checked against the root;
2. the outer `recordType`, `schemaVersion`, `recordId` and `issuer.id` are bound to the reserved leaves the root commits;
3. the floor is selected from the **committed** `roax.recordType` leaf and enforced.

**The step 1-2 ordering is pinned by the vectors.
Step 3's source-of-floor is not, and cannot be.**
Both halves of that are measured, and the difference matters to anyone porting this:

| Deviation | Envelope vectors failed, of the 54 committed when this was measured |
|---|---:|
| enforce the floor before the binding | **16** |
| keep the ordering, read the floor from the envelope's `recordType` | **0** |

The second is zero *because* step 2 has just proved the outer field NFC-equal to the committed leaf: both sources then yield the same floor table, so no vector can tell them apart.
Sourcing it from the leaf is therefore a **clarity convention** rather than a corpus-enforced requirement - it puts the structural claim where a reader of the code can see it, and an implementation that reads the outer field instead will pass the corpus.
The `profile-unknown` branch that follows the lookup in both implementations is unreachable for the same reason, and is kept only so that a later edit cannot quietly restore the trust-then-verify shape.

Two consequences an implementer needs, and unlike step 3 both ARE observable in the vectors:

- **The binding subsumes the reserved half of the floor.**
  If one of those four reserved leaves is absent the binding fires first, so the floor loop can now only ever reject on a profile-specific path.
  The 16 `floor-<profile>-omits-roax-*` vectors - four reserved paths across four profiles - therefore assert `outer-identity-mismatch`, not `minimum-disclosure-floor`.
  An implementation that enforces the floor first fails exactly those 16, and the cause is the ordering, not the floor table.
  The class 14 requirement is unchanged: each reserved path omitted in turn is still rejected, only the code differs.
  `_floor_for` still carries the four reserved paths, because `docs/conformance-corpus.md` class 14 defines the floor as those plus what the profile adds and that definition should stay readable in the code.
- **The reason code is the honest one.**
  A copy that withholds `roax.recordType` never told the verifier what it is, so no floor could be selected for it; `minimum-disclosure-floor` would claim a floor was chosen and then missed.

`profile-unknown` is unaffected and still fires on the outer `recordType` before any of this.
It is the verifier's own allow-list - the same shape as the `hashAlg` allow-list of section 7.4 H3 - and settles whether this verifier can proceed at all rather than which policy to apply.
`roax.issuer.keyId` is deliberately not bound, being a conditional leaf (specification section 11.2).

### Class 13 is partial

The flattened-versus-normalized FHIR entry layout is covered, as a synthetic pair proving the two layouts produce different roots.
The other half - loading the PDT and recovery schemas together and asserting recovery's rules still apply despite its `$id` pointing at PDT's path - is a JSON Schema **loading** property with no hash in it, and `schemas/conformance-corpus-1.0.json` has no vector type that can express it.
It is enforced in `tools/build_type_maps.py`, which resolves `$ref` by file path and never registers a schema by `$id`, and the two colliding `$id` values were confirmed by reading them.

### Class 18 is partly built, and the unbuilt half is a named gap rather than an omission

The four identity rows and the two type-map binding rows are built and are described above.
The registry-dependent rows of `docs/conformance-corpus.md` class 18 are not, and they cannot be: each of them turns on what the verifier's own anchoring registry answers, and specification section 2.2 deliberately leaves that registry undesigned.
Building them here would make the corpus invent that interface, which section 1.2 of the corpus document forbids for the same reason it forbids binding an unresolved path.
That is why `schemas/conformance-corpus-1.0.json` PERMITS `envelopeVector.verifierConfig` at class 18 rather than requiring it: an earlier revision required it, and the six built vectors carry none because the envelope alone determines them, so the requirement rejected the committed corpus.
The completeness rule the block exists for - a vector whose outcome turns on the verifier's configuration must state that configuration - is stated in the schema and is **not mechanically enforced today**, because the vectors that would need the check are exactly the ones that cannot be built yet.

### Class 19 now carries both sites, and decision D14a is why the key site is buildable

The class defines two sites, a value and an object key, because an implementation can normalize one and not the other.
Both are built.

**The key site was deliberately unbuilt until 2026-07-30**, because a key-site vector has to resolve its key through the type map, and whether that lookup normalized was an open question - ambiguity 4 below.
Both reference implementations matched raw, so a built vector would have passed under one reading and failed under the other, which settles a decision from inside a data file rather than testing a settled one.
Decision D14 is ruled D14a, normalize, so the vector now tests a decided question and `build_corpus` fails the build if either site is missing.

**Two committed vectors discriminate the two readings, and both fail closed under raw matching.**

| Vector | Under D14a, ruled | Under raw matching |
|---|---|---|
| `normalization-nfc-key-end-to-end`, the NFD half | resolves, and gives the same root as its composed twin | `type-map-uncovered-path` at `é`, so the vector's `expectSameRoot` is unreachable |
| `record-guard-kelvin-key` | resolves, reaching the ASCII `Kelvin` pattern through NFC | `type-map-uncovered-path` at `Kelvin` |

The second exists because the synthetic map used to declare the Kelvin key under **both** spellings, which was a workaround standing in for the decision.
Removing the U+212A duplicate turned an existing vector into a discriminator at no cost, and keeping it would have left that vector passing under either reading, which is exactly why it proved nothing before.

**Rebuilding the corpus under D14a changed zero existing vectors and added one.**
Encoded paths already normalized every KEY segment, so the leaf bytes were always NFC and the ruling moves no root.

## What was actually measured, and what was not

**The corpus was generated twice, in two languages, and the outputs are byte-identical.**
Implementation A is [`tools/roax_ref.py`](tools/roax_ref.py) (Python 3.13), implementation B is [`tools/roax_ref.mjs`](tools/roax_ref.mjs) (Node 22).
B was written from the specification text rather than ported from A.
They share no code, and they differ where it counts:

| | implementation A | implementation B |
|---|---|---|
| JSON reader | `json.loads` with `parse_int`, `parse_float` and `object_pairs_hook` | a hand-written scanner, because `JSON.parse` cannot preserve duplicate keys |
| Numbers | verbatim literal text, arbitrary precision | verbatim literal text, arbitrary precision |
| NFC tables | Python 3.13.5, **Unicode 15.1.0** | Node v22.21.0 / ICU 77.1, **Unicode 16.0** |
| Byte handling | `bytes`, `int.to_bytes` | `Buffer`, `writeUInt32BE`, `BigInt` for `u64be` |
| Sort | `list.sort` over `bytes` | `Array.sort` with `Buffer.compare` |

The Unicode row is worth reading twice.
The corpus pins Unicode 15.1 and was **generated under 15.1.0 tables**; implementation B agreed on every vector while running **16.0** tables.
That is a demonstration that these particular vectors are stable across that release boundary.
It is not a demonstration that a version mismatch is detectable, which class 16 already says it is not, because no character whose NFC form changed between releases has been identified for this corpus.

**Both reference implementations here have one author**, so they share one reading of the specification, and a shared misreading is exactly what a corpus exists to catch.
What two implementations in two languages do catch is transcription slips and language-API divergence, and they caught one - see below.
Scope the claim to that.
Nothing in this directory discharges gate 3 of `docs/conformance-corpus.md`, and section 2.1 of that document owns the gate's status.

### The prior canonicalization research was used narrowly, and here is exactly how

That work built five implementations that produced identical roots on the three real MOH records.
**None of its whole-record roots transfer, and none were used.**
It predates the reserved leaf set, used a bare `ROAX-CANON/1` domain string rather than the algorithm-qualified one, and derived its salts through a preimage where this design now draws them independently (decision D4b, specification section 7).
Each of those changes every leaf hash in every record, so its 87-, 130- and 65-leaf roots are not comparable with anything here.

Two things from it agree with this work, and both were read before this work was done, so they are corroboration and not blind agreement:

- the `encodePath` hex for the nested-versus-dotted collision pair, which matches `path-nested-a-b` and `path-literal-dotted-key` here;
- the record leaf counts 87, 130 and 65, which this work also gets by enumerating the samples.

Nothing was copied.
Everything in this corpus was derived from `docs/spec/roax-canon-1.md`.

### The divergence the two implementations caught

Python's `$` in a regular expression also matches immediately before a trailing newline; JavaScript's matches only at end of input.
Implementation A's first draft anchored the section 6.2 number grammars with `^...$` and therefore **accepted `"1.0\n"` and canonicalized it**, while implementation B rejected it.
Both grammars are now anchored `\A...\Z`, and `reject-decimal-trailing-newline` and `reject-integer-trailing-newline` pin it.
Any implementation written in a Python-family regex dialect has this bug until it is looked for.

## Known corpus schema limits

Two places where `schemas/conformance-corpus-1.0.json` cannot express something `docs/conformance-corpus.md` requires.
Both are worked around visibly rather than silently.

1. **Class 6 requires an array index at `2^32` that MUST be rejected**, but `rejectVector.segments` resolves to `#/$defs/segments`, whose index `maximum` is `4294967295`.
   The vector therefore cannot be written through `segments`, and `reject-index-at-2-32` carries it in the unconstrained `input` field as `{"$segments": [{"index": 4294967296}]}` instead.
2. **Class 13's schema-`$id` half has no vector type**, as described above.

A third, smaller one: `typeMapVector` identifies its map by `recordType` alone, with no file reference and no `schemaVersion`, so the runner resolves it by the convention `corpus/type-maps/<recordType>.json`.

A fourth, which is only a naming gap: there is no class for "an unknown algorithm or an unknown profile fails closed", which specification sections 7.4 H3 and 12.2 both require.
Those three vectors are filed under class 11 for the reason given in the coverage table, rather than left untagged where the gap check would not see them.

## Specification ambiguities found

Recorded rather than decided.
Every one of them is unobservable across the shipped vectors, which is deliberate: a vector that discriminated would settle the question from inside the corpus.

1. **The 1024-digit bound's scope.**
   Specification section 6.2 states it under *Canonical decimal*, but its own justification paragraph counts "class 2's 40-digit integer" against it.
   Both corpus reference implementations and the Rust implementation apply it to INTEGER as well as DECIMAL.
   No vector discriminates.
2. **What the 1024-digit bound counts.**
   "The expanded positional form" is read here as the padded form *before* the output-grammar normalization, which is the literal reading and the memory-safe one.
   Under the other reading `0e99999` canonicalizes to `0`; under this one it is rejected.
   No vector carries `0e99999`.
3. **Resolved and removed: the record identifier in the salt preimage.**
   This list previously recorded that section 7 wrote `RID = utf8(recordId)` rather than `utf8(NFC(recordId))`, while the reserved leaf `roax.recordId` is a STRING and therefore *is* normalized.
   Decision D4 was ruled D4b and section 7 has no preimage at all, so the ambiguity is gone rather than resolved.
   The reserved leaf is unaffected and still normalizes.
4. **Resolved: type-map matching is now stated to be over NFC-normalized keys.**
   This ambiguity was that section 11.2's general rule - "check the bytes you commit, not the bytes you received" - suggested normalizing while the specification said nothing, and both implementations compared a pattern token against a segment key **raw**, with no `nfc()` on either side.
   It was raised to decision D14 and ruled **D14a on 2026-07-30**: specification section 4.2 now requires the lookup to compare the normalized key, and both implementations normalize the pattern token at parse time and the segment key at match time.
   The Kelvin workaround that stood in for the decision is removed and the class-19 key site is built, so two vectors now discriminate the readings where none did.
   See the class 19 section above.
5. **The type-map `pattern` field is display notation**, so it cannot address a key containing `.`, `[` or `]` - keys section 5 deliberately admits with no rejection rule.
   `a.**` reaches such a key without the pattern language growing an escape, and both implementations reject an ambiguous pattern rather than mis-parse it.
6. **NFC-colliding sibling keys with disjoint descendants are not ruled.**
   Specification sections 3.2 and 3.3 require raw map keys to be unique and emit complete leaf paths, while section 5 normalizes each KEY segment, so `{"é":{"a":1},"é":{"b":2}}` has neither a duplicate raw key nor a duplicate complete encoded leaf path even though the two intermediate paths encode identically.
   The Rust implementation accepts that shape, and no vector distinguishes acceptance from rejecting every intermediate-key collision.
7. **Issuer-scope membership has no normalization rule.**
   Specification section 10 requires a disclosed issuer identity to be a member of `scope.issuerIds`, but neither it nor `docs/type-maps.md` says whether that comparison uses the received strings or their NFC forms.
   The executable extension checker compares the strings as received, while the Rust implementation rejects issuer child artifacts until parent/additivity support can make that choice observable.

## One substantive specification finding

**Specification section 11.1's claim that `leafCount` is self-binding in a disclosed copy does not hold.**
It says tree shape is uniquely determined by the number of leaves, "so a wrong `leafCount` makes the audit path fail".
Measured, on an 8-leaf tree:

```
  internal node MTH(L[0:4]) presented as a leaf at index 0
    with the TRUE tree size 8      -> verification FAILS   (correct)
    with a FORGED tree size 2      -> verification SUCCEEDS
```

RFC 9162 section 2.1.3.2 consumes `tree_size` as an input, so an attacker who controls `leafCount` controls the shape the verifier reconstructs.
What actually blocks the attack is specification section 10 step 1 - recompute the leaf hash from the disclosed fields rather than trust a supplied one - plus second-preimage resistance, since the attacker would need a `(path, tag, value, salt)` hashing to the internal node.
That defence is already normative and already load-bearing; the `leafCount` sentence overstates a second one that is not there.

`negative-internal-node-as-leaf` and `negative-internal-node-as-leaf-n130` still carry the honest tree size, where the bare RFC 9162 fold rejects.
No committed `negativeProof` row has attack `forged-tree-size`, and that carrier has only a supplied `leafHash`, not the path, tag, value and salt needed to drive the full disclosed-copy verification path required by `docs/conformance-corpus.md` class 9 and specification section 10 step 2.
The coverage row above is therefore stale until the corpus is rebuilt with an expressible full-disclosure attack vector.
An implementation-specific regression may demonstrate the defence, but it does not make the missing corpus release gate complete.

## Decisions this corpus does and does not presume

`docs/conformance-corpus.md` section 1.2 requires a field-by-field audit.
Done once, here.

| Field | Presumes | Resolution |
|---|---|---|
| `recordVector.saltsFile` and `saltPairing` | D4 salt strategy | **RULED D4b**, so this is no longer a presumption to manage. Every salt is an independent random draw that nothing can re-derive, so a vector must name the set its root was computed under; a bare record file plus a root asserts something no runner can reproduce. `masterSaltHex` and the whole `saltVector` class are gone - they expressed a derivation that no longer exists. |
| Leaf ordering in every `record`, `tree` and `envelope` vector | D5 leaf ordering | Encoded-path order, per specification section 9. There is no root without an ordering, so class 8 and class 10 are inexpressible otherwise. The specification governs (section 1.1) and this is derived from it, not decided here. |
| `typeMapVector.expectFailClosed` | D7 unknown paths | Fail-closed, per specification section 4.2, which states the rule normatively and records that it is the recommended answer to D7. Same resolution as D5. |
| NFC in every string and key vector | D12 normalization | NFC with a pinned Unicode version, per specification section 6.1. Same resolution. |
| `hashAlg` | B, ruled | `SHA-256`. See below. |

Nothing here binds a `number` to a numeric tag, adds a default tag, or requires a salt seed in any envelope.

## Why there is no Poseidon-BN254 corpus

`schemas/conformance-corpus-1.0.json` carries `hashAlg` at the top level as a single value, so one corpus file is one algorithm by construction, and a second file would be the way to add one.
It cannot be written yet.
`ROAX-CANON/1` **registers** `Poseidon-BN254` and **defines** no construction for it: the field, the rate and capacity, the round constants, and - the part the byte layouts in specification sections 7 and 8 do not survive without - the encoding from a length-prefixed byte string to field elements are all unpinned, and section 7.4 states normatively that a record MUST NOT be issued against it until a revision pins them.

`algorithm-poseidon-fails-closed` therefore asserts the behaviour that *is* required today: a v1 verifier's allow-list excludes it and it fails closed with a stated reason (section 7.4, H3).

## The synthetic profile

`org.roax.corpus.synthetic` is a `recordType` that exists only inside this corpus.
It is syntactically valid under the envelope schema's reverse-DNS pattern and is deliberately **not** in the `docs/profiles/` registry, so a record MUST NOT be issued under it.
It exists so that structural vectors do not have to borrow a real health authority's profile identifier, and so that authored type-map bindings are never mixed into a map that claims schema provenance.
