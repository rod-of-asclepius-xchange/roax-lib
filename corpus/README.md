# The ROAX conformance corpus

**Status:** first cut.
471 vectors, all 19 classes reachable, 14 complete, 4 partial and 1 stale.
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
| `fixtures/records/*.json` | Synthetic records for classes 5, 7, 13, 15 and 19. Authored here; no reference sample is reproduced. |
| `fixtures/envelopes/*.json` | Envelopes for classes 11, 14, 15, 17 and 18. Generated. |
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

On the committed tree, the fully configured command above measures 471 vectors, 1,101 implementation-B assertions, and 70 JSON Schema verdicts.

`build_corpus.py --check` and `check_corpus.mjs` use the same three-way status.
In particular, each exits 2 when the committed external record vectors were not checked.
Run `corpus/tools/test_gate_status.sh` for the dependency-matrix and direct-tool regression checks; it uses scratch files only and never rewrites the corpus or its fixtures.

`run.sh` does four things.
The third is the cross-implementation comparison:

1. implementation A rebuilds the corpus, the generator-owned record and envelope fixtures, and the synthetic type map, then compares those outputs with the committed files, writing nothing;
2. implementation B shape-validates every committed salt-set input and recomputes the derived fields of every runnable committed vector, while a `NOT RUN` vector is copied through and excluded from the cross-implementation claim;
3. the emitted file is compared byte for byte with the committed corpus, with copied-through `NOT RUN` vectors identified as unchecked;
4. Ajv validates the corpus file and every committed type map, checks each envelope fixture against its expected schema verdict, and probes both directions of the schemas' conditionals with synthesized whole-corpus documents, because a conditional that never fires compiles perfectly and asserts nothing.

Step 1 alone would only prove that one program is self-consistent.
Step 3 covers only rows generated into the committed corpus.
It does not claim that profiles or rows absent from that corpus were cross-checked.

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
| `tree` | `MTH(leafHashes)` equals `root`. |
| `inclusion` | Verifying `(leafHash, index, treeSize, auditPath, root)` returns `expect`. Generating the audit path for `index` reproduces `auditPath`. |
| `negativeProof` | Verification MUST fail. |
| `typeMap` | Resolving `segments` at `jsonKind` against `type-maps/<recordType>.json` yields `expectTag`, or fails closed when `expectFailClosed`. |
| `normalization` | Build a root over `recordFileNFD` and over `recordFileNFC`, both under the ONE salt set `saltsFile` names, so any difference between the two roots is normalization and nothing else. The two agree iff `expectSameRoot`, and the root equals `root`. |
| `envelope` | Verifying `envelopeFile` returns `expectAccept`, **and rejects for `reason`**. The reason is not decoration here: several fixtures are rejectable for more than one cause, so a boolean alone would pass an implementation that never ran the check the vector is about. `guard-reject-reserved-collision` is the clearest case - the record it carries cannot be hashed at all, so its envelope holds a placeholder root, and an implementation that skips the reserved-namespace guard rejects it on `root-mismatch` and looks correct. |

### Input escape forms

Three values cannot appear literally in a JSON file, so `input` may carry one of these instead of a plain JSON value.
Everything else is literal.

| Form | Means |
|---|---|
| `{"$utf16": ["0041", "d800"]}` | A string built from those UTF-16 code units. This is how an unpaired surrogate is carried: a conforming JSON writer cannot emit one as well-formed UTF-8. |
| `{"$segments": [ ... ]}` | A path. Used where the corpus schema's own `segments` definition cannot express the vector - see "Known corpus schema limits". A segment's `key` may itself be a `$utf16` object. |
| `{"$jsonText": "..."}` | Record text to be handed to the implementation's JSON reader, for rejections that happen at the parser boundary rather than at a tag. |

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
| 3 rejection vectors | 24 | complete |
| 4 Unicode | 27 | complete |
| 5 structure | 9 | complete |
| 6 path | 40 | complete |
| 7 type tags | 14 | complete |
| 8 tree shape | 173 | complete |
| 9 negative proof vectors | 11 | **stale - the forged-size, full-disclosure row is absent** |
| 10 the three real MOH records | 2 | **partial - 1 of 3 records** |
| 11 the schema binding | 23 | complete. Includes the three unknown-algorithm and unknown-profile fail-closed vectors: specification section 12.2 calls that "the same rule section 4.2 applies to an unknown path, applied one level up", and section 4.2 is what this class tests. |
| 12 cross-record unlinkability | 3 | complete. Behavioural rather than pinned: the runner draws and asserts. Detects a deterministic or reused salt; it CANNOT detect a weak CSPRNG, and no fixed vector file can. |
| 13 reference-schema hazards | 2 | **partial - the `$id` half is inexpressible** |
| 14 minimum-disclosure floor | 34 | complete. The four outer-identity vectors this row used to count are class 18 now - see below. |
| 15 reserved-namespace guard | 20 | complete |
| 16 Unicode version sensitivity | 20 | complete, at the strength class 16 itself states |
| 17 withheld-leaf salt | 8 | complete |
| 18 outside-the-root authority | 4 | **partial - the identity rows only; the registry rows are a named gap** |
| 19 NFC end to end, with a root | 1 | **partial - the value site only; the key site is gated on decision D14** |

### Class 10 is partial, and the reason is a finding rather than an omission

Only the recovery healthcert has a vector.
The vaccination and PDT samples **cannot be committed at all** under the fail-closed rule of specification section 4.2, because their reference schemas do not determine a ROAX type tag for every scalar those samples contain:

- **vaccination:** `notarisationMetadata.signedEuHealthCerts[*].dose` is declared `"type": "number"` with no pattern.
  ROAX has two numeric tags and JSON Schema's `number` chooses neither.
  FHIR's own lite schema distinguishes `integer` from `decimal` by **pattern**, both being `"type": "number"`, and the notarise schema carries no such pattern.
  `expiryDateTime` in the same object is declared with a `format` and `examples` and **no `type` at all**.
- **PDT:** its root object declares seven members and does not close itself, so `$template`, `attachments`, `issuers` and `notarisationMetadata` - all four present in its own shipped sample - are permitted and undeclared.
  That is twenty unbound `(pattern, jsonKind)` pairs.

Binding either would be an authored ruling, and an authored ruling inside the corpus is the exact defect `docs/conformance-corpus.md` section 1.2 forbids: every implementation built against the corpus would inherit it as though it were settled.
So those paths appear as class 11 **fail-closed** vectors, which is a real assertion on real paths, and the roots wait for a ruling.

`tools/build_type_maps.py` produces the vectors the moment the bindings exist.
Nothing else is blocking.

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
Those four are the whole of class 18 as built, and they carry no `verifierConfig` because the envelope alone determines each of them.

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

| Deviation | Envelope vectors failed, of 54 |
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
`roax.issuer.keyId` is deliberately not bound, being the one conditional leaf.

### Class 13 is partial

The flattened-versus-normalized FHIR entry layout is covered, as a synthetic pair proving the two layouts produce different roots.
The other half - loading the PDT and recovery schemas together and asserting recovery's rules still apply despite its `$id` pointing at PDT's path - is a JSON Schema **loading** property with no hash in it, and `schemas/conformance-corpus-1.0.json` has no vector type that can express it.
It is enforced in `tools/build_type_maps.py`, which resolves `$ref` by file path and never registers a schema by `$id`, and the two colliding `$id` values were confirmed by reading them.

### Class 18 is partly built, and the unbuilt half is a named gap rather than an omission

The four identity rows are built and are described above.
The registry-dependent rows of `docs/conformance-corpus.md` class 18 are not, and they cannot be: each of them turns on what the verifier's own anchoring registry answers, and specification section 2.2 deliberately leaves that registry undesigned.
Building them here would make the corpus invent that interface, which section 1.2 of the corpus document forbids for the same reason it forbids binding an unresolved path.
That is why `schemas/conformance-corpus-1.0.json` PERMITS `envelopeVector.verifierConfig` at class 18 rather than requiring it: an earlier revision required it, and the four built vectors carry none because the envelope alone determines them, so the requirement rejected the committed corpus.
The completeness rule the block exists for - a vector whose outcome turns on the verifier's configuration must state that configuration - is stated in the schema and is **not mechanically enforced today**, because the vectors that would need the check are exactly the ones that cannot be built yet.

### Class 19 carries the value site only, and decision D14 is why

The class defines two sites, a value and an object key, because an implementation can normalize one and not the other.
Only the value site is built.
A key-site vector has to resolve its key through the type map, and whether type-map matching normalizes the key it matches on is an open question - ambiguity 4 below, recorded as decision D14 in `docs/decisions.md` Part 2a.
Both reference implementations match raw, so a built key-site vector would pass under one reading of that question and fail under the other, which settles it from inside a data file.
The row stays in the class table in `docs/conformance-corpus.md` so that a passing class 19 does not read as coverage it does not have.

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
4. **Type-map matching is not stated to be over normalized keys.**
   Section 11.2's general rule - "check the bytes you commit, not the bytes you received" - suggests it should be, but the specification does not say so, and both implementations compare a pattern token against a segment key **raw**, with no `nfc()` on either side (`_match_from`, `roax_ref.py:776`; `matchPattern`, `roax_ref.mjs:619`).
   The synthetic type map therefore carries the Kelvin key under **both** spellings, so that `record-guard-kelvin-key` resolves identically under either reading and no vector settles the question.
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
