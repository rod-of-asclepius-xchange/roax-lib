# The ROAX conformance corpus

**Status:** first cut. 472 vectors, all 17 classes reachable, 15 complete and 2 partial.
**Normative definition:** [`docs/conformance-corpus.md`](../docs/conformance-corpus.md).
**Schema:** [`schemas/conformance-corpus-1.0.json`](../schemas/conformance-corpus-1.0.json).
**Specification:** [`docs/spec/roax-canon-1.md`](../docs/spec/roax-canon-1.md), which governs where the
two disagree (specification section 1.1).

This directory is the executable arbiter. If ROAX ships five independent libraries it is the whole
enforcement mechanism for cross-language agreement, not a safety net.

## What is here

| Path | What it is |
|---|---|
| `conformance-corpus-1.0.json` | The vector file. The deliverable. |
| `type-maps/*.json` | The type maps class 10 and class 11 are asserted against. Three are derived from the reference schemas with a citation on every entry; one is authored for the synthetic fixtures and says so. |
| `fixtures/records/*.json` | Synthetic records for classes 5, 7, 13 and 15. Authored here; no reference sample is reproduced. |
| `fixtures/envelopes/*.json` | Envelopes for classes 14, 15 and 17. Generated. |
| `tools/` | Two independent implementations, the generator, the runner and the schema validator. |

**No reference schema or sample is copied into this repository.** Class 10 names the MOH samples by
module and export in a checkout that lives outside this repository by design, and
`tools/extract_reference_record.py` converts one to JSON text in a scratch directory when a runner
needs it.

## Running it

```sh
corpus/tools/run.sh --references /path/to/schemata --modules /path/to/node_modules
```

Both arguments are optional and their absence is reported rather than hidden.

- Without `--references`, class 10 reports `SKIPPED - NOT RUN` and contributes zero assertions. It
  never reports green unrun.
- Without `--modules` (holding `ajv@8` and `ajv-formats`), the JSON Schema validation step is
  skipped and says so. The repository has no package manifest, deliberately.

`run.sh` does four things, and the third is the one that matters:

1. implementation A rebuilds the corpus and compares it with the committed file;
2. implementation B recomputes every derived value in the corpus and rewrites it;
3. the two files are compared byte for byte;
4. every artifact is validated against the repository's JSON Schemas.

Step 1 alone would only prove that one program is self-consistent.

### Checking an implementation that is not one of these two

The runner to port is [`tools/check_corpus.mjs`](tools/check_corpus.mjs). It consumes every vector
class and nothing else, and it is written to be read as the specification of what conformance
means operationally. The procedure per class:

| Vector array | What an implementation must do |
|---|---|
| `encodePath` | `encodePath(segments)` equals `encodedHex`; the display path equals `displayPath`. |
| `encodeValue` | `encodeValue(tag, input)` equals `encodedHex`. |
| `reject` | The input MUST error. The `reason` is the reference reason code; an implementation with its own taxonomy should map to it rather than ignore it. |
| `salt` | `salt(path)` under `(masterSaltHex, recordId)` equals `saltHex`. |
| `leaf` | `leafHash(segments, tag, value, saltHex)` equals `leafHash`. |
| `tree` | `MTH(leafHashes)` equals `root`. |
| `inclusion` | Verifying `(leafHash, index, treeSize, auditPath, root)` returns `expect`. Generating the audit path for `index` reproduces `auditPath`. |
| `negativeProof` | Verification MUST fail. |
| `typeMap` | Resolving `segments` at `jsonKind` against `type-maps/<recordType>.json` yields `expectTag`, or fails closed when `expectFailClosed`. |
| `record` | Building the tree over `recordFile` yields `leafCount` and `root`. |
| `unlinkability` | Each side's leaf hash matches, and the two differ. |
| `envelope` | Verifying `envelopeFile` returns `expectAccept`, **and rejects for `reason`**. The reason is not decoration here: several fixtures are rejectable for more than one cause, so a boolean alone would pass an implementation that never ran the check the vector is about. `guard-reject-reserved-collision` is the clearest case - the record it carries cannot be hashed at all, so its envelope holds a placeholder root, and an implementation that skips the reserved-namespace guard rejects it on `root-mismatch` and looks correct. |

### Input escape forms

Three values cannot appear literally in a JSON file, so `input` may carry one of these instead of a
plain JSON value. Everything else is literal.

| Form | Means |
|---|---|
| `{"$utf16": ["0041", "d800"]}` | A string built from those UTF-16 code units. This is how an unpaired surrogate is carried: a conforming JSON writer cannot emit one as well-formed UTF-8. |
| `{"$segments": [ ... ]}` | A path. Used where the corpus schema's own `segments` definition cannot express the vector - see "Known corpus schema limits". A segment's `key` may itself be a `$utf16` object. |
| `{"$jsonText": "..."}` | Record text to be handed to the implementation's JSON reader, for rejections that happen at the parser boundary rather than at a tag. |

### How the tree class generates its leaves

Class 8 tests `MTH` and the RFC 9162 split rule, not leaf construction, so its leaves are
`SHA-256("ROAX-CORPUS/1.0.0/tree/<n>/<i>")`. A consumer never needs this rule, because every tree
vector carries its leaf hashes explicitly; it is written down so both reference implementations
regenerate identical trees. Inclusion and negative-proof vectors are derived from the tree vector
named `tree-n<size>`.

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
| 9 negative proof vectors | 11 | complete |
| 10 the three real MOH records | 2 | **partial - 1 of 3 records** |
| 11 the schema binding | 23 | complete. Includes the three unknown-algorithm and unknown-profile fail-closed vectors: specification section 12.2 calls that "the same rule section 4.2 applies to an unknown path, applied one level up", and section 4.2 is what this class tests. |
| 12 salt freshness and unlinkability | 9 | complete |
| 13 reference-schema hazards | 2 | **partial - the `$id` half is inexpressible** |
| 14 minimum-disclosure floor | 34 | complete |
| 15 reserved-namespace guard | 20 | complete |
| 16 Unicode version sensitivity | 20 | complete, at the strength class 16 itself states |
| 17 withheld-leaf salt | 8 | complete |

### Class 10 is partial, and the reason is a finding rather than an omission

Only the recovery healthcert has a vector. The vaccination and PDT samples **cannot be committed at
all** under the fail-closed rule of specification section 4.2, because their reference schemas do
not determine a ROAX type tag for every scalar those samples contain:

- **vaccination:** `notarisationMetadata.signedEuHealthCerts[*].dose` is declared `"type": "number"`
  with no pattern. ROAX has two numeric tags and JSON Schema's `number` chooses neither. FHIR's own
  lite schema distinguishes `integer` from `decimal` by **pattern**, both being `"type": "number"`,
  and the notarise schema carries no such pattern. `expiryDateTime` in the same object is declared
  with a `format` and `examples` and **no `type` at all**.
- **PDT:** its root object declares seven members and does not close itself, so `$template`,
  `attachments`, `issuers` and `notarisationMetadata` - all four present in its own shipped sample -
  are permitted and undeclared. That is twenty unbound `(pattern, jsonKind)` pairs.

Binding either would be an authored ruling, and an authored ruling inside the corpus is the exact
defect `docs/conformance-corpus.md` section 1.2 forbids: every implementation built against the
corpus would inherit it as though it were settled. So those paths appear as class 11 **fail-closed**
vectors, which is a real assertion on real paths, and the roots wait for a ruling.

`tools/build_type_maps.py` produces the vectors the moment the bindings exist. Nothing else is
blocking.

### Class 13 is partial

The flattened-versus-normalized FHIR entry layout is covered, as a synthetic pair proving the two
layouts produce different roots. The other half - loading the PDT and recovery schemas together and
asserting recovery's rules still apply despite its `$id` pointing at PDT's path - is a JSON Schema
**loading** property with no hash in it, and `schemas/conformance-corpus-1.0.json` has no vector
type that can express it. It is enforced in `tools/build_type_maps.py`, which resolves `$ref` by
file path and never registers a schema by `$id`, and the two colliding `$id` values were confirmed
by reading them.

## What was actually measured, and what was not

**The corpus was generated twice, in two languages, and the outputs are byte-identical.**
Implementation A is [`tools/roax_ref.py`](tools/roax_ref.py) (Python 3.13), implementation B is
[`tools/roax_ref.mjs`](tools/roax_ref.mjs) (Node 22). B was written from the specification text
rather than ported from A. They share no code, and they differ where it counts:

| | implementation A | implementation B |
|---|---|---|
| JSON reader | `json.loads` with `parse_int`, `parse_float` and `object_pairs_hook` | a hand-written scanner, because `JSON.parse` cannot preserve duplicate keys |
| Numbers | verbatim literal text, arbitrary precision | verbatim literal text, arbitrary precision |
| NFC tables | Python 3.13.5, **Unicode 15.1.0** | Node v22.21.0 / ICU 77.1, **Unicode 16.0** |
| Byte handling | `bytes`, `int.to_bytes` | `Buffer`, `writeUInt32BE`, `BigInt` for `u64be` |
| Sort | `list.sort` over `bytes` | `Array.sort` with `Buffer.compare` |

The Unicode row is worth reading twice. The corpus pins Unicode 15.1 and was **generated under
15.1.0 tables**; implementation B agreed on every vector while running **16.0** tables. That is a
demonstration that these particular vectors are stable across that release boundary. It is not a
demonstration that a version mismatch is detectable, which class 16 already says it is not, because
no character whose NFC form changed between releases has been identified for this corpus.

**Gate 3 of `docs/conformance-corpus.md` section 2 is NOT discharged.** That gate requires an
implementation written by a different author, from the specification text alone, to pass the corpus
unmodified. Both implementations here have one author, so they share one reading of the
specification, and a shared misreading is exactly what a corpus exists to catch. What two
implementations in two languages do catch is transcription slips and language-API divergence, and
they caught one - see below. Scope the claim to that.

### The prior canonicalization research was used narrowly, and here is exactly how

That work built five implementations that produced identical roots on the three real MOH records.
**None of its whole-record roots transfer, and none were used.** It predates the reserved leaf set,
used a bare `ROAX-CANON/1` domain string rather than the algorithm-qualified one, and used a salt
preimage with no length prefixes and no `recordId` in it. Each of those changes every leaf hash in
every record, so its 87-, 130- and 65-leaf roots are not comparable with anything here.

Two things from it agree with this work, and both were read before this work was done, so they are
corroboration and not blind agreement:

- the `encodePath` hex for the nested-versus-dotted collision pair, which matches
  `path-nested-a-b` and `path-literal-dotted-key` here;
- the record leaf counts 87, 130 and 65, which this work also gets by enumerating the samples.

Nothing was copied. Everything in this corpus was derived from `docs/spec/roax-canon-1.md`.

### The divergence the two implementations caught

Python's `$` in a regular expression also matches immediately before a trailing newline;
JavaScript's matches only at end of input. Implementation A's first draft anchored the section 6.2
number grammars with `^...$` and therefore **accepted `"1.0\n"` and canonicalized it**, while
implementation B rejected it. Both grammars are now anchored `\A...\Z`, and
`reject-decimal-trailing-newline` and `reject-integer-trailing-newline` pin it. Any implementation
written in a Python-family regex dialect has this bug until it is looked for.

## Known corpus schema limits

Two places where `schemas/conformance-corpus-1.0.json` cannot express something
`docs/conformance-corpus.md` requires. Both are worked around visibly rather than silently.

1. **Class 6 requires an array index at `2^32` that MUST be rejected**, but `rejectVector.segments`
   resolves to `#/$defs/segments`, whose index `maximum` is `4294967295`. The vector therefore
   cannot be written through `segments`, and `reject-index-at-2-32` carries it in the unconstrained
   `input` field as `{"$segments": [{"index": 4294967296}]}` instead.
2. **Class 13's schema-`$id` half has no vector type**, as described above.

A third, smaller one: `typeMapVector` identifies its map by `recordType` alone, with no file
reference and no `schemaVersion`, so the runner resolves it by the convention
`corpus/type-maps/<recordType>.json`.

A fourth, which is only a naming gap: there is no class for "an unknown algorithm or an unknown
profile fails closed", which specification sections 7.4 H3 and 12.2 both require. Those three
vectors are filed under class 11 for the reason given in the coverage table, rather than left
untagged where the gap check would not see them.

## Specification ambiguities found

Recorded rather than decided. Every one of them is unobservable across the shipped vectors, which is
deliberate: a vector that discriminated would settle the question from inside the corpus.

1. **The 1024-digit bound's scope.** Specification section 6.2 states it under *Canonical decimal*,
   but its own justification paragraph counts "class 2's 40-digit integer" against it. Both
   implementations apply it to INTEGER as well as DECIMAL. No vector discriminates.
2. **What the 1024-digit bound counts.** "the expanded positional form" is read here as the padded
   form *before* the output-grammar normalization, which is the literal reading and the
   memory-safe one. Under the other reading `0e99999` canonicalizes to `0`; under this one it is
   rejected. No vector carries `0e99999`.
3. **`recordId` is not normalized in the salt preimage.** Section 7 writes `RID = utf8(recordId)`,
   not `utf8(NFC(recordId))`, while the reserved leaf `roax.recordId` is a STRING and therefore *is*
   normalized. Every corpus record identifier is ASCII, so the two readings agree throughout.
4. **Type-map matching is not stated to be over normalized keys.** Section 11.2's general rule -
   "check the bytes you commit, not the bytes you received" - says it should be, and both
   implementations normalize. The synthetic type map carries the Kelvin key under **both** spellings
   so that `record-guard-kelvin-key` resolves identically either way.
5. **The type-map `pattern` field is display notation**, so it cannot address a key containing `.`,
   `[` or `]` - keys section 5 deliberately admits with no rejection rule. `a.**` reaches such a key
   without the pattern language growing an escape, and both implementations reject an ambiguous
   pattern rather than mis-parse it.

## One substantive specification finding

**Specification section 11.1's claim that `leafCount` is self-binding in a disclosed copy does not
hold.** It says tree shape is uniquely determined by the number of leaves, "so a wrong `leafCount`
makes the audit path fail". Measured, on an 8-leaf tree:

```
  internal node MTH(L[0:4]) presented as a leaf at index 0
    with the TRUE tree size 8      -> verification FAILS   (correct)
    with a FORGED tree size 2      -> verification SUCCEEDS
```

RFC 9162 section 2.1.3.2 consumes `tree_size` as an input, so an attacker who controls `leafCount`
controls the shape the verifier reconstructs. What actually blocks the attack is specification
section 10 step 1 - recompute the leaf hash from the disclosed fields rather than trust a supplied
one - plus second-preimage resistance, since the attacker would need a `(path, tag, value, salt)`
hashing to the internal node. That defence is already normative and already load-bearing; the
`leafCount` sentence overstates a second one that is not there.

`negative-internal-node-as-leaf` and `negative-internal-node-as-leaf-n130` carry the honest form -
the true tree size, where RFC 9162 does reject - because that is what the specification requires
today. Changing the sentence in section 11.1 would be a specification change and is not made here.

## Decisions this corpus does and does not presume

`docs/conformance-corpus.md` section 1.2 requires a field-by-field audit. Done once, here.

| Field | Presumes | Resolution |
|---|---|---|
| `recordVector.masterSaltHex` | D4 salt strategy | **OPTIONAL** and left optional. It is present on every vector because these vectors were built under D4a, and a D4b implementation reads the salts from the record's envelope and ignores it. |
| `saltVector.masterSaltHex`, `unlinkabilitySide.masterSaltHex` | D4 | **REQUIRED**, correctly. Class 12 is the class where master-salt freshness *is* the assertion, so the value is its subject rather than an assumption. |
| Leaf ordering in every `record`, `tree` and `envelope` vector | D5 leaf ordering | Encoded-path order, per specification section 9. There is no root without an ordering, so class 8 and class 10 are inexpressible otherwise. The specification governs (section 1.1) and this is derived from it, not decided here. |
| `typeMapVector.expectFailClosed` | D7 unknown paths | Fail-closed, per specification section 4.2, which states the rule normatively and records that it is the recommended answer to D7. Same resolution as D5. |
| NFC in every string and key vector | D12 normalization | NFC with a pinned Unicode version, per specification section 6.1. Same resolution. |
| `hashAlg` | B, ruled | `SHA-256`. See below. |

Nothing here binds a `number` to a numeric tag, adds a default tag, or requires `masterSalt` in any
envelope.

## Why there is no Poseidon-BN254 corpus

`schemas/conformance-corpus-1.0.json` carries `hashAlg` at the top level as a single value, so one
corpus file is one algorithm by construction, and a second file would be the way to add one. It
cannot be written yet. `ROAX-CANON/1` **registers** `Poseidon-BN254` and **defines** no construction
for it: the field, the rate and capacity, the round constants, and - the part the byte layouts in
specification sections 7 and 8 do not survive without - the encoding from a length-prefixed byte
string to field elements are all unpinned, and section 7.4 states normatively that a record MUST NOT
be issued against it until a revision pins them.

`algorithm-poseidon-fails-closed` therefore asserts the behaviour that *is* required today: a v1
verifier's allow-list excludes it and it fails closed with a stated reason (section 7.4, H3).

## The synthetic profile

`org.roax.corpus.synthetic` is a `recordType` that exists only inside this corpus. It is
syntactically valid under the envelope schema's reverse-DNS pattern and is deliberately **not** in
the `docs/profiles/` registry, so a record MUST NOT be issued under it. It exists so that structural
vectors do not have to borrow a real health authority's profile identifier, and so that authored
type-map bindings are never mixed into a map that claims schema provenance.
