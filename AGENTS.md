# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test,
release, architecture, and sharp-edge notes that should travel with the code.

## What this repository is right now

Specification, schemas, and the conformance corpus. **No library code has been written, and that is
deliberate.** The specifications exist so the design can be reviewed before five language
implementations exist to be re-litigated.

Do not add a Rust crate, TypeScript package, Go module, Swift package or Kotlin library without an
explicit instruction to do so.

`corpus/tools/` holds two small reference implementations, in Python and in plain `.mjs`. **They are
corpus tooling and they are not roax-lib.** They exist to generate and check the vectors and they
are deliberately parser-only, error-code-only and unoptimized. They are also why there is no
`package.json`: a TypeScript package here would read as the beginning of a library. If you need a
third implementation for cross-checking, add another single-file one; do not promote these.

## This repository is PUBLIC

Consequences that have already bitten once during authoring:

- No task identifiers, no internal team vocabulary, no absolute paths into anyone's home directory
  or into internal working trees.
- The reference schemata at `references/` are **third-party and must never be committed.**
  `.gitignore` excludes `references/` and `schemata/`. Cite them by relative path plus the upstream
  commit; never copy a schema in, not even a fragment.
- dogtag is an internal repository. Cite it as `dogtag-mono-repo` with file and line, and do not
  link it.

## Sharp edges in the design itself

These are the things a future agent is most likely to get wrong.

- **Four base type maps are published in `type-maps/`.** They were generated from the pinned
  reference checkout by `tools/build-type-maps.mjs`, which loads schemas by file path rather than
  `$id`. Neither regeneration nor `--check` runs today - both fail closed on the object-branch
  disagreements described below - so the committed bytes are authoritative and
  `tools/check-type-maps.mjs` is what verifies them. Their exact coverage and unresolved paths are
  in `docs/type-maps.md`. Do not infer a tag syntactically for any unbound path - decision D7
  requires it to fail closed.

- **The operative type-map matcher is a structured-path DFA, not a display-pattern table.**
  Resolve NFC-normalized KEY and INDEX segments, then select one output by observed JSON kind.
  A missing transition or output fails closed. The map must authorize a path before the flattener
  emits EMPTY_ARRAY or EMPTY_OBJECT, or an unknown empty extension bypasses D7.

- **The exact effective type map is committed per record.** The envelope's `typeMap.id` selects
  immutable artifact bytes and is itself committed at the single-segment reserved path
  `KEY("roax.typeMap.id")`. The semver is exact metadata, not a latest-version selector. Issuer
  extensions are materialized, single-parent, issuer-scoped and additive; they never override an
  inherited transition or output. See specification section 4 and `docs/type-maps.md` sections 3
  through 5.

- **Issuer extensions need executable validation, not only a carrier schema.**
  Run `tools/check-type-map-extension.mjs` against the exact parent and child.
  It checks logical DFA additivity, exact parent identity, issuer scope, extension-point containment,
  canonical reachability and provenance-reference linkage.
  Every selector must cite an immutable supplemental source, and its materialized binding must cite
  every evidence source by `sourceId`.
  Publication review still retrieves each source and verifies its commit or content digest.
  Its `--self-test` mode covers those rejections without any external artifact.

- **An extension point does not open the whole subtree beneath it.** A `prefix` admits only two
  selector shapes: a segment the base map does not declare at that prefix state, and then anything
  below that untyped subtree; or a direct child of the prefix, exactly one segment deeper, that has
  no binding for the observed kind **and carries an explicit `unresolved` row naming that kind**,
  such as vaccination `dose`. So the PDT and recovery empty root prefixes reach undeclared root
  properties, not the shared lite FHIR Bundle, and no issuer can privately bind `base64Binary` or
  `Narrative.div`. Rebinding a declared path is a base-map revision. See `docs/type-maps.md`
  section 5.

- **`unresolved` rows are operative for the extension lifecycle, not just audit prose.** They gate
  shape 2 above, so silence is not eligibility: PDT `type` has no `array` binding and no row, and is
  therefore not extensible. A child must carry every inherited row unchanged except for kinds it
  resolves with a binding - it may not invent a row, restate one with its own evidence, or drop one
  it did not resolve. Do not describe them as purely non-operative anywhere.

- **`tools/check-type-maps.mjs` is the only checker that runs against the committed tree.**
  `build-type-maps.mjs --check` needs the gitignored reference checkout and still fails closed on
  the 34 object-branch disagreements once it has one; this one needs neither and passes.
  It recomputes the content IDs, validates the four artifacts and the registry against their JSON
  Schemas, exercises both branches of the artifact schema's `parentTypeMapId` conditional in both
  directions, reuses `validateArtifact` from the extension checker rather than re-encoding the
  carrier rules, and pins a set of operative and fail-closed bindings.
  It needs Ajv 8 and `ajv-formats` installed outside the tree and named by `ROAX_AJV`;
  `--skip-schema-validation` runs the dependency-free subset. See `docs/type-maps.md` section 6.

- **The FHIR schemata use object keywords without declaring object type.**
  The full schema has 659 reached object-applicator source nodes with no `type: "object"`, and the
  Bundle-reachable lite scope has 65.
  The maps retain KEY traversal, mark the affected states as non-operative audit gaps, and never
  infer a scalar, array or null tag from an inapplicable object keyword.
  See `docs/type-maps.md` section 1.5.

- **The generator rejects schema intersections and mixed empty-container permission, for objects
  and arrays alike.** Its DFA closure can safely union the pinned `anyOf` and `oneOf` path
  languages only because complete profile validation runs first.
  An `allOf` needs intersection-aware compilation, and container branches that disagree on whether
  empty is admitted need combinator-aware evaluation, so `tools/build-type-maps.mjs` fails instead
  of publishing a guessed EMPTY_OBJECT or omitting a valid EMPTY_ARRAY.
  EMPTY_ARRAY and EMPTY_OBJECT are distinct leaves, so a permissive union is silent widening.
  **Both comparisons select a branch by container-ness, which is the declared type OR the
  applicator keyword**: `type: "object"` or `properties` on the object side, `type: "array"` or
  `items` on the array side, which are the same keywords `classifyNode` already treats as container
  markers when it declines to tag a node. Selecting on the declared type alone drops
  `{"items": {...}, "minItems": 1}` out of the comparison, and selecting on the applicator alone
  drops `{"type": "object", "required": ["x"]}`; either way the surviving permissive branch
  publishes an empty-container leaf unopposed, which is the widening itself.
  **The admission predicates must cover every keyword of the pinned dialect that can forbid the
  empty container, or the comparison compares the wrong answer.** For objects that is a non-empty
  `required` and `minProperties`; `dependencies` and `propertyNames` pass vacuously on `{}`. For
  arrays it is `minItems` **and `contains`**, because draft-06 section 6.14 and draft-07 section
  6.4.6 both require at least one matching element and `[]` has none. A node whose only container
  keyword is `contains` needs no selector clause: `classifyNode` leaves it unresolved for every
  kind, and an unresolved kind suppresses that kind's binding, so the state already fails closed.
  **The three sets are not the same set, and the object and array sides differ.** The COMPARISON is
  the widened container-ness set on both. TRAVERSAL is narrow on both: `keyGroups` skips a selected
  branch declaring no `properties`, and `anyIndex` comes only from the `items` of `type: "array"`
  branches. EVIDENCE differs - an EMPTY_ARRAY binding cites only `type: "array"` branches, because
  an `items` keyword on an untyped node constrains arrays without asserting the instance is one and
  inferring a tag from an inapplicable keyword is what section 1.5 of `docs/type-maps.md` forbids,
  whereas an EMPTY_OBJECT binding cites the widened set, so a bare `{"type": "object"}` is cited.
  That is not the same defect: a declared `type: "object"` does assert object-ness, so the tag still
  comes from declared schema evidence. `expectNoTag` pins the array half.
  `--self-test` proves both rejections against constructed schemas and needs no reference checkout,
  and on each side one case drops the applicator from a branch and another drops the declared type,
  so both halves of both disjunctions are pinned rather than assumed.

- **The object rejection above means the four published artifacts can currently be neither
  regenerated nor `--check`ed, and that is the ruled trade.** `--check` compiles before it
  compares, so it fails on the same states.
  Measured on the pinned checkout, it fires on 34 states: 30 full
  FHIR, 2 PDT, 2 recovery, 0 vaccination. **That count is now a LOWER BOUND**: it was measured
  under the earlier declared-type-only and `properties`-only branch selections, and widening both
  to container-ness can only add branches to a state's comparison, never remove one. The array
  comparison was widened after that measurement too, so the bound now covers array states as well.
  It has not been re-measured
  because `references/` is gitignored, and regeneration is blocked either way.
  The first merges `ImplementationGuide_Definition`, which
  requires `resource`, with `Reference`, which admits `{}`. Do not "fix" this by restoring the
  permissive union - that ruling was raised with this measurement and reaffirmed. The committed
  artifacts and their content IDs stay authoritative and `tools/check-type-maps.mjs` still passes
  on them; what is open is how to evaluate those 34 merged states combinator-aware so regeneration
  works again. Note the detected condition is broader than the strictly `oneOf`-unsound one: with
  one permitting and one requiring branch, `{}` is valid under both combinators, whereas two or
  more branches all permitting `{}` is the case `oneOf` actually rejects.

- **Numbers are never parsed through a float.** Anywhere. This is the whole point of the design;
  see `docs/decisions.md` part 0. In test vectors and JSON Schemas, INTEGER and DECIMAL values are
  carried as **strings**, because a JSON number in a vector file would be destroyed by the very
  parser under test.

- **Trailing zeros in decimals are significant.** `0.010` is not `0.01`. FHIR R4 says SHALL. dogtag
  strips them (`crates/dogtag-standard-rs/src/encode.rs:51-59`) and ROAX deliberately does not. If
  you port anything from dogtag's `encode.rs`, this is the line to change.

- **The display path is never hashed.** `a.b[0].c` is for humans. Hashing uses the length-prefixed
  structured encoding (spec section 5). Never reconstruct a path by parsing a display string.

- **The leaf set is a union, not the record.** Reserved `roax.*` leaves join the record's leaves
  before the sort (spec sections 3.3 and 11.2). A flattener that walks the record only produces a
  different root. Each reserved path is a **single `KEY` segment carrying the literal dotted name**,
  so `roax.recordType` is one segment `KEY("roax.recordType")` and *not* two. There are five
  mandatory reserved leaves, including `roax.typeMap.id`, plus `roax.issuer.keyId`, which is the one
  conditional leaf: absent means no leaf, not a NULL leaf. The tree floor is therefore 6.

- **The reserved-namespace guard tests the NFC-normalized key of the FIRST segment** for the ASCII
  prefix `roax.` (spec section 11.2). Three ways to get it wrong: reconstructing a display path to
  run it (the section 5.2 trap), applying it to every segment rather than the first, and checking
  raw bytes before NFC. A key named `roax` or `roaxX`, with no dot, is **accepted** - it collides
  with nothing.

- **`DOMAIN` is algorithm-qualified:** `"ROAX-CANON/1/" + hashAlg`, not a bare `"ROAX-CANON/1"`
  (spec sections 7, 7.4, 8). But `hashAlg` is **not** a leaf and must never become one: a leaf is
  hashed under the algorithm it names, so it cannot bind it. Authority comes from the anchoring
  registry and the verifier's allow-list. Only SHA-256 has a defined construction; Poseidon-BN254
  is registered but unparameterized and MUST NOT be issued against.

- **Version identifiers defined elsewhere are opaque** and carry no shape constraint: `schemaVersion`
  and `unicodeVersion` are matched for equality, never parsed or ordered (spec section 12.1). No
  dotted-numeric pattern accepts even FHIR's own 22 `fhirVersion` values. ROAX's own artifacts,
  `corpusVersion` and `typeMapVersion`, keep semver. Do not harmonize the two groups.

- **An unresolved path is bound by a ruling, not by a resolver improvement.**
  Under the fail-closed rule of specification section 4.2, two of the three real MOH samples are uncommittable today.
  Vaccination is blocked on `dose`, declared `"type": "number"` where ROAX has two numeric tags, and on `expiryDateTime`, declared with a `format` and examples and no `type` at all (`docs/type-maps.md` section 1.1).
  PDT is blocked on the 20 endorsed-sample `(pattern, kind)` pairs its open root leaves undeclared (`docs/type-maps.md` section 1.2).
  Recovery is the one whose sample commits, which is why class 10 has a vector for it alone (`corpus/README.md`), and that is a statement about the sample rather than about full coverage: the recovery base map carries the same five unresolved lite-FHIR slots as PDT (`docs/type-maps.md` sections 1.3 and 2.2).
  A ruling lands in `docs/decisions.md` and the type map together.
  Do NOT quietly bind `number` to a tag to make class 10 green: `docs/conformance-corpus.md` section 1.2 exists because that kind of fix decides an open question from inside a data file.
  Note the tool split when citing any of this: `corpus/tools/build_type_maps.py` is corpus-side and writes the vectors' maps, while the published `type-maps/` artifacts come from `tools/build-type-maps.mjs`.

- **The corpus may not require what the design has not decided.** A required corpus field that
  presumes one side of an open decision silently rules it (`docs/conformance-corpus.md` section
  1.2). This happened twice with `masterSalt` before decision D4 was ruled. The rule still binds,
  because decisions A, C and D are still open.

- **There is no master salt and no KDF. Every salt is an independent CSPRNG draw of 16 bytes**
  (spec section 7, decision D4 ruled D4b on 2026-07-28). Do not reintroduce derivation, and do not
  put the record identifier into any preimage - it was in the salt preimage of an earlier draft and
  is not any more. The 128-bit entropy floor is normative: it is the only thing standing between a
  withheld low-entropy leaf and a dictionary search.

- **An envelope carries per-leaf salts and nothing a salt could be derived from.** A full copy
  carries the salt of *every* leaf in a `salts` array; a disclosed copy carries the salt of *only the
  leaves it reveals* (spec section 7.3). Both are load-bearing. Dropping the first makes a full copy
  unverifiable; breaking the second leaks every withheld low-entropy field to a dictionary search in
  an envelope that still verifies correctly. Rule 3 of that section forbids any seed field, which is
  vacuous today and binds any revision that brings derivation back.

- **`roax.recordId` is mandatory to disclose by policy, not by arithmetic.**
  `roax.recordType`, `roax.schemaVersion` and `roax.typeMap.id` are arithmetic because they select
  and authenticate the exact map. This changed with the D4b and type-map binding work, and several
  documents said otherwise before it. A verifier that never receives `roax.recordId` can still
  verify every leaf it did receive.

- **`leafCount` is NOT authenticated in a disclosed copy**, and the specification claimed otherwise
  until this was measured. RFC 9162 section 2.1.3.2 takes the tree size as an *input*, so an attacker
  supplying both a leaf hash and a tree size can walk an internal node to the genuine root: on an
  8-leaf tree, `MTH(L[0:4])` at index 0 with a forged size of 2 verifies. What actually defends is
  spec section 10 step 2 - recompute the leaf hash from the disclosed fields, never accept one - plus
  the `0x00` leaf-domain byte. Never add a check that leans on `leafCount` in a disclosed copy.
  Spec section 11.1 owns the full measurement and correction.

- **Type tag 8 `BLOB_REF` is defined and selected by nothing.** The schemas accept it so the carrier
  form is pinned once; an implementation MUST reject any record or type map that uses it until a
  profile declares the binding (spec section 6.5). Same treatment as `Poseidon-BN254`: registered,
  forbidden in issuance. Base64 is pinned to RFC 4648 section 4 with padding and no line wrapping,
  and that governs `BYTES` and `BLOB_REF` rather than the explicitly typed healthcert fields bound
  as STRING. FHIR `base64Binary` remains unresolved between STRING and BYTES.

- **The vaccination healthcert's `fhirBundle.entry[]` is flattened pseudo-FHIR**, not a real FHIR
  Bundle. Normalizing it to the genuine `entry[i].resource` shape changes every path and therefore
  every root, which silently breaks existing commitments. See
  `docs/profiles/vaccination-healthcert.md` section 2.1.

- **Do not resolve the reference schemas by `$id`.** Two of them carry copy-pasted `$id` values:
  recovery points at PDT's path, and vaccination points at a PDT interim path. A validator that
  registers both by `$id` silently applies the wrong rules. Load by file path.

- **A minimum-disclosure floor is SEGMENTS, never display notation.** This is the section 5.2
  display-path trap one layer above hashing, and it has already been made once here. The
  `docs/profiles/` tables print non-redactable paths for humans, so
  `notarisationMetadata.reference` reads as one token and is **two** segments. A floor holding the
  dotted string as a single `KEY` asks for a leaf no record has, so it matches nothing and the
  floor is *silently unenforced* while every fixture built the same way agrees with it. Reserved
  paths are the one genuine single-dotted-key case (spec section 11.2). Carry a floor as segments
  so the mistake cannot be written.

- **The envelope's outer identity is not authority and must be bound to the reserved leaves.**
  Section 11.3 says fields outside the root are hints; section 11.2 commits `recordType`,
  `schemaVersion`, `typeMap.id`, `recordId` and `issuer.id` as leaves so a disclosed copy can be
  checked against them.
  The outer `recordType` is what SELECTS the profile floor, and PDT's floor is a strict subset of
  recovery's, so an unbound one lets a holder relabel a recovery copy as PDT, withhold
  `validUntil`, and still have every inclusion proof verify against the genuine root. Compare under
  NFC on both sides: a STRING leaf commits its normalized form. `roax.issuer.keyId` MUST NOT be
  bound - it is the conditional leaf.

- **The binding runs BEFORE the minimum-disclosure floor, and the floor is selected from the
  COMMITTED `roax.recordType` leaf.** Derived from section 11.3, not chosen: authority has to be
  established before an outer field selects anything, and floor-then-bind is trust-then-verify.
  The consequence is load-bearing and is pinned by 16 vectors of the committed corpus - because
  absence of a reserved leaf now trips the binding, the reserved half of the floor is unreachable
  and every `floor-<profile>-omits-roax-*` vector asserts `outer-identity-mismatch` rather than
  `minimum-disclosure-floor`. Do not "simplify" by enforcing the floor first; do not trim the
  reserved paths out of the floor table either, since class 14 defines the floor as the reserved
  paths plus the profile's.
  Those 16 are four reserved paths across four profiles because the committed corpus predates
  `roax.typeMap.id`, while class 14 now defines five reserved paths; closing that difference is
  corpus-rebuild work and not a reason to trim the table.
  `profile-unknown` stays ahead of both: it is the verifier's own allow-list, not a policy choice.
  See `corpus/README.md`.

## The conformance corpus

`corpus/` holds it. `corpus/README.md` is the operative document: coverage per class, the runner,
the ambiguities found and what was actually measured. Read it before touching a vector.

```sh
corpus/tools/run.sh --references /path/to/schemata --modules /path/to/node_modules
```

Both flags are optional and their absence is reported, never hidden. Things to know:

- **A vector is never hand-written.** `corpus/tools/corpus_plan.py` carries INPUTS only; every
  expected hash, root, audit path, resolved tag and accept/reject verdict is computed. A value
  typed in by hand would be agreed on by both implementations without either having computed it,
  which is the whole failure mode the corpus exists to prevent.
- **The two implementations must stay independent.** `roax_ref.py` and `roax_ref.mjs` were written
  from the specification separately, and they use deliberately different mechanisms - stdlib JSON
  hooks against a hand-written scanner, `bytes` against `Buffer`, Unicode 15.1 tables against 16.0.
  Porting one to the other would make `run.sh` step 3 pass while proving nothing.
- **Python's `$` also matches before a trailing newline; JavaScript's does not.** Anchor every
  grammar in section 6.2 with `\A`/`\Z`. The first draft of implementation A accepted `"1.0\n"` and
  canonicalized it. `reject-decimal-trailing-newline` pins it.
- **Class 10 is 1 of 3 records** and class 13 is half, both for reasons recorded in
  `corpus/README.md`. Do not fill either in without reading why they are short.
- **`org.roax.corpus.synthetic` is a corpus-only `recordType`.** It is not in the `docs/profiles/`
  registry and must never be issued against. It exists so structural vectors do not borrow a real
  health authority's identifier and so authored type-map bindings never mix into a map that claims
  schema provenance.

## Documentation conventions in force here

- No em dashes. Use a plain hyphen.
- In long Markdown, put each full sentence on its own line.
  It keeps diffs readable when a single sentence changes.
  This is the target rather than a description of the repository as it stands.
  The files here are currently hard-wrapped at roughly 100 columns and put several sentences on a line, so adoption is incremental.
  Hold new and substantially rewritten prose to the convention.
  Do not reflow a file wholesale as a side effect of an unrelated change, because the cosmetic diff buries the real one.
- **Every normative claim carries a citation:** specification name, version and section for
  standards; file and line for code. Where something is inferred rather than confirmed, the text
  says so in the sentence. Keep this - the documents are written to be checkable rather than
  trusted, and a reader who spot-checks one uncited claim loses confidence in all of them.

## The open decisions are open on purpose

`docs/decisions.md` holds four decisions belonging to the project owner (A, B, C, D) plus ten more.

**Only three are still open, and all three are the owner's: A, C and D.** B was ruled earlier - both
hash families are first-class and selectable per record - and what stays open under it is the
`Poseidon-BN254` parameterization. **The ten engineering decisions D3 through D13 were ruled on
2026-07-28** and the specification is written on those rulings rather than on a recommendation; see
specification section 15 for the table of where each lands. Eight confirmed what the specification
already said. Two changed it: D4 to independent per-leaf salts, and D9 gaining the `BLOB_REF` binding.

**Do not resolve A, C or D in code or prose without an explicit ruling**, and if one is ruled, update
`docs/decisions.md` in the same change rather than only the specification. A decision that looks
settled in the spec but is still marked OPEN in the decisions document is worse than either. Part 1's
A, C and D sections are the owner's and are not edited by ruling work elsewhere in the document.

## Validating the schemas

There is no CI and no package manifest. The JSON Schemas were checked with Ajv 8 in **strict mode**
plus `ajv-formats`, and all seven compile clean. Re-check after any edit: install `ajv` and
`ajv-formats` outside the tree, then `new Ajv2020({strict: true}).compile()` each of the seven files,
using the `ajv/dist/2020.js` entry point because they are draft 2020-12. Compiling is not enough on
its own for a conditional - validate instances both ways, since an `if`/`then` that never fires
compiles perfectly and asserts nothing.

**The envelope and the corpus vector file each have two live schema versions, and the pair is not a
leftover.** `schemas/envelope-2.0.json` and `schemas/conformance-corpus-2.0.json` carry the type-map
binding and the six-leaf floor, and are what the specification and `docs/type-maps.md` describe.
`schemas/envelope-1.0.json` and `schemas/conformance-corpus-1.0.json` govern the corpus artifact and
the 54 envelope fixtures as committed, which `corpus/tools/validate_schemas.mjs` measures.

**The two files differ in what stayed behind, and the difference is deliberate.**
`schemas/envelope-1.0.json` is unchanged in meaning: the D4b ruling altered no envelope bytes, so
only its descriptions moved, and its floor stays at five reserved leaves where the successor's is
six. `schemas/conformance-corpus-1.0.json` was **migrated in place** instead, because the D4b ruling
did change the vector shapes: `saltVector`, `unlinkabilitySide` and `recordVector.masterSaltHex` are
deleted, `saltsFile` and `normalizationVector` are added, and the committed corpus was rebuilt in the
same change. The same-change rule in specification section 1.1 and `docs/conformance-corpus.md`
section 1.1 is why: a canonicalization change lands with the vectors that assert it, and leaving the
deleted derivation expressible in the file that governs the artifact would have left the corpus
implementing a construction the specification no longer has. Do not tighten the 1.0 files any
further without rebuilding what they govern in the same change. The schema version is not the
canonicalization version - both envelope schemas pin `canon` to `ROAX-CANON/1`.

Two things to know if you touch them:

- Ajv's `strictRequired` rejects `required` inside a `not`/`anyOf` subschema unless the same
  subschema also lists those properties. The schemas carry no-op `"properties": {"x": true}`
  annotations for exactly this reason. They are not redundant - removing them breaks strict
  compilation.
- Union types (`"type": ["string","boolean"]`) trip `strictTypes`. The envelope pins each value type
  per tag in its `allOf` conditionals instead, which is more precise anyway.
