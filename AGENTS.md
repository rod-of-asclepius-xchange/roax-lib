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

- **The type map does not exist.** The specification requires it (section 4) and the design is
  unsafe without it, because type tags MUST come from the schema and not from JSON literal syntax.
  Building it is on the critical path and is the single largest gap. Do not write a library that
  infers tags syntactically "for now" - that is the exact bug this project exists to remove.

  `corpus/tools/build_type_maps.py` now derives one per healthcert family from the reference
  schemas, and what it found is the sharpest open item in the project:

  - **recovery** binds completely, 50 of 50 `(pattern, jsonKind)` pairs.
  - **vaccination** leaves two unbound. `signedEuHealthCerts[*].dose` is declared `"type": "number"`
    with no pattern, and ROAX has *two* numeric tags, so JSON Schema `number` chooses neither. FHIR
    itself distinguishes `integer` from `decimal` by **pattern**, both being `"type": "number"`;
    the notarise schema carries no pattern. `expiryDateTime` is declared with a `format` and
    `examples` and **no `type` at all**.
  - **PDT** leaves twenty unbound. Its root object declares seven members and does not close
    itself, so `$template`, `attachments`, `issuers` and `notarisationMetadata` - all four in its
    own shipped sample - are permitted and undeclared.

  **Under the fail-closed rule of specification section 4.2, that makes two of the three real MOH
  samples uncommittable today.** Binding them needs a ruling, not a resolver improvement, and the
  ruling must land in `docs/decisions.md` and the type map together. Do NOT quietly bind `number`
  to a tag to make class 10 green: `docs/conformance-corpus.md` section 1.2 exists because that
  kind of fix decides an open question from inside a data file.

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
  so `roax.recordType` is one segment `KEY("roax.recordType")` and *not* two. There are four
  mandatory reserved leaves plus `roax.issuer.keyId`, which is the one conditional leaf: absent
  means no leaf, not a NULL leaf. The tree floor is therefore 5.

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

- **The corpus may not require what the design has not decided.** A required corpus field that
  presumes one side of an open decision silently rules it (`docs/conformance-corpus.md` section
  1.2). This has already happened twice with `masterSalt`.

- **`masterSalt` MUST NEVER appear in any envelope**, full or disclosed. What an envelope carries is
  per-leaf salts: a full copy carries the salt of *every* leaf in a `salts` array, a disclosed copy
  carries the salt of *only the leaves it reveals* (spec section 7.3). Both rules are load-bearing.
  Dropping the first makes a full copy unverifiable; breaking the second leaks every withheld
  low-entropy field to a dictionary search in an envelope that still verifies correctly.

- **Per-leaf carriage is not a ruling on decision D4, which is OPEN.** Requiring `masterSalt` in an
  envelope would be, because D4b has no `masterSalt` at all. Salts are generated by the library from
  a CSPRNG and are never data an issuing institution supplies or collects.

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
  `schemaVersion`, `recordId` and `issuer.id` as leaves so a disclosed copy can be checked against
  them. The outer `recordType` is what SELECTS the profile floor, and PDT's floor is a strict
  subset of recovery's, so an unbound one lets a holder relabel a recovery copy as PDT, withhold
  `validUntil`, and still have every inclusion proof verify against the genuine root. Compare under
  NFC on both sides: a STRING leaf commits its normalized form. `roax.issuer.keyId` MUST NOT be
  bound - it is the conditional leaf.

- **The binding runs BEFORE the minimum-disclosure floor, and the floor is selected from the
  COMMITTED `roax.recordType` leaf.** Derived from section 11.3, not chosen: authority has to be
  established before an outer field selects anything, and floor-then-bind is trust-then-verify.
  The consequence is load-bearing and is pinned by 16 vectors - because absence of a reserved
  leaf now trips the binding, the reserved half of the floor is unreachable and every
  `floor-<profile>-omits-roax-*` vector asserts `outer-identity-mismatch` rather than
  `minimum-disclosure-floor`. Do not "simplify" by enforcing the floor first; do not trim the
  reserved paths out of the floor table either, since class 14 defines the floor as those four
  plus the profile's. `profile-unknown` stays ahead of both: it is the verifier's own allow-list,
  not a policy choice. See `corpus/README.md`.

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

## A specification claim that measurement contradicts

**Section 11.1 says `leafCount` is self-binding in a disclosed copy. It is not.** RFC 9162 section
2.1.3.2 takes `tree_size` as an input, so an attacker who controls `leafCount` controls the shape
the verifier reconstructs. Measured on an 8-leaf tree: the internal node `MTH(L[0:4])` presented as
a leaf at index 0 fails verification under the true tree size 8 and **succeeds** under a forged tree
size 2, against the same genuine root.

What actually blocks it is section 10 step 1 - recompute the leaf hash from the disclosed fields
rather than trust a supplied one - plus second-preimage resistance. That defence is already
normative. The `leafCount` sentence claims a second one that is not there, and the specification has
not been changed here because that is a specification decision.

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
Three of the four are unruled: A, C and D. **B is ruled** - both hash families are first-class and
selectable per record - and what stays open under it is the `Poseidon-BN254` parameterization. The
specification is written on the *recommended* answer to each unruled decision so it reads as a real
specification.

**Do not resolve any of them in code or prose without an explicit ruling**, and if one is ruled,
update `docs/decisions.md` in the same change rather than only the specification. A decision that
looks settled in the spec but is still marked OPEN in the decisions document is worse than either.

## Validating the schemas

There is no CI and no package manifest. The JSON Schemas were checked with Ajv 8 in **strict mode**
plus `ajv-formats`, and all three compile clean. Two things to know if you touch them:

- Ajv's `strictRequired` rejects `required` inside a `not`/`anyOf` subschema unless the same
  subschema also lists those properties. The schemas carry no-op `"properties": {"x": true}`
  annotations for exactly this reason. They are not redundant - removing them breaks strict
  compilation.
- Union types (`"type": ["string","boolean"]`) trip `strictTypes`. The envelope pins each value type
  per tag in its `allOf` conditionals instead, which is more precise anyway.
