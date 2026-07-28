# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test,
release, architecture, and sharp-edge notes that should travel with the code.

## What this repository is right now

Specification and schemas only. **No library code has been written, and that is deliberate.**
The specifications exist so the design can be reviewed before five language implementations exist to
be re-litigated.

Do not add a Rust crate, TypeScript package, Go module, Swift package or Kotlin library without an
explicit instruction to do so.

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

- **`roax.recordId` is mandatory to disclose by policy, not by arithmetic.** Only `roax.recordType`
  and `roax.schemaVersion` are arithmetic, because they select the type map. This changed with the
  D4b ruling and several documents said otherwise before it. A verifier that never receives
  `roax.recordId` can still verify every leaf it did receive.

- **`leafCount` is NOT authenticated in a disclosed copy**, and the specification claimed otherwise
  until this was measured. RFC 9162 section 2.1.3.2 takes the tree size as an *input*, so an attacker
  supplying both a leaf hash and a tree size can walk an internal node to the genuine root: on an
  8-leaf tree, `MTH(L[0:4])` at index 0 with a forged size of 2 verifies. What actually defends is
  spec section 10 step 1 - recompute the leaf hash from the disclosed fields, never accept one - plus
  the `0x00` leaf-domain byte. Never add a check that leans on `leafCount` in a disclosed copy.

- **Type tag 8 `BLOB_REF` is defined and selected by nothing.** The schemas accept it so the carrier
  form is pinned once; an implementation MUST reject any record or type map that uses it until a
  profile declares the binding (spec section 6.5). Same treatment as `Poseidon-BN254`: registered,
  forbidden in issuance. Base64 is pinned to RFC 4648 section 4 with padding and no line wrapping,
  and that governs `BYTES` and `BLOB_REF` rather than the `STRING` bindings every v1 profile uses.

- **The vaccination healthcert's `fhirBundle.entry[]` is flattened pseudo-FHIR**, not a real FHIR
  Bundle. Normalizing it to the genuine `entry[i].resource` shape changes every path and therefore
  every root, which silently breaks existing commitments. See
  `docs/profiles/vaccination-healthcert.md` section 2.1.

- **Do not resolve the reference schemas by `$id`.** Two of them carry copy-pasted `$id` values:
  recovery points at PDT's path, and vaccination points at a PDT interim path. A validator that
  registers both by `$id` silently applies the wrong rules. Load by file path.

## Documentation conventions in force here

- No em dashes. Use a plain hyphen.
- In long Markdown, put each full sentence on its own line. Every document here follows this, and
  it keeps diffs readable when a single sentence changes.
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
plus `ajv-formats`, and all three compile clean. Re-check after any edit: install `ajv` and
`ajv-formats` outside the tree, then `new Ajv2020({strict: true}).compile()` each of the three files,
using the `ajv/dist/2020.js` entry point because they are draft 2020-12. Compiling is not enough on
its own for a conditional - validate instances both ways, since an `if`/`then` that never fires
compiles perfectly and asserts nothing.

Four things to know if you touch them:

- Ajv's `strictRequired` rejects `required` inside a `not`/`anyOf` subschema unless the same
  subschema also lists those properties. The schemas carry no-op `"properties": {"x": true}`
  annotations for exactly this reason. They are not redundant - removing them breaks strict
  compilation.
- Union types (`"type": ["string","boolean"]`) trip `strictTypes`. The envelope pins each value type
  per tag in its `allOf` conditionals instead, which is more precise anyway.
- **A property is FORBIDDEN inside a branch with the false schema, `"properties": {"x": false}`.**
  That idiom is used in `recordVector`'s two-branch `oneOf` and in `envelopeVector`'s `else`, and it
  compiles clean under strict mode. It is shorter than `"not": {"required": ["x"], "properties":
  {"x": true}}` and needs no `strictRequired` annotation, because it carries no `required`.
- **A conditional keyed on a vector's `class` needs an instance test on BOTH sides.**
  `envelopeVector` requires `verifierConfig` at class 18 and forbids it everywhere else. The
  else-branch is the half a compile check cannot see, and it is the half that was missing when the
  block was merely optional. Validate a class-18 instance without the block (MUST fail), one with an
  empty block (MUST fail), and a class-14 instance carrying one (MUST fail). Do the same through a
  whole corpus document, not only against the `$defs` subschema: compiling proves the `$ref`
  resolves, and only a root-level instance proves the branch is reached by the path a runner takes.
