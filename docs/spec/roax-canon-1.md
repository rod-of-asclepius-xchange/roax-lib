# ROAX-CANON/1 - canonical serialization, commitment and selective disclosure

**Status:** draft for review.
Not frozen.
Two ruled independent implementations exist, in Rust under `rust/` and in TypeScript under `src/`; the other three have not been added.
The TypeScript implementation was written from this document alone, and its disagreements with the conformance corpus are recorded in `docs/typescript-implementation-findings.md`.
**Version string:** `ROAX-CANON/1`
**Date:** 2026-07-28

This document specifies how a health record is turned into a set of typed, salted leaves,
how those leaves are hashed and merklized into a single 32-byte root, and how individual
leaves are later disclosed and verified against that root.

It is written to be implementable independently.
Two engineers implementing only from sections 3 through 9, plus the reserved leaf set in section
11.2, should produce byte-identical roots.
Section 11.2 is named explicitly because the leaf set is the union of the record's leaves and those
reserved leaves (section 3.3), so sections 3 through 9 alone do not determine a root.
Section 11 states what makes that claim checkable, and section 13 states honestly how far it has
actually been demonstrated.

## Table of contents

1. [Conventions and terminology](#1-conventions-and-terminology)
2. [Scope, and what this design does not solve](#2-scope-and-what-this-design-does-not-solve)
3. [Abstract data model](#3-abstract-data-model)
4. [Schema binding and the type map](#4-schema-binding-and-the-type-map)
5. [Path encoding](#5-path-encoding)
6. [Value encoding](#6-value-encoding)
7. [Salt generation](#7-salt-generation)
8. [Leaf construction](#8-leaf-construction)
9. [Tree construction](#9-tree-construction)
10. [Selective disclosure](#10-selective-disclosure)
11. [The envelope](#11-the-envelope)
12. [Versioning](#12-versioning)
13. [Why not JCS, dCBOR or RDFC-1.0](#13-why-not-jcs-dcbor-or-rdfc-10)
14. [Reconciliation with dogtag](#14-reconciliation-with-dogtag)
15. [Decisions: what is ruled and what is still open](#15-decisions-what-is-ruled-and-what-is-still-open)
16. [Citations](#16-citations)

---

## 1. Conventions and terminology

The key words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, RECOMMENDED, MAY and
OPTIONAL in this document are to be interpreted as described in BCP 14 (RFC 2119, RFC 8174) when,
and only when, they appear in all capitals.

| Term | Meaning |
|---|---|
| **record** | The input document: a FHIR resource or a Singapore MOH healthcert. See the four profile documents under `docs/profiles/`. |
| **leaf** | One `(path, typeTag, value, salt)` tuple, and its 32-byte hash. |
| **path** | The location of a leaf in the record, as a sequence of typed segments. |
| **root** | The 32-byte Merkle Tree Head over all of a record's leaves. |
| **full copy** | An envelope carrying the whole record plus the salt of every leaf; the verifier recomputes the root from scratch. See section 7.3. |
| **disclosed copy** | An envelope carrying only selected leaves plus inclusion proofs, and carrying the salt of no other leaf. See sections 7.3 and 10.1. |
| **type map** | The data file binding each path pattern to a ROAX type tag. See section 4. |

Byte-level notation used throughout:

- `‖` is concatenation.
- `u32be(n)` is `n` as a 4-byte big-endian unsigned integer.
- `u64be(n)` is `n` as an 8-byte big-endian unsigned integer.
- `utf8(s)` is the UTF-8 encoding of string `s`.
- `NFC(s)` is Unicode Normalization Form C of `s` (see section 6.1 for the version pin).

### 1.1 Normative precedence between this document and the conformance corpus

**This specification is normative for meaning.**
[`docs/conformance-corpus.md`](../conformance-corpus.md) and the corpus file it defines are the
executable arbiter between two implementations that disagree, but they are **derived from** this
document rather than independent of it.

Where the two diverge, this specification governs.
A divergence is a **release-blocking corpus defect**, and the corpus build MUST report it rather
than letting an implementation pass against a vector the specification does not support.
Neither document may be changed alone: a change to a canonicalization rule here MUST land in the
same change as the corpus vectors that assert it.

The reason is stated in `docs/conformance-corpus.md` section 1.
If ROAX ships five independent libraries the corpus is the entire enforcement mechanism, and an
arbiter that disagrees with the specification it arbitrates is worse than no arbiter at all.

---

## 2. Scope, and what this design does not solve

This section is deliberately first, because a specification that only lists what it achieves is
misleading.

### 2.1 In scope

Turning a record into a root; disclosing individual leaves against that root; and an envelope that
carries either form.

### 2.2 Explicitly NOT solved by this document

- **No signature.** There is no detached issuer signature over the root in v1. Authority is
  re-derived from the anchoring chain, not read from the document. This is decision D11 and it is
  **ruled**.

  > **Normative, and stated now rather than when the feature arrives.** If a detached signature is
  > added by a later revision: it MUST sign the root; it MUST NOT become an alternative to
  > anchoring; and a verifier MUST NOT accept a signature in place of a chain read.

  The constraint is written before the feature exists because that is what stops the feature being
  added wrongly. A signature that lets a verifier skip the chain is a straight regression into the
  failure mode section 11.3 describes, and the pressure to add exactly that will arrive with a real
  and sympathetic requirement - offline verification at a border with no connectivity - at the moment
  when refusing it is least popular.
- **No anchoring registry design.** What the on-chain registry looks like - one root per record
  versus batched roots, and revocation semantics - is not specified here and is not settled.
  A further smart-contract round is expected, so no contract set is treated as permanent by this
  document. **This document does place one requirement on that design, and hands it forward rather
  than pretending it is closed here: the registry MUST record the pair `(root, hashAlg)`, and a
  verifier MUST take `hashAlg` from the registry rather than from the envelope.** Section 7.4 shows
  why that is the only one of the three algorithm bindings that actually works.
- **Some reference-schema type gaps remain unresolved.** Four base type-map artifacts are published
  in `type-maps/`, and their exact coverage is reported in `docs/type-maps.md` section 2.
  The vaccination sample's `dose` and `expiryDateTime`, PDT's 20 endorsed-sample path-kind pairs,
  FHIR XHTML, FHIR `base64Binary` and null placeholders remain unbound for the reasons documented
  in `docs/type-maps.md` section 1.
  Decision D7 requires each of those paths to fail closed rather than receive a syntactic guess, so
  the affected records remain uncommittable until profile governance or an issuer-scoped extension
  supplies determining evidence under section 4.2.
- **No absence proofs, and the capability is deliberately preserved.** Proving "this record asserts
  no allergy" is possible under the leaf ordering chosen in section 9: sorting by encoded path makes
  the tree shape a function of the path set alone, so showing the two adjacent leaves in canonical
  order proves no leaf exists between them (section 9.3).

  > **Normative:** the construction of this document **admits** absence proofs, `ROAX-CANON/1`
  > **does not define them**, and defining them requires a clinical-liability decision that is not a
  > cryptographic one.

  This is decision D6 and it is **ruled** out of scope for version 1 with that capability kept open.
  The three-part statement is deliberate: an implementer who found only "not supported" would be
  entitled to read the omission as an oversight and add them unilaterally, and "this record asserts
  no X" is a clinical claim with liability attached.
- **No confidentiality.** The full copy of a record is plaintext. This document provides selective
  disclosure, which is a different property: it lets a holder reveal a subset without invalidating
  the root. It does not encrypt anything.
- **No leaf-count privacy.** A verifier of a disclosed copy learns how many leaves the record has.
  For a record whose profile is known, the leaf count is weak but nonzero information about record
  shape. This is inherent to the construction and is not mitigated.
- **No gap privacy between disclosed leaves.** Leaves are ordered by encoded path (section 9), so a
  disclosure revealing leaves at two paths also reveals **how many withheld leaves sort between
  them**. This is the residual cost of decision D5a and it is stated rather than left for a reader to
  infer that sorting by path is free. In practice the leak is bounded, because these profiles are
  published and their path sets are largely known already, but it is real and it is structural.
  Section 10.1 states what a verifier learns in full and section 9.3 states what D5a bought in
  exchange.
- **No clinical validation, and this one is normative rather than merely absent.** A valid root
  proves that a typed payload was committed by an identified issuer and proves **nothing clinical**.
  Section 2.3 states that in full, with the prohibition it places on every surface built on this
  protocol.
- **Kotlin/JVM is unverified.** Every other target language has a confirmed mechanism for
  preserving JSON numeric literals (section 6.4). Kotlin does not, in the sense that nobody has yet
  checked. Treat the Kotlin row of that table as an open engineering question, not as a solved one.

### 2.3 What a valid root proves, and what it does not

This section is normative and it is the honesty boundary of the whole protocol.

**What a valid root proves.** That a particular typed payload, at a particular set of paths, was
committed by the issuer identified in the reserved leaves of section 11.2, under the canonicalization
version and hash algorithm bound into every leaf preimage, and that the root was anchored.

**What it does not prove.** Anything clinical. Not that a test was performed, not that a result was
negative, not that a vaccine was administered, not that a person recovered.

> **Normative:** no surface derived from this protocol may assert a clinical fact on the strength of
> root validity alone. A clinical assertion MUST be derived from the disclosed payload and MUST be
> attributed to the payload and its issuer rather than to the protocol.

**This is not a hypothetical caution and the evidence is in the profile documents.** The reference
schemas enforce far less than they appear to. A minimal `{"resourceType":"Bundle"}` satisfies both
the PDT and the recovery profiles (`docs/profiles/pdt-healthcert.md` section 6 and
`docs/profiles/recovery-healthcert.md` section 5, both confirmed by reproduction against the audited
schemas). The recovery schema never checks that the result is positive
(`docs/profiles/recovery-healthcert.md` section 6), which is the entire clinical premise of a
recovery certificate. The vaccination schema never requires any entry at all, because
`fhirBundle.entry` carries no `minItems` and its `anyOf` constrains only items that exist
(`docs/profiles/vaccination-healthcert.md` section 5). So a record can validate against its own
published schema, commit cleanly, anchor, verify, and still describe nothing.

**Clinical validation is a separate layer, deliberately.** Enforcing subject, event, cardinality and
reference rules by named implementation profiles is a real and worthwhile thing to build, and it is
**out of scope for this document**. It is a separate conformance layer, versioned independently of
every axis in section 12, that a deployment may adopt. It is kept off this document's critical path
because merging clinical governance into a cryptographic specification makes both move at the speed
of the slower one, and because the split lets that layer arrive later as an additive change without
touching a single byte of the digest rule.

This is decision D13 and it is **ruled**: D13a at the protocol layer, together with the normative
statement above.

---

## 3. Abstract data model

### 3.1 Layering

```
  record (FHIR bundle / healthcert JSON)
        |
        |  (A) SCHEMA BINDING     <- schema-driven, NOT syntax-driven (section 4)
        v
  typed value tree: every scalar carries an explicit ROAX type tag
        |
        |  (B) FLATTEN            (section 3.3)
        v
  set of (path, typeTag, value) triples
        |
        |  (C) LEAF HASH          (independent per-leaf random salt, sections 7 and 8)
        v
  leaf hashes, ordered by encoded path
        |
        |  (D) RFC 9162 MERKLE TREE (section 9)
        v
  32-byte root  ->  anchored
```

Step (A) is the step that is easy to skip and the one that matters most.
Section 4 demonstrates what breaks without it.

### 3.2 Admissible values

The abstract model admits exactly these value kinds:

- map (string keys, unique)
- array (ordered, indexed)
- string
- boolean
- null
- integer (arbitrary precision, carried as a string)
- decimal (arbitrary precision, carried as a string)
- byte string

An implementation MUST reject, at the input boundary and before any hashing:

- duplicate keys in a map;
- `NaN`, `Infinity` and `-Infinity`;
- JavaScript `undefined` and sparse-array holes, which have no JSON representation;
- unpaired UTF-16 surrogates;
- any numeric literal that has passed through a floating-point type (see section 6.4).

These rejections follow the successor requirements set out in the OpenAttestation audit, section 15
items 1-6, which lists each of them as a state a successor should not admit.
The audit demonstrates concrete harm for two of them in OpenAttestation itself:
sparse-array holes break redaction across a JSON round trip (audit section 9.6), and duplicate or
"magic" keys silently drop from the commitment (audit section 9.8).

### 3.3 Flattening

A leaf is produced for every scalar and for every **empty** container.

```
flatten(node, path):
  if node is a map and is empty:        emit (path, typeTag(path, "object"), -)
  if node is a map and is non-empty:    for each key k: flatten(node[k], path ‖ KEY(k))
  if node is an array and is empty:     emit (path, typeTag(path, "array"), -)
  if node is an array and is non-empty: for each index i: flatten(node[i], path ‖ INDEX(i))
  otherwise:                            emit (path, typeTag(path, jsonKind(node)), node)
```

`typeTag` is consulted for every emitted record leaf, including empty containers.
An object output is tag 7 EMPTY_OBJECT and an array output is tag 6 EMPTY_ARRAY, but only when the
exact selected map authorizes that structured path and observed kind under section 4.2.
Assigning tags 6 or 7 before map resolution would let an unknown empty issuer extension bypass
decision D7's fail-closed rule.

**The leaf set is not the record alone.** It is the union of the reserved leaves and the record
leaves:

```
leaves(envelope, record) =
      reservedLeaves(envelope)      // section 11.2 - a fixed set, derived from envelope fields
    U flatten(record, [])           // this section - derived from the record
```

The union is formed **before** the sort in section 9, so reserved and record leaves are ordered
together by encoded path and are indistinguishable to the tree function.
Section 11.2 gives every reserved leaf with its exact path segments and type tag, states which of
them are conditional, and states the guard that keeps the two sets disjoint.
An implementation that flattens the record only produces a different root from one that does not,
so this is not an optional step.

Map iteration order is irrelevant, because leaves are sorted by encoded path in section 9.
This is deliberate: it means a Go implementation works despite Go randomising map iteration order,
and it removes the class of bug that OpenAttestation inherits from JavaScript key enumeration.

An empty container is a leaf so that removing it changes the root.
This is a departure from dogtag, which collapses empty array, empty object and explicit null to a
single leaf (`dogtag-mono-repo`, `crates/dogtag-standard-rs/src/flatten.rs:96-115` - an empty
array and an empty object both yield `TypedScalar::Null`, which is also what a genuine null yields).
Section 14.2 explains why ROAX does not inherit that.

**A record that contributes zero leaves of its own MUST be rejected at issuance rather than
anchored.** The rejection is on the record's own contribution, because the union above always
carries the reserved leaves, so the tree itself is never empty: its floor is 6 leaves, being the
five always-emitted reserved leaves plus at least one from the record. Section 11.2 gives the
reserved set and states which one is conditional.

---

## 4. Schema binding and the type map

**The type tag MUST come from the schema, not from the JSON literal's syntax.**

This is normative and it is the highest-risk surface in the whole design.

### 4.1 Why syntactic inference is unsafe

FHIR R4 declares `Quantity.value` as `decimal`.
Three issuers writing the same logical value produce three different roots under syntactic
inference, because the tag depends on how the literal happened to be written:

| literal | syntactic tag | encoded value | outcome |
|---|---|---|---|
| `100` | INTEGER | `100` | root A |
| `100.0` | DECIMAL | `100.0` | root B |
| `1e2` | DECIMAL | `100` | root C |

With a schema-bound tag (always DECIMAL at that path), `100` and `1e2` agree on `100`, and `100.0`
stays distinct - which is the correct FHIR outcome, because FHIR R4 says the trailing zero is
significant (section 6.2).

This is not hypothetical for the reference records.
`notarisationMetadata.signedEuHealthCerts[].dose` is written as a bare JSON `1` and `2` in the
shipped vaccination sample. Under syntactic inference that is INTEGER; an issuer who later writes
`1.0` silently produces a different record.

### 4.2 Requirements on the type map

- The type map is an immutable data artifact in `type-maps/`, with its format defined by
  `schemas/type-map-artifact-1.0.json` and its exact identities listed in
  `type-maps/registry-1.0.0.json`.
- The operative matcher is a structured-path DFA over KEY and INDEX segments, followed by an output
  selected by observed JSON kind, as defined in `docs/type-maps.md` section 3.
  It MUST NOT parse or match a display path, because section 5.2 makes that representation
  non-authoritative.
- The four base artifacts cover different schema scopes.
  PDT and recovery include the lite FHIR Bundle reached through their pinned schema files,
  vaccination preserves its inline flattened pseudo-FHIR definitions, and the FHIR artifact starts
  at the full reference schema's 146-resource root union, as audited in
  `docs/type-maps.md` section 2.
- The exact map is selected by `(recordType, schemaVersion, typeMap.id)`.
  The first two values MUST equal the artifact fields exactly, and the fetched artifact bytes MUST
  reproduce `typeMap.id` under the content-ID construction in `docs/type-maps.md` section 2.1.
  The identified bytes MUST decode as strict UTF-8 and MUST contain neither duplicate JSON object
  member names nor unpaired surrogate escapes after escape decoding, under section 3.2 and
  `docs/type-maps.md` section 2.1.
  `typeMap.version` MUST equal the artifact's `typeMapVersion`, but semver is metadata and MUST NOT
  be used to choose a latest or compatible artifact, as specified in
  `docs/type-maps.md` sections 4 and 5.2.
- **Unknown transitions and missing observed-kind outputs MUST fail closed.**
  A resolver MUST NOT search another installed map, infer from JSON syntax or apply a fallback tag,
  under ruled decision D7 and `docs/type-maps.md` section 3.
- Complete profile-schema validation MUST precede map resolution.
  The DFA authorizes paths and supplies tags, but it does not replace sibling constraints or
  resource discriminators in the applicable profile schema, as stated in
  `docs/type-maps.md` section 3.

#### The type map is an artifact, not a lookup table

Fail-closed makes the type map the gate every record passes through, so its lifecycle is part of the
design rather than an operational detail.

> **Normative:** the type map is a first-class, independently versioned artifact with the extension
> path defined in `docs/type-maps.md` section 5.
> A child MUST name one exact parent ID, carry the complete effective DFA, narrow scope to named
> issuer identities, add only selectors with no inherited output under declared extension points, and
> leave every inherited transition and output logically unchanged.
> An overlapping or retagging child MUST be rejected, because section 12.2 requires an
> already-issued record to keep resolving through its original exact artifact forever.

An extension-point prefix names one structured region.
It permits an exact selector only when the parent has no output for that observed JSON kind, which
covers both unknown-key subtrees and known but unresolved outputs without permitting an override,
as defined in `docs/type-maps.md` section 5.
The added path MUST still pass complete base-profile validation under this section.
The issuer MUST publish schema or profile evidence that determines each new tag, because permissive
`additionalProperties` establishes only that a value is allowed and does not determine its semantic
type under ruled decision D7.

Two issuers may extend independently from the same parent and use the same semver.
Their content IDs and issuer scopes distinguish the branches, neither version wins, and a conflicting
pair cannot be merged without a profile-governance ruling, under
`docs/type-maps.md` sections 5.1 and 5.2.

**The operational cost is real and lands hardest on PDT**, and it is recorded rather than smoothed
over. The PDT base object permits additional properties, so a legitimate PDT record may carry fields
the type map has never seen and fail-closed rejects it at issuance
(`docs/profiles/pdt-healthcert.md` section 5). If extending the map is slow or unclear, the
fail-closed rule becomes an adoption blocker for the profile with the most real-world traffic, and
the pressure to default an unknown path to STRING will arrive from a real issuer with a real record.
That is the moment refusing it is hardest, which is why the refusal is normative here rather than
advisory.

### 4.3 Status

**Four base maps are published at `typeMapVersion: 1.0.0`.**
They contain 3,440 executable DFA states and 3,398 resolved path-kind outputs in total, with
per-profile counts, source-audit counts and exact content IDs in
`docs/type-maps.md` section 2.

The gap list remains part of the deliverable rather than a reason to guess.
The vaccination sample cannot be issued because two paths are unresolved, and the PDT endorsed
sample cannot be issued against the base map because 20 path-kind pairs are outside the base schema.
FHIR XHTML, `base64Binary` and null-placeholder semantics also remain unbound as documented in
`docs/type-maps.md` section 1.

---

## 5. Path encoding

A path is a sequence of segments. Each segment is a KEY or an INDEX.
There are **no reserved characters and no escaping.**

```
encodePath(segments) =
    u32be(count(segments))
  ‖ for each segment:
        KEY(k)   ->  0x01 ‖ u32be(len(utf8(NFC(k)))) ‖ utf8(NFC(k))
        INDEX(i) ->  0x02 ‖ u32be(i)
```

- Array indices are 0-based and MUST be `< 2^32`. An implementation that cannot represent an index
  in 32 bits MUST error rather than truncate.
- A key MAY be the empty string. It encodes as `0x01 ‖ u32be(0)` and is distinct from an absent
  segment, because the segment count differs.

### 5.1 Why length-prefixed rather than a string path

dogtag builds a display-style string path (`a.b[0].c`) and **rejects** any object key containing
`.`, `[` or `]` (`crates/dogtag-standard-rs/src/flatten.rs:17-20`).
That is a rejection rule where an encoding rule would do, and rejection rules break when a schema
evolves. Under length prefixing, the two colliding cases are provably distinct with no rule at all:

```
  keyCollisionA.b   (nested)  00000002 01 0000000d 6b6579436f6c6c6973696f6e41 01 00000001 62
  keyCollisionB.c   (dotted)  00000001 01 0000000f 6b6579436f6c6c6973696f6e422e63
                              ^^^^^^^^ 2 segments vs 1 segment
```

The same property removes the OpenAttestation collisions the audit demonstrated: an array element
and a numeric-keyed map member encode differently (`0x02 ‖ u32be(0)` versus
`0x01 ‖ u32be(1) ‖ "0"`), and an empty-string parent key is a real segment rather than a dropped
one. Both of those commit identically under OpenAttestation (audit section 9.7, reproduced there
against the pinned source).

### 5.2 The display path is never hashed

The human-readable form `a.b[0].c` is retained for display and for disclosure requests.
It MUST NOT enter any hash preimage.
Implementations MUST NOT reconstruct the encoded path by parsing a display path.

### 5.3 Consequence: leaf order is not alphabetical

Because the length prefix precedes the key bytes, sorting encoded paths sorts by
(segment count, then segment kind, then key length, then key bytes).
The resulting order is a deterministic total order but is **not** alphabetical.

This is pinned deliberately: a plain `memcmp` over the encoding is the easiest thing to get
identical in five languages. It is decision D5, ruled D5a.

---

## 6. Value encoding

### 6.1 Type tags

| Tag | Name | Encoded value bytes |
|---:|---|---|
| 0 | `NULL` | empty |
| 1 | `BOOL` | `0x01` if true, `0x00` if false |
| 2 | `STRING` | `utf8(NFC(s))` |
| 3 | `INTEGER` | ASCII canonical integer (6.2) |
| 4 | `DECIMAL` | ASCII canonical decimal (6.2) |
| 5 | `BYTES` | the bytes themselves |
| 6 | `EMPTY_ARRAY` | empty |
| 7 | `EMPTY_OBJECT` | empty |
| 8 | `BLOB_REF` | `u64be(blobByteLength) ‖ u32be(len(blobDigest)) ‖ blobDigest` (6.5) |

Tags 6 and 7 give empty containers distinct identities. See section 14.2.

**Tag 8 is REGISTERED and selected by no version-1 profile.** Its construction is defined in section
6.5 so that it does not have to be retrofitted later, and a record that selects it MUST be rejected
until a profile declares it. This mirrors exactly how section 7.4 handles `Poseidon-BN254`.

**Unicode normalization.** Strings and object keys are normalized to NFC before encoding.

This resolves a direct conflict between two of the three research inputs, and the conflict is
recorded rather than hidden. The canonicalization report specifies mandatory NFC
(the canonicalization research, section 3.3). The OpenAttestation audit takes a different view: its
section 15 item 3 says a successor should use "either no normalization or an explicitly versioned
normalization rule", and adds that "preserving exact sequence is the least surprising for FHIR".

The chosen resolution satisfies both, because the audit admits a versioned normalization rule as
valid: ROAX normalizes to NFC **and pins the Unicode version**.

> **`ROAX-CANON/1` pins Unicode 15.1.**
> An implementation whose NFC tables are from a different Unicode version MAY produce a different
> root for a string containing characters whose composition changed between versions, and MUST NOT
> claim conformance to `ROAX-CANON/1`.
> Tested by `docs/conformance-corpus.md` class 16, which is honest about its own limit: no character
> whose NFC form actually changed between Unicode versions has yet been identified, so that class
> currently detects a version mismatch by declaration rather than by demonstration.

This pin is adopted from dogtag, which learned it in code:
`crates/dogtag-standard-rs/src/encode.rs:6-7` declares `UNICODE_VERSION = "15.1"` with the comment
"Pinned Unicode version target (A3) - must match the TS SDK's runtime ICU major version."
Unlike dogtag's other lessons this one is recorded only in the source, not in its `AGENTS.md`
scar list, so it is cited at that strength: it is evidence that dogtag found the pin necessary in
practice, not a written post-mortem explaining what went wrong without it.

**This is decision D12 and it is ruled D12a.** The alternative - preserve the exact scalar sequence,
per the audit's preferred reading - is stated with its consequence in `docs/decisions.md`, and the
reason it lost is the project's own thesis: a record that passes through any normalizing form field,
which is ordinary web-form behaviour rather than an edge case, would get a different root, and the
two forms **render identically to a human**. That is an invisible failure. D12a's cost is a real
dependency on matching NFC tables, but it is explicit and checkable, because `unicodeVersion` is
carried as an opaque equality-matched field and a mismatch is detected rather than silently producing
a different root.

**Two conformance classes carry this rule and they test different halves of it.**
`docs/conformance-corpus.md` class 4 asserts NFC against NFD at leaf level, in values and in keys.
Class 19 asserts it end to end: one record whose string differs before and after NFC, in both forms,
producing **one** root. Without class 19 the rule is prose that every implementation is trusted to
have applied to the whole pipeline rather than to the leaves a leaf-level vector happens to reach.

**Unpaired surrogates MUST be rejected** before normalization. dogtag's TypeScript SDK does exactly
this and explains why: Rust strings cannot represent them but JavaScript strings can, so the
rejection has to be explicit on the JavaScript side or the two implementations diverge on input
neither should accept (`packages/dogtag-standard-ts/src/encode.ts:14-28`, and the matching comment
at `crates/dogtag-standard-rs/src/encode.rs:9-10`).

### 6.2 Canonical numbers

**Canonical integer.** Arbitrary precision, held as a string, never parsed into a machine integer.

- Grammar: `^-?(0|[1-9][0-9]*)$`
- Leading zeros are rejected.
- `-0` normalizes to `0`.
- Anything else is an error.

**Canonical decimal.** Arbitrary precision, held as a string, never parsed into a float.

- Input grammar: `^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$`, which is exactly the FHIR R4
  `decimal` pattern as shipped in the reference `fhir/4.0.1/schema.json`.
- Canonicalization does **only** two things:
  1. expands exponent notation into positional notation, by the rule below;
  2. drops the sign of a zero-valued magnitude.

#### Exponent expansion, stated exactly

Let the input be a sign, a mantissa written as `intDigits` optionally followed by `.` and
`fracDigits`, and an exponent `e`, where an absent exponent means `e = 0`.
Let `f = len(fracDigits)`, which is `0` when there is no fraction part.

Expansion shifts the decimal point right by `e` places.
The fraction of the result then has exactly `f'` digits, where:

```
  f' = max(0, f - e)     for e >= 0
  f' = f + |e|           for e <  0
```

The digit sequence is never rounded, extended or truncated to a target precision.
Shifting pads with `0` where the point runs past the digits that are present.
The result is then normalized to the output grammar `^-?(0|[1-9][0-9]*)(\.[0-9]+)?$`, which is the
same grammar `schemas/envelope-2.0.json` pins for a DECIMAL value:

- leading zeros in the integer part are removed, and an emptied integer part becomes a single `0`;
- a fraction of zero digits is dropped along with its `.`;
- a zero-valued magnitude keeps its fraction digits and loses its sign.

Worked examples, which a conforming implementation MUST reproduce:

```
  1e2      ->  100        f = 0, e =  2, f' = max(0, 0 - 2) = 0
  1.0e2    ->  100        f = 1, e =  2, f' = max(0, 1 - 2) = 0
  1.00e1   ->  10.0       f = 2, e =  1, f' = max(0, 2 - 1) = 1
  1.5e-2   ->  0.015      f = 1, e = -2, f' = 1 + 2         = 3
  1e-3     ->  0.001      f = 0, e = -3, f' = 0 + 3         = 3
  0e5      ->  0          f = 0, e =  5, f' = 0, integer part normalizes to a single 0
  0.010    ->  0.010      no exponent, unchanged
```

Note precisely what this preserves.
Trailing zeros of the **fraction** are significant and survive, which is the FHIR requirement stated
immediately below.
Trailing zeros of the **integer part** carry no precision in this grammar and cannot, so `1e2`,
`1.0e2` and `100` all encode to `100` and are therefore the **same leaf**, while `100.0` encodes to
`100.0` and is a **different leaf**.
`docs/conformance-corpus.md` class 1 states that trio explicitly, so the corpus cannot be misread as
requiring the three to differ.

#### Bound on expansion

**An implementation MUST reject any input whose expanded positional form would carry more than 1024
digits in total, counting integer digits and fraction digits together.**

This bound is a fixed constant of `ROAX-CANON/1` and MUST NOT be implementation-chosen.
Section 13.3 rejects RDFC-1.0 partly because an implementation-chosen iteration limit means two
conformant implementations disagree about which records they will canonicalize at all; an
implementation-chosen digit limit here would be that same defect in this design.
Changing the bound changes which records canonicalize, so it is a canonicalization-version change
under section 12.

The bound is what gives the input grammar an error path.
The grammar admits `1.4e+9999`, whose expansion is ten thousand digits, and
`docs/conformance-corpus.md` class 3 requires exactly that input to error rather than be
canonicalized.
1024 clears every vector the corpus requires to succeed, including class 1's 40-digit integer part
and 40-digit fraction and class 2's 40-digit integer.

**Trailing zeros in the fraction are significant and MUST be preserved.**

```
  0.010  ->  0.010        (NOT 0.01)
  1.50   ->  1.50         (NOT 1.5)
  2.0    ->  2.0          (NOT 2)
  1e2    ->  100
  -0.00  ->  0.00         (sign dropped, precision kept)
```

This is what makes the scheme conformant with FHIR R4, which states of `decimal`:

> "The precision of the decimal value has significance: e.g. 0.010 is regarded as different to 0.01,
> and the original precision should be preserved"
>
> "Implementations **SHALL** handle decimal values in ways that preserve and respect the precision
> of the value as represented for presentation purposes"

- FHIR R4, Data Types, `decimal`: <https://hl7.org/fhir/R4/datatypes.html>
- The shipped reference schema agrees in its own words, describing `Quantity.value` as
  "The value includes an implicit precision in the presentation of the value."

Section 13.1 shows what a rule that strips trailing zeros does to this requirement, with a
reproducible demonstration.

### 6.3 Bytes, and the canonical base64 form

`BYTES` carries the bytes themselves.
Where a record embeds base64 (`logo`, `attachments[].data`), the profile document states whether
the field is bound as `STRING` over the base64 text or as `BYTES` over the decoded content.
The explicitly typed healthcert blob fields bind as `STRING`, so their base64 text is normalized to
NFC and hashed like any other string and no base64 rule enters their digest.
FHIR `base64Binary` is the version-1 exception: its six full-FHIR and four lite-FHIR source slots
remain unresolved between STRING over the text and BYTES over the decoded bytes, so no current map
binds those slots (`docs/type-maps.md` sections 1.3 and 2.2).
That unresolved choice and the healthcert STRING bindings are unchanged by the D9 ruling, which
adds BLOB_REF as a carrier selected by no version-1 profile (section 6.5).

`BYTES` and `BLOB_REF` (section 6.5) both have to decode that text, so one base64 form is pinned
now rather than left to be discovered later.

> **`ROAX-CANON/1` pins RFC 4648 section 4 base64: the standard alphabet, with padding, and no line
> wrapping.**
> An implementation MUST reject base64 input that is not in this form, specifically: the URL-safe
> alphabet of RFC 4648 section 5; absent or excess `=` padding; any line break or other character
> outside the alphabet; and a final quantum whose unused bits are non-zero, which RFC 4648 section
> 3.5 identifies as the non-canonical case.

**Why this is pinned before it is used.** Padding and line-wrap variants encode identical bytes
differently, so without a pin two implementations decoding the same field could disagree about
whether the record is admissible at all, which is the same class of divergence section 13.3 rejects
RDFC-1.0 for. It is stated here rather than in section 6.5 because it governs `BYTES` as well, and
`BYTES` is selectable by a profile today.

This is decision D9, which is **ruled**: inline for version 1, with the content-addressed binding
defined now and selected by nothing.

### 6.4 Platform hazard: your JSON parser probably destroys the record

This bites *before* any canonicalization runs, and it is the practical form of section 13.1.

| Language | Mechanism preserving the raw numeric literal | Confirmed? |
|---|---|---|
| Rust | `serde_json` with `arbitrary_precision`; `Value::Number::to_string()` returns the verbatim literal | Yes |
| Go | `encoding/json` with `Decoder.UseNumber()`; `json.Number` is the literal string | Yes |
| TypeScript / JS | ES2025 `JSON.parse` source-text access: the reviver's third `context` argument carries `context.source` (V8 >= 12 / Node >= 21) | Yes |
| Swift | **Nothing in Foundation.** A literal-preserving scanner must be hand-written | Yes, negative result |
| Kotlin / JVM | Not established | **No - see section 2.2** |

Swift is the sharp edge and it is worse than merely lossy.
`JSONSerialization` switches between `__NSCFNumber` and `NSDecimalNumber` depending on the
magnitude of the value, so `{"a":0.010}` reserializes as `{"a":0.01}` while
`{"a":1234567890123456789.1}` survives. The failure is therefore *inconsistent*, which is the worst
kind: it passes every small-number test anyone writes.

> **Normative:** implementations MUST NOT parse record numbers through any floating-point type.

The canonicalization report gives a ~90-line Swift scanner that captures number source bytes
verbatim (the canonicalization research, appendix B). Porting it is REQUIRED for any Swift
implementation.

### 6.5 The content-addressed blob binding - registered, and selected by nothing in v1

A blob bound as `STRING` or `BYTES` is hashed in full, inline, and the record stays self-contained.
`BLOB_REF` is the alternative: the leaf commits to the blob rather than containing it, and the blob
travels out of band.

```
BLOB_REF value bytes =
      u64be(blobByteLength)                  // the blob's length in bytes
    ‖ u32be(len(blobDigest)) ‖ blobDigest    // the digest of the blob's bytes

blobDigest = SHA-256(blob bytes)             // 32 bytes; see the inference note below
```

**The length is inside the commitment, and that is not decoration.** A digest alone lets a
substituted blob of a different size pass anything that does not separately check the size, so the
size is committed rather than carried beside the commitment. The digest is length-prefixed for the
same reason every other variable-length component in this document is: a future revision that
registers a wider digest must not be able to overlap a preimage with this one.

> **Normative:** no version-1 profile selects `BLOB_REF`. An implementation MUST reject a record
> whose type map binds any path to tag 8, and MUST reject an envelope carrying a tag-8 leaf, until a
> profile document under `docs/profiles/` declares the binding for that path. A profile that declares
> it MUST also state how the blob is carried out of band and how a verifier obtains it, neither of
> which this document specifies.

This is the same treatment section 7.4 gives `Poseidon-BN254`: defined or registered now, forbidden
in issuance until the remaining pin is made. The two are related. Under `hashAlg: "SHA-256"` a 14 KB
blob costs about 41 microseconds and inline is simply correct; under Poseidon the same blob costs
about 14 ms, and `logo` plus `attachments[].data` are 60 to 70 percent of all hashed bytes across the
three reference records (`docs/decisions.md`, decision B and decision D9). So for a Poseidon-selecting
record family, blob handling stops being an optimization and becomes a requirement.

**Why the binding is defined now rather than when it is first needed.** Retrofitting a second
leaf-binding form after five independent implementations exist splits the family: some implement it,
some do not, and a record that verifies in one fails in another. Defining it while no code exists to
migrate costs almost nothing, and section 12.2 states future-proofing as a standing requirement
rather than an aspiration.

> **Stated as inference, not as a carried ruling.** Pinning the blob digest to SHA-256 regardless of
> `hashAlg` is a design choice made in this document. The reasoning is that the binding exists to
> keep a large blob out of an expensive hash, so tying the blob digest to `hashAlg` would make a
> Poseidon record hash the whole blob through Poseidon and defeat the binding's only purpose; a
> 44-byte `BLOB_REF` value - `u64be` length 8, `u32be` digest length 4, digest 32 - is then cheap
> under either algorithm. The consequence to accept knowingly
> is that a `BLOB_REF` leaf depends on SHA-256's collision resistance even inside a record whose tree
> is not SHA-256. A revision that wants a different blob digest must register it explicitly rather
> than infer it from `hashAlg`.

---

## 7. Salt generation

```
salt(leaf) = 16 bytes drawn from a CSPRNG, independently for every leaf
```

There is no derivation, no key derivation function, no master secret and no preimage.
Each leaf's salt is an independent random value, generated once at issuance and thereafter stored
and carried alongside the leaf it belongs to.

> **Normative:**
>
> - Every salt MUST be drawn from a cryptographically secure pseudorandom number generator, with at
>   least **128 bits** of entropy. `ROAX-CANON/1` pins the salt length at exactly **16 bytes**, which
>   is that floor. The length is carried in the leaf preimage as `u32be(len(salt))` (section 8), so a
>   later revision can widen it without ambiguity.
> - A salt MUST NOT be derived from record content, from the leaf's path, from the record identifier,
>   from another salt, from the issuer's signing key, or from any other issuer-stable value.
> - An implementation MUST draw each salt independently. It MUST NOT reuse a salt across leaves, and
>   MUST NOT reuse a record's salts when reissuing that record.

**The entropy floor is load-bearing and is the only thing standing between a withheld low-entropy
leaf and a dictionary search.** Section 10.1 gives that attack in full: an attacker holding a
withheld leaf's hash, its path and its tag enumerates candidate values until one matches, and gender,
a birth date or a positive/negative result have only a few or a few thousand candidates. The salt is
what makes the enumeration infeasible, so a salt from a non-cryptographic generator, or a short one,
silently removes the protection while every verification still passes.

`DOMAIN` is **algorithm-qualified**: it is the ASCII string `ROAX-CANON/1/` followed by the
envelope's `hashAlg` value, so for v1's defined algorithm it is `ROAX-CANON/1/SHA-256`.
It appears in the leaf preimage of section 8. Section 7.4 states why the algorithm identifier is
bound there and not merely declared, and this ruling on salts does not touch it.

> **Salts are generated by the protocol, not supplied by the issuing institution.**
> Every salt is produced at issuance by the issuing library itself, from a CSPRNG. Salts are not
> clinical data, not a record field, and not something a hospital, a laboratory or any other issuer
> collects, stores in its own systems, or adds to an existing dataset.
> Section 7.3 requires a full copy to carry every leaf's salt, and that is purely a matter of
> envelope format: it imposes **no new data-collection burden on any issuer**.
> This is stated because "include the random numbers in the dataset" is an easy and expensive
> misreading, and an implementer who takes it as an integration requirement would levy real work on
> issuing institutions for a value the library computes on its own.

### 7.1 Why independent salts rather than derivation from a master salt

**This is decision D4 and it is ruled D4b.** An earlier draft of this document specified D4a: one
32-byte `masterSalt` per record, every leaf's salt derived from it by HMAC-SHA-256 over a preimage
that also carried the record identifier. That construction is gone, and the reasoning is recorded
here because the deleted option is the one a reader is most likely to reinvent.

**The envelope was never the argument.** Section 7.3 requires a full copy to carry the salt of every
leaf under either option, because a full copy is otherwise unverifiable, and a disclosed copy carries
only the salts of the leaves it reveals under either option. So the envelope bytes are identical
either way and **nothing in the envelope changed with this ruling**. The whole case for derivation
was issuer-side storage: one 32-byte secret per record instead of 16 bytes per leaf, about 1.4 KB on
an 87-leaf record.

**Against that sat a failure mode independent salts do not have at all.** Reusing a master salt
across two records for the same patient makes every shared path with a shared value produce the
*same* leaf hash in both, so anyone who sees both disclosures links them. In a protocol whose purpose
is patient privacy that is the worst failure available, and it is **silent**: both records verify
perfectly, and no check anywhere reports a problem.

Binding the record identifier into the preimage was real defence in depth, adopted from dogtag, which
does the same to keep one wallet's two tags mutually unlinkable (`AGENTS.md:1744-1745` in the dogtag
monorepo; the shared builder is documented at
`crates/dogtag-standard-rs/src/profile_tree.rs:14-24`). But it was defence in depth rather than a
fix, and this document said so: if the record identifier is content-derived or reused across a
reissuance, the linkage returns. "Derive the record identifier deterministically so reissuance
reproduces the same root" is an attractive-sounding thing for an implementer to do. A hazard a
competent engineer can walk into while trying to be helpful is not adequately guarded by a MUST.

**Trading a kilobyte of issuer storage for a silent cross-record patient-linkage hazard is a bad
trade.** Independent per-leaf salts have no shared secret, so there is nothing to reuse and the
failure mode does not exist to be guarded against.

**The ruling also removes machinery, which is a second and independent reason for it.** Gone are the
key derivation function, the master salt, the record identifier in a preimage, and a conformance
class whose only job was to enforce a MUST no verifier can check. Five independent implementations
have five fewer places to disagree subtly. dogtag stores 16 random bytes per leaf and reached this
same answer for this same reason (section 14.2).

**One consequence is easy to miss and is corrected throughout this document.** The record identifier
is no longer an input to anything a verifier computes. `roax.recordId` remains a reserved leaf and
remains in the minimum-disclosure floor, but it is now mandatory **by policy** rather than **by
arithmetic**: a verifier that does not receive it can still verify every leaf it did receive.
Sections 10.2 and 11.2 state which of the five floor paths are arithmetic and which are policy.

**And one hazard genuinely disappears rather than moving.** Under derivation, a holder given
`salt(A)` was safe from deriving `salt(B)` only because HMAC is one-way. Under independent salts the
salts are unrelated by construction, so there is no one-wayness argument to get wrong and no
truncation to reason about.

### 7.2 What the `salts` array costs, in bytes

A full copy carries one salt per leaf. For an 87-leaf record that is 1,392 bytes of salt itself, and
far more for a large FHIR bundle - but the salt bytes are not where the cost is.

**Path bytes dominate, not the 16-byte salt.** Each entry repeats the leaf's whole structured path,
so a reader who budgets 16 bytes per leaf will be wrong by roughly an order of magnitude and will
optimize the wrong thing.

Worked from `fhirBundle.entry[0].identifier[0].type`, a real path in the vaccination sample
(section 4.2), serialized as the `salts` entry `schemas/envelope-2.0.json` defines:

```
  {"segments":[                                    13 bytes of framing
    {"key":"fhirBundle"},                          20   = 10 + len("fhirBundle")
    {"key":"entry"},                               15   = 10 + len("entry")
    {"index":0},                                   11
    {"key":"identifier"},                          20   = 10 + len("identifier")
    {"index":0},                                   11
    {"key":"type"}                                 14   = 10 + len("type")
  ],"salt":"<32 hex>"}                             10 + 32 + 2
                                                 + 5 commas between segments
  total                                          ~153 bytes, of which 96 are path and 32 are salt
```

At about 153 bytes an entry, the 93-leaf vaccination envelope of section 11.1 gains roughly
**13.9 KB**. That is comparable to the same record's own 14,314-byte embedded logo, which
`docs/decisions.md` D9 tabulates to the byte, and it is the largest single format cost this
document imposes.

Two things that cost is **not**. It is a **full-copy-only** cost: a disclosed copy carries one salt
per revealed leaf, so the 583-versus-2,720-byte figures in section 10.3 are untouched. And it is not
a cost the deleted derivation scheme could have avoided either, because it lands identically under
both answers to decision D4 and was one of the reasons D4b won.

**The obvious smaller encoding is rejected on purpose.** A positional array in `encodePath` order
with the segments dropped would cost 35 bytes an entry instead of 153. It would also make
salt-to-leaf pairing depend on each implementation reproducing the section 9 sort identically before
it can even read the salts, which is precisely the cross-implementation divergence this project
exists to prevent. Explicit segments make the pairing self-describing and independent of the sort,
and that is worth the bytes.

Disclosing leaf A means disclosing that leaf's salt only. The salts are independent random values, so
a verifier holding one learns nothing whatsoever about any other and cannot brute-force a withheld
low-entropy field - which matters because a birth date or a gender has only a few thousand or a few
possible values. Under the deleted derivation scheme this property held only because HMAC is one-way;
under section 7 it holds by construction, which is one fewer argument an implementation can get
wrong.

This is decision D4 and it is ruled D4b. See `docs/decisions.md`.

### 7.3 Which copy carries which salts

Three rules, and the third is absolute:

1. **A full copy MUST carry the salt of every leaf**, each 16 bytes in lowercase hex, addressed by
   its structured path. "Every leaf" means the union of section 3.3, so the reserved `roax.*` leaves
   of section 11.2 are included and the count equals `leafCount`.
2. **A disclosed copy MUST carry the salt of every leaf it reveals and the salt of no other leaf.**
   See section 10.1 for why the second half of that sentence is the load-bearing one.
3. **No envelope may carry any value from which the salt of an undisclosed leaf could be obtained.**
   Under section 7 no such value exists to carry, which is what makes this rule cheap: the salts are
   independent, so there is no master secret, no seed and no derivation key anywhere in the design.

`schemas/envelope-2.0.json` enforces all three structurally. The `salts` array is required alongside
`record` and forbidden alongside `disclosure`, the envelope closes with `additionalProperties: false`
so no seed field can be added by an issuer, and there is no `masterSalt` field to populate because
`masterSalt` does not exist.

**Rule 3 is retained rather than deleted, and the reason is worth stating.** An earlier draft of this
document derived every salt from a per-record `masterSalt`, and rule 3 then forbade that secret from
appearing in any envelope. Decision D4 was ruled D4b and the secret is gone (section 7.1), which
makes the old wording vacuous but the rule itself still binding on any future revision that
reintroduces a derived salt. A revision that adds a seed to the envelope would hand every holder the
ability to recompute every withheld leaf's salt, which is exactly the leak section 10.1 exists to
prevent, and it would do so in an envelope that still verified correctly.

Without rule 1 a full copy is not verifiable at all, which would make the definition in section 1
false. `leafHash` (section 8) needs the leaf's salt, and the record body carries no salts, so a
verifier holding a full copy would have no route to any leaf hash and therefore none to the root.

**Carrying every salt in a full copy discloses nothing extra.** A full copy already reveals every
value at every path. A salt is only useful for confirming a value you do not already have, and a
full copy withholds nothing, so there is nothing left for the salts to protect. The property salts
exist for is defeating a dictionary search against a **withheld** low-entropy leaf (sections 7 and
10.1), and that property belongs entirely to the disclosed copy.

**Verification never regenerates a salt.** It reads the salt from the envelope and recomputes
`leafHash`. That was true under the deleted derivation scheme as well, which is why this ruling
changes no envelope bytes and no verification step.

**Operationally:** a holder downgrading a full copy to a disclosed copy MUST drop the `salts` array
and emit, on each revealed leaf, only that leaf's own salt. An envelope carrying `salts` alongside
`disclosure` MUST be rejected rather than repaired.

Note also that the record body of a full copy carries record numbers in their original JSON form.
The parser requirement of section 6.4 therefore applies to the **envelope**, not only to a bare
record: an implementation that reads a full copy through a float-based JSON parser destroys the very
literals it is about to recompute the root from, and will fail to reproduce a root it should have
matched.

### 7.4 How the algorithm identifier is bound, and what each binding is worth

`hashAlg` selects which hash function a verifier runs, so it is authority rather than a hint, and
section 11.3 states normatively that anything outside the root is never authority.

**A reserved leaf cannot bind the algorithm, and an earlier draft of this document was wrong to try.**
The leaf would be hashed *with* the algorithm it names. An attacker who computes the whole tree
under a weak algorithm `W` produces a self-consistent record whose `roax.hashAlg` leaf says `W`,
whose every other leaf is hashed under `W`, and whose root is the one he was aiming at. He controls
the root, so committing the field inside it buys nothing at all. The leaf was removed rather than
kept as belt-and-braces, because a binding that does not bind is worse than none: it invites a
verifier to rely on it.

Three mechanisms replace it, and they are listed with what each is actually worth:

**H1. `hashAlg` is a length-prefixed component of `DOMAIN`**, so it enters every leaf preimage
(section 8). It no longer enters a salt preimage, because decision D4's ruling to D4b removed salt
derivation entirely (section 7.1); `DOMAIN` itself is unchanged by that ruling. **Stated honestly,
this buys almost nothing
cryptographically**, for the same reason the leaf did not: the attacker computes both records under
the same domain string. What it does buy is real but narrower. It removes cross-algorithm root
ambiguity by construction, so the same content under two algorithms cannot collide on a root by
accident, and it makes the claim in `schemas/envelope-2.0.json` true rather than aspirational.

**H2. The anchoring registry MUST record the pair `(root, hashAlg)`, and a verifier MUST take
`hashAlg` from the registry, never from the envelope.** This is the one that works. Authority for
which hash to run then comes from the same place authority for the root comes from, which section
11.3 requires of every other authoritative field. This document does not design the anchoring
registry (section 2.2), so this is recorded as a requirement handed forward to that work rather
than as something closed here.

**H3. A verifier MUST reject any `hashAlg` that is not on its own configured allow-list.**
This closes the case H2 does not: an algorithm that was legitimately registered and has since been
retired. Without H3 a verifier that has retired `W` still runs `W` because the envelope asked it to.

The general shape is worth naming, because it recurs: **a self-describing document cannot
authenticate its own description.** The description has to come from outside, which here means the
anchoring layer.

**Which algorithms are defined.** `ROAX-CANON/1` **defines** the construction for `SHA-256` only.
`Poseidon-BN254` is **registered** in the envelope schema because ZK-friendly and non-ZK hashes are
both first-class and selectable per record (decision B in `docs/decisions.md`), but its
parameterization is **not pinned** by this document: the field, the rate and capacity, the round
constants and - the part the byte layouts above do not survive without - the encoding from a
length-prefixed byte string to field elements.

> **Normative:** a record MUST NOT be issued with `hashAlg: "Poseidon-BN254"` until a revision of
> this specification pins that parameterization. The byte-level preimage in section 8 is
> stated over byte strings and does not transfer to a prime-field permutation unmodified.
> Section 7 no longer states a preimage of its own, because decision D4 was ruled D4b and salt
> derivation is gone; section 8's leaf preimage is the only one left to carry across.

---

## 8. Leaf construction

```
leafHash(path, tag, value, salt) = H(
      0x00                              // RFC 9162 leaf domain byte
    ‖ u32be(len(DOMAIN)) ‖ DOMAIN       // DOMAIN = "ROAX-CANON/1/" ‖ hashAlg
    ‖ u32be(len(P))      ‖ P            // P = encodePath(path)
    ‖ tag                               // one byte
    ‖ u32be(len(salt))   ‖ salt         // 16 bytes
    ‖ u64be(len(V))      ‖ V            // V = encoded value bytes (section 6)
)
```

**`H` is the hash function named by the envelope's `hashAlg`**, taken by a verifier from the
anchoring registry rather than from the envelope (section 7.4, H2). It is written as `H` rather than
as `SHA-256` because this is a hash-agile specification and naming one algorithm in the construction
would contradict that; `ROAX-CANON/1` defines `H` for `SHA-256` only, per section 7.4.

**Salts carry no algorithm dependence at all** (section 7). A salt is random bytes, generated once at
issuance and never recomputed by a verifier or inside a proof circuit, so there is no second hash
function anywhere in this construction and no question of which algorithm produced a salt. An earlier
draft derived salts through `HMAC-SHA-256` and had to state explicitly that the derivation stayed
`HMAC-SHA-256` under every `hashAlg`; decision D4's ruling to D4b removed the derivation and that
exception with it. dogtag reached the same split from the other direction, with a Poseidon tree over
BN254 and salts that are not Poseidon output (`crates/dogtag-standard-rs/src/profile_tree.rs` and
`poseidon.rs`).

**There is exactly one leaf-preimage builder in a conforming implementation.** dogtag records the
cost of the alternative plainly - "A second preimage builder is the drift" (`AGENTS.md:1747-1751`) -
and its consent key stayed wallet-level for a whole release because it had its own hand-rolled
preimage. With salts no longer having a preimage of their own, `leafHash` is the only one left, which
is the shape that lesson recommends.

Every variable-length component is length-prefixed, so no two distinct
`(path, tag, salt, value)` tuples share a preimage.

The `0x00` prefix is RFC 9162's leaf domain byte, so a leaf can never be confused with an internal
node, which is prefixed `0x01`. RFC 9162 section 2.1.1 states the reason: "the hash calculations
for leaves and nodes differ; this domain separation is required to give second preimage resistance".

`DOMAIN` is inside every leaf preimage, which is what cryptographically binds the canonicalization
version **and**, because it is algorithm-qualified, the hash algorithm. See sections 7.4 and 12.

---

## 9. Tree construction

Leaves are the `leafHash` values, **ordered by ascending `encodePath` bytes**, using plain unsigned
byte comparison. Paths are unique by construction, so the order is total and tie-free.

Then RFC 9162 section 2.1.1, **with one stated adaptation.**

### 9.1 The adaptation - read this carefully

This is the easiest place for two implementations to disagree.

RFC 9162 defines `MTH({d[0]}) = HASH(0x00 ‖ d[0])`. The RFC applies the `0x00` leaf-domain byte
itself, to *raw entries*. In this design the `0x00` byte is already applied inside `leafHash`
(section 8). So the tree function here operates on **already-hashed leaves** and MUST NOT apply
`0x00` a second time:

```
Let L = [ leafHash(...) for each leaf, in encodePath order ]     // each already 0x00-domained

MTH([])      = H("")                                             // total function only; see below
MTH([x])     = x                                                 // NOT H(0x00 ‖ x)
MTH(L), n>1  = H(0x01 ‖ MTH(L[0:k]) ‖ MTH(L[k:n]))
               where k is the largest power of two strictly smaller than n
```

`H` is the same algorithm-parameterized hash as in section 8, and for the same reason: naming
`SHA-256` here would hardwire one algorithm into a hash-agile specification.

The composition `leafHash` then `MTH` is therefore bit-identical to RFC 9162's `MTH` over raw
entries whose entry bytes are everything after the `0x00` in section 8.
The internal-node rule and the split rule for `k` are unchanged from the RFC.

A record that contributes zero leaves of its own MUST be rejected at issuance rather than anchored.

**`MTH([])` is unreachable in a conforming implementation**, and is stated only so the function is
total. The leaf set is the union of section 3.3, which always carries the reserved leaves of section
11.2, so `L` is never empty and its length is never below 6. The branch is kept rather than deleted
because a total function is easier to port than one with an undefined case, and because an
implementation that reaches it has a defect worth failing loudly on rather than an input worth
hashing.

### 9.2 Inclusion proofs

RFC 9162 sections 2.1.3 and 2.1.3.2, unchanged, again over already-hashed leaves.
A proof is verified against `(leaf hash, leaf index, tree size, audit path, root)`.

### 9.3 Why RFC 9162 rather than a bespoke tree

- It is **position-bound and domain-separated**. There is no commutative fold, and a leaf hash is
  `H(0x00 ‖ ...)` where an internal node is `H(0x01 ‖ ...)`, so the hazard dogtag demonstrates in its
  own test suite - an *internal node* folding to the root just as happily as a leaf, under a
  commutative sorted tree with odd-promotion - has no analogue here
  (`crates/dogtag-standard-rs/src/merkle.rs:86-99` documents the hazard on `process_proof`; the
  test at `merkle.rs:196-229` demonstrates the forgery). dogtag closes it with a Poseidon5-vs-
  Poseidon3 arity/domain split inside `verify_inclusion`. ROAX gets it from the RFC's own domain
  bytes.

  > **The domain separation is what closes it, and only in combination with section 10 step 2.**
  > Position-binding alone does not: RFC 9162 section 2.1.3.2 takes the tree size as an input, so a
  > verifier handed both a leaf hash and a tree size by the same party can be walked to the genuine
  > root from an internal node. Section 11.1 records that case with its reproduction. What removes it
  > is that a conforming verifier never accepts a leaf hash; it recomputes one, and a recomputed leaf
  > hash is `0x00`-domained by construction.

- Its shape is uniquely determined by the number of leaves (RFC 9162 section 2.1.1), so a verifier
  reconstructs tree shape from `(index, size)` alone. dogtag reached the same requirement from the
  other direction and had to make promotion an **explicit** proof step to get it, because the
  legacy bare-sibling list represented a promote by omission and the verifier could not recover the
  depth (`merkle.rs:57-64`). This is convergent evidence that the requirement is real, not a
  departure from dogtag.

  **Read that property precisely: shape follows from size, and size is an input.** It does not follow
  that a verifier can recover the size, and section 11.1 states what goes wrong for an implementation
  that assumes it can.
- It has no duplicate-promotion second-preimage problem, and its non-power-of-two handling is
  specified rather than invented.

**Sorting by path rather than by leaf hash** additionally makes the tree shape independent of the
salt values, and makes absence proofs possible in principle: showing the two adjacent leaves in
canonical order proves no leaf exists between them. dogtag sorts by hash
(`merkle.rs:24-26`). This is decision D5, **ruled D5a**; the absence-proof consequence is decision
D6, **ruled** out of scope for version 1 with the capability preserved (section 2.2).

Three things bought, and one paid, stated together so the trade is visible in the section that makes
it:

- **The tree shape is reproducible and therefore checkable.** It is a function of the path set alone,
  so two implementations can be compared structurally rather than only on a final root. That matters
  enormously when five of them must agree, and it is the decisive argument.
- **Absence proofs stay available** at essentially no cost, which is what lets section 2.2 preserve
  the capability rather than foreclose it.
- **Debugging survives the salt ruling.** Since decision D4 was ruled D4b, salts are independently
  random, so sorting by leaf hash would now make tree shape effectively random per record - the worst
  case for diagnosing a cross-implementation disagreement.
- **Paid: a disclosure reveals the gaps.** A verifier given leaves at two paths learns how many
  withheld leaves sort between them, because the positions are determined by the path order. Sorting
  by leaf hash would have hidden that. The leak is bounded in practice, since these profiles are
  published and their path sets are largely known already, but it is real and structural, and
  sections 2.2 and 10.1 state it rather than leaving a reader to infer that sorting by path is free.

---

## 10. Selective disclosure

A disclosed copy carries, for each revealed leaf: its path as **structured segments**, its leaf
index, its type tag, its value, **the leaf's own salt**, and its RFC 9162 audit path.
There is no path-keyed derivation function to look up: since decision D4 was ruled D4b the salt is an
independent random draw stored alongside the leaf it belongs to (section 7).
It MAY additionally carry the display path, which is display only and is never an input to anything
the verifier computes (section 5.2).

> **Normative:** a disclosed copy MUST carry the salt of every leaf it reveals and **MUST NOT carry
> the salt of any withheld leaf**. It MUST NOT carry any value from which a withheld leaf's salt
> could be obtained, and under section 7 no such value exists (section 7.3, rule 3).
> Section 10.1 gives the attack this prevents.

The top-level `typeMap` descriptor is a discovery hint under section 11.3.
Before resolving a record leaf, a verifier MUST fetch the candidate artifact, reproduce its exact
content ID and compare its `recordType`, opaque `schemaVersion` and `typeMapVersion` to the envelope
under section 4.2.
The verifier MUST first verify all five mandatory reserved leaves using the fixed table in section
11.2, require `roax.typeMap.id` to equal the candidate ID, and require the disclosed issuer identity
to be a member of `scope.issuerIds` when the artifact has `scope.kind: "issuers"`.
Only after those proofs succeed may it apply the profile or issuer-scope authority rules in section
4.2 and use the candidate map for record leaves.

For each disclosed leaf, a verifier:

1. checks a record leaf's tag against the exact selected map under section 4.2, or checks a reserved
   leaf against the fixed table in section 11.2;
2. re-encodes the path from the structured segments, recomputes the encoded value, and recomputes
   `leafHash` per section 8, without trusting a caller-supplied leaf hash;
3. verifies the audit path against `root` per RFC 9162 section 2.1.3.2;
4. checks `root` against the anchoring layer under section 11.3.

The leaf-hash recomputation step is not optional and it is where dogtag's most expensive scar lives.
dogtag documents `process_proof` as "a fold **primitive**, NOT a membership check. It trusts the
`leaf_hash` you hand it, so on its own it proves nothing" (`merkle.rs:86-91`), and its
`check_integrity` rebuilds the whole tree rather than trusting a fold
(`crates/dogtag-standard-rs/src/verify.rs:263-264`: "rebuild the WHOLE tree (never trust
processProof alone - C1)").

### 10.1 What a verifier learns, and what it does not

**Learns:** each disclosed path, value and salt; the total leaf count; the disclosed indices; the
sibling hashes on each audit path; and **how many withheld leaves sort between any two disclosed
ones**, since leaf indices are positions in the encoded-path order of section 9.

**Does not learn:** any other path, value or salt - and therefore nothing brute-forceable about
withheld low-entropy fields such as name, national identifier, passport number, birth date or
gender, all of which appear in the reference records.

**The gap count is a real structural leak and is named rather than left implicit.** It is the
residual cost of ordering by path (decision D5a), and it is the one thing ordering by leaf hash would
have hidden. Section 9.3 states what that ordering bought in exchange. In practice the leak is
bounded, because these profiles are published and their path sets are largely known already, so a
verifier who knows the profile can often infer the same information without any disclosure at all -
but "usually inferable anyway" is not "not disclosed", and section 2.2 lists it among the properties
this design does not provide.

#### Why a withheld leaf's salt is the whole ballgame

The audit path already gives a verifier the leaf **hashes** of withheld leaves, and that is safe
only because the salt is missing. Hand over a withheld leaf's salt as well and the leaf becomes
guessable by dictionary search, with no cryptanalysis required: an attacker who knows the path and
the tag enumerates candidate values, computes `leafHash` per section 8 for each, and stops when one
matches. Gender has a handful of candidates, a birth date a few tens of thousands, and a
positive/negative result exactly two.

**Defeating that search is the entire purpose of per-leaf salts**, and it is why section 10 states
the prohibition normatively rather than leaving it inferred.

The failure mode is dangerous because of its shape rather than its difficulty. A disclosed copy that
shipped every salt would **still verify correctly against the root**, because the salts do not
change any leaf hash. It would look valid to every check a verifier runs, while leaking every
withheld field in the record. Nothing about the verification result would indicate a problem.

So the constraint is made structural rather than left to prose. In
`schemas/envelope-2.0.json` the `salts` array is forbidden alongside `disclosure`, which makes a
withheld leaf's salt **unrepresentable** in a disclosed copy rather than merely prohibited: with
that array absent, the per-leaf `salt` field inside `disclosure.leaves` is the only place a salt can
appear, and every entry there belongs by construction to a leaf being revealed. Adding a `salts`
array to the disclosed branch "for symmetry" would reopen exactly this hole.
`docs/conformance-corpus.md` class 17 fails an implementation that emits withheld-leaf salts, because
a rule of this kind that lives only in prose is one an implementer can pass every other test while
violating.

### 10.2 Minimum disclosure floor

**Each profile MUST declare a set of non-redactable paths, and a disclosed copy that omits any of
them MUST be rejected.**

This is adopted from dogtag, where `NON_OBFUSCATABLE` names paths that must be present and cannot
be redacted, enforced inside the integrity gate itself
(`crates/dogtag-standard-rs/src/verify.rs:253` and `:273-277`).

Without it, a holder can withhold the very fields that say what the record is - its type, its
version, its issuer - and the disclosed copy still verifies against a genuine root.
The verifier then has a cryptographically valid proof of something it cannot identify.
Neither source research report specifies this; it comes from dogtag.

The per-profile lists live in `docs/profiles/`.

> **Normative:** at minimum every profile MUST include the five reserved paths that section 11.2
> marks **mandatory** to disclose: `roax.recordType`, `roax.schemaVersion`, `roax.typeMap.id`,
> `roax.recordId` and `roax.issuer.id`.
>
> It MUST NOT extend that minimum to `roax.issuer.keyId`, which section 11.2 marks OPTIONAL to
> disclose. A profile MAY of course add its own paths on top, as the FHIR profile adds
> `resourceType`.

**The floor is doing two different jobs, and the distinction is worth keeping visible.**
`roax.recordType`, `roax.schemaVersion` and `roax.typeMap.id` together select and authenticate the
exact type map under section 4.2, so those three are mandatory **by arithmetic**.
A verifier without them cannot run the procedure at all, and withholding one yields no proof rather
than a weaker one.
`roax.recordId` and `roax.issuer.id` are mandatory **by policy**, because the paragraph above is
about a verifier being able to say what it is looking at.

**`roax.recordId` moved from the first group to the second when decision D4 was ruled**, and the move
is recorded because an earlier draft of this section put it in the first. Under the deleted derived-
salt scheme the record identifier was inside every salt preimage, so a verifier genuinely could not
rebuild a leaf without it. Section 7 no longer has a preimage, so it is not an input to anything a
verifier computes. It stays in the floor on the same ground as `roax.issuer.id`: a disclosed copy
that cannot say which record it is is a cryptographically valid proof of something unidentifiable.

**Why `roax.issuer.keyId` is deliberately not in the floor**, stated here because this is the
section a future editor would edit to put it back. Requiring its disclosure would permanently bind
an anchored record to the key it was issued under: the root is fixed, so a holder whose issuer has
since rotated keys would have to reveal a retired key identifier to make an otherwise valid record
verify, with no path to rotate. That is exactly the foreclosure section 12.2 tells implementers to
design out, so this is not merely the preservation of an earlier call - it is ruled out by a later
and more general constraint. Tightening this floor back to "all reserved paths" would silently
reintroduce it.

### 10.3 Disclosure size

Selective disclosure here costs `O(k log n)`, against `O(n)` for the redaction style
OpenAttestation and dogtag use, which carries one 32-byte hash per **withheld** field.
For an 87-leaf record disclosing 2 fields, that was measured at ~583 bytes versus 2,720 bytes, a
4.7x reduction (the canonicalization research, sections 2.3 and 6.3). The gap widens roughly as
`n / (k log n)`.

---

## 11. The envelope

The envelope is a strawman for review. It is the least settled part of this document.

JSON Schema: [`schemas/envelope-2.0.json`](../../schemas/envelope-2.0.json).

**Two envelope schema versions exist, and this document describes the second.**
The type-map binding of section 4.2 is breaking for the envelope document: `typeMap` becomes a required member, `roax.typeMap.id` becomes a mandatory reserved leaf, and the leaf and salt floors rise from 5 to 6 with it (sections 3.3 and 11.2).
An envelope written before that binding does not validate against `schemas/envelope-2.0.json`, so [`schemas/envelope-1.0.json`](../../schemas/envelope-1.0.json) is retained unchanged in meaning and still governs every envelope issued under it.
A verifier selects one schema per envelope and MUST NOT merge them.
The envelope schema version is NOT the canonicalization version and the two MUST NOT be conflated: both files pin `canon` to the `ROAX-CANON/1` const, and the leaf, salt and root constructions of sections 6 through 8 are identical under both.
The version identifier is one of ROAX's own under section 12.1, so it carries a shape by this project's choice, and the major part moved because documents that validated stopped validating.

### 11.1 Shape

```jsonc
{
  "canon": "ROAX-CANON/1",          // canonicalization version - BOUND INTO THE ROOT
  "hashAlg": "SHA-256",             // hash algorithm - in the domain string AND inside the root
  "recordType": "sg.gov.moh.vaccination-healthcert",
  "schemaVersion": "1.0",
  "recordId": "urn:uuid:...",       // committed INSIDE the root at roax.recordId
  "typeMap": {                      // discovery hint whose ID is committed at roax.typeMap.id
    "id": "sha256:<64 lowercase hex>",
    "version": "1.0.0"
  },

  "root": "<64 hex chars>",
  "leafCount": 93,                  // the UNION - record leaves plus reserved leaves (section 3.3)

  "issuer": {                       // identity, committed INSIDE the root at reserved paths
    "id": "did:web:example.gov",
    "keyId": "did:web:example.gov#key-1"
  },

  "anchor": {                       // OUTSIDE the root - routing hint only, never authority
    "chainId": 0,
    "registry": "0x...",
    "txHash": "0x...",
    "anchoredAt": "2026-07-28T00:00:00Z"
  },

  "disclosure": { /* present in a DISCLOSED copy only */ },
  "record":     { /* present in a FULL copy only */ },

  "salts": [                        // present in a FULL copy only, forbidden in a disclosed one
    { "segments": [ {"key":"roax.recordId"} ], "salt": "<32 hex chars>" }
    /* ... one entry per leaf of the union, so salts.length == leafCount ... */
  ]
}
```

There is no master-salt field and no seed field of any kind, and adding one would be a violation:
section 7 generates each leaf's salt independently, and section 7.3 rule 3 forbids an envelope from
carrying any value from which a withheld leaf's salt could be obtained.

The `anchor` values above are illustrative placeholders.
No chain id, registry address or contract set is treated as permanent by this document.

`leafCount` counts the **union** defined in section 3.3, so it includes the reserved leaves of
section 11.2 and not only the leaves the record itself produced. The value shown is the 87-leaf
vaccination record of section 10.3 plus its six reserved leaves, `issuer.keyId` being present
here. An implementation that counts the record alone reports a `leafCount` that does not match its
own root, and every inclusion proof it issues is bound to the wrong tree size.

> **Normative:** `leafCount` is neither a domain component nor a leaf, deliberately. A leaf stating
> the leaf count would change the leaf count, so there is no fixed point to commit.
>
> **`leafCount` is therefore NOT authenticated in a disclosed copy.** It sits outside the root, so
> section 11.3 applies to it in full: it is a hint, and a verifier MUST NOT treat it as authority for
> anything.
>
> In a **full copy** the verifier derives the leaf count itself while rebuilding the tree, and
> **a derived count that disagrees with the `leafCount` field MUST be a rejection**, not a warning
> and not a silent preference for either value.

That last MUST is stated because the field is required in every envelope while the full-copy path
recomputes the same quantity, and a specification that requires a field without saying what a
disagreement means is inviting two implementations to resolve it differently.

#### An earlier version of this section claimed a binding that does not exist

**It said that in a disclosed copy `leafCount` was already bound by the RFC 9162 proof, because tree
shape is uniquely determined by the number of leaves, so a wrong `leafCount` would make the audit
path fail. That is false, and it was measured false rather than argued false.**

RFC 9162 section 2.1.3.2 takes the tree size as an **input** to verification, not as something it
recovers. An attacker who controls `leafCount` therefore controls the shape the verifier rebuilds,
and can choose a shape in which a node of his choosing sits where a leaf should be.

Demonstrated on an 8-leaf tree, reproduced on Node v22.21.0 while this correction was written:
presenting the internal node `MTH(L[0:4])` as the leaf at index 0, with a **forged tree size of 2**
and the single-element audit path `[MTH(L[4:8])]`, **verifies against the genuine root**. The same
node with the honest tree size of 8 fails, and so does an honest leaf's proof under a forged size,
which is why a *random* wrong `leafCount` usually is caught and a *chosen* one is not. Being caught
by accident in the common case is not a binding.

**The defence that does exist is section 10 step 2, and it is already normative.** A verifier
recomputes `leafHash` from the disclosed path, tag, value and salt and MUST NOT trust a
caller-supplied leaf hash. Every leaf hash is `H(0x00 ‖ ...)` and every internal node is
`H(0x01 ‖ ...)` (sections 8 and 9.1), so a recomputed leaf hash cannot equal an internal node except
by defeating second-preimage resistance. The attack above requires handing the verifier a leaf hash,
which a conforming verifier never accepts.

**Two consequences follow and both are stated rather than left implicit.** A verifier MUST NOT skip
step 2 on the grounds that the tree size makes the position unambiguous, because it does not. And
`leafCount` MUST NOT be used as a check on anything, in either copy kind, beyond the full-copy
equality above where the verifier derives the quantity itself.

This correction came from the conformance corpus work, which measured the case while building class
9. It is recorded here rather than quietly fixed, because a specification that claimed two
independent defences and had one is exactly the shape of error section 1.1 makes the corpus a
release gate to catch.

**Exactly one of `record` and `disclosure` MUST be present.**
A verifier that sees both MUST reject. The JSON Schema encodes this as two `allOf` clauses, because
it is the security-relevant invariant and is easy to get wrong when written informally.
`salts` follows `record`: it is REQUIRED in a full copy and FORBIDDEN in a disclosed one
(section 7.3), and its length equals `leafCount` because it carries one entry per leaf of the union.

### 11.2 Reserved leaves, and the prefix rule

The envelope fields that say what a record **is** are committed **inside** the root as ordinary
leaves whose single KEY segment uses the reserved ASCII prefix `roax.`.
Only genuinely mutable routing hints stay outside.

These are ordinary leaves in every respect. They are salted per section 7, hashed per section 8, and
sorted into the same order as record leaves per section 9. Nothing about them is special-cased
except where they come from.

#### The reserved leaf set

**Each reserved path is a SINGLE `KEY` segment whose key is the literal dotted string.**
`roax.recordType` is one segment `KEY("roax.recordType")`, not two segments `KEY("roax")` then
`KEY("recordType")`.

| Reserved leaf | Path segments | Tag | Value | Emitted | Disclosure |
|---|---|---:|---|---|---|
| `roax.recordType` | `[KEY("roax.recordType")]` | 2 STRING | the envelope's `recordType` | always | mandatory |
| `roax.schemaVersion` | `[KEY("roax.schemaVersion")]` | 2 STRING | the envelope's `schemaVersion` | always | mandatory |
| `roax.typeMap.id` | `[KEY("roax.typeMap.id")]` | 2 STRING | the envelope's `typeMap.id` | always | mandatory |
| `roax.recordId` | `[KEY("roax.recordId")]` | 2 STRING | the envelope's `recordId` | always | mandatory |
| `roax.issuer.id` | `[KEY("roax.issuer.id")]` | 2 STRING | the envelope's `issuer.id` | always | mandatory |
| `roax.issuer.keyId` | `[KEY("roax.issuer.keyId")]` | 2 STRING | the envelope's `issuer.keyId` | only when `issuer.keyId` is present | OPTIONAL |

Every reserved leaf is a STRING, so every value is normalized to NFC and encoded per section 6.1
like any other string.

**Why single-segment rather than one segment per dot component.** Under the per-component reading, a
record carrying an ordinary top-level field named `roax` collides with the reserved namespace, and
that is genuinely reachable rather than hypothetical: these record families already carry
non-clinical top-level keys such as `$template`, `notarisationMetadata` and `issuers`, so the
top-level namespace is open-world and belongs to whoever writes the profile. Under the
single-segment reading a collision needs a record field named literally `roax.recordType`, and FHIR
element names do not contain dots. This is also what length-prefixed encoding makes natural: it is
the same property section 5.1 already relies on to keep a nested `a.b` and a literal dotted key
`"a.b"` provably distinct with no rule at all.

**Three of the five always-emitted leaves are mandatory to disclose by arithmetic, not by policy.**
`recordType`, `schemaVersion` and `typeMap.id` together select and authenticate the exact map under
section 4.2, so a verifier that does not have all three cannot run the verification procedure.
Withholding any one does not produce a weaker proof; it produces no proof.
`roax.recordId` and `roax.issuer.id` are policy choices, and both are in the floor because section
10.2 requires a disclosed copy to say what it is and who issued it.

**`roax.recordId` was arithmetic and is now policy.** It was an input to every salt under the
derived-salt scheme this document carried before decision D4 was ruled D4b; section 7 has no preimage
now, so nothing a verifier computes consumes it. Its commitment as a leaf is unchanged, and so is its
place in the floor. Section 10.2 states the same split from the disclosure side.

**`roax.issuer.keyId` is committed but OPTIONAL to disclose**, which is the one place this set
departs from the pattern. Requiring its disclosure would break key rotation on already-anchored
records: the key that signed an issuance is fixed in the root forever, so a holder whose issuer has
since rotated keys would be forced to reveal a retired key identifier to make an otherwise valid
record verify. That is the same trap section 11.3 records for mutable routing fields, arriving from
a different direction.

**This is ruled out by section 12.2, not merely preferred.** An anchored root freezes what it
commits, so a rule that forced disclosure of the key identifier would leave an already-issued record
with no rotation path at all, which is the precise shape of foreclosure the future-proofing
constraint exists to prevent. Section 10.2 therefore narrows the minimum-disclosure floor to the
five mandatory paths rather than to every reserved path, and says so in the place an editor would
otherwise widen it back.

`issuer.keyId` is also the one reserved leaf whose *presence* varies. **An absent `issuer.keyId`
emits no leaf**; it MUST NOT be emitted as a NULL leaf or as an empty string, because those are
three different roots and only one of them can be right. The reserved leaf count is therefore 5 or 6.

**Two leaves that an earlier draft committed have been removed, and the reasons differ.**
`roax.hashAlg` was removed because a leaf cannot bind the algorithm it is hashed under at all
(section 7.4). `roax.canon` was removed because it is redundant rather than wrong: `canon` is
already inside `DOMAIN` in every leaf preimage (section 8), so a v2 library cannot be
tricked into applying v2 rules to a v1 record, and the leaf paid roughly 290 bytes on every
disclosed copy for a property already bought.

Without this table the specification's headline claim in the preamble does not hold, which is why
that claim names this section. Under section 5 the name `roax.issuer.id` could otherwise legally
encode as three segments, as two, or as one key containing dots, and each produces a different root.

These leaves are inputs to sections 8 and 9, so labelling section 11 a strawman does not cover them:
the envelope's **shape** is unsettled, but the leaves it commits and their encoding are not.

#### The reserved-namespace guard

> **Normative:** no record-supplied path may have, as its **first segment**, a `KEY` whose
> NFC-normalized key begins with the ASCII prefix `roax.`.
>
> The guard is applied at the input boundary, to the **decoded, NFC-normalized key of that one
> segment**. It is not a test against a rendered display path: section 5.2 forbids reasoning over
> display paths, and an implementation that reconstructs `a.b[0].c` in order to run this check is
> doing the thing that section forbids.

**The guard checks the first segment only**, because every reserved path is a single segment. A path
like `[KEY("a"), KEY("roax.foo")]` differs from every reserved path in segment count and cannot
collide with one, so rejecting it would be over-broad. Applying the check to every segment is the
most likely over-implementation and is wrong.

**The guard MUST compare the NFC-normalized key, not the bytes as received.** Section 6.1 normalizes
keys to NFC before they are encoded and hashed, so a check performed on the raw bytes is checking a
different string from the one that actually gets committed. That the two differ at all is easy to
demonstrate: U+212A KELVIN SIGN is the three bytes `e2 84 aa` as received and normalizes under NFC
to ASCII `K`, the single byte `0x4b` (verified on Node v22.21.0). The rule is the general one -
**check the bytes you commit, not the bytes you received** - and it applies here because this guard
and the hashing path must agree about what the key is.

> **Stated at the strength of the evidence: this MUST is currently unobservable at the guard, and
> that is a fact about today's prefix rather than about the design.**
> No character normalizes into `roax.`. Scanning every assigned code point on Node v22.21.0 finds no
> non-ASCII character whose NFC form contains `r`, `o`, `a`, `x` or `.`; the only ASCII letter
> reachable that way at all is uppercase `K`, from U+212A. So for every input a record can actually
> supply, checking before or after normalization gives the guard the same verdict, and U+212A above
> is evidence that NFC can cross into ASCII rather than an instance of this case.
>
> The MUST stands anyway, for three reasons. It costs nothing. It keeps this guard and the hashing
> path reasoning about the same string, which is the property that has to hold rather than the
> coincidence that currently makes it moot. And the coincidence is not load-bearing by design: a
> reserved name that later contained a character with a canonical singleton decomposition would make
> the ordering observable immediately, and the rule needs to be in place before that, not after.
> `docs/conformance-corpus.md` class 15 records the same limit rather than promising a vector that
> cannot be built.

Consequences worth stating, because a guard written against the earlier multi-segment model gives
different answers:

- A record key literally named `roax.recordType`, or any other reserved name, is **rejected**. It is
  the reserved path, so this is a direct collision rather than a near miss.
- A record key named `roax.anythingElse` is **rejected**. The guard is on the `roax.` prefix within
  that first key, not on the exact reserved names, so a future reserved leaf cannot be squatted
  before it is defined.
- A record key literally named `roax`, with no dot, is **accepted**. It is an ordinary record field
  that collides with nothing, because no reserved path is the single segment `KEY("roax")`.
- A record key named `roaxX` is **accepted**, for the same reason.

The last two reverse an earlier draft of this document, which rejected both. That draft was written
against a string-path model this specification deliberately departed from, and rejecting an ordinary
field named `roax` is over-broad once reserved paths are single dotted segments.
`docs/conformance-corpus.md` class 15 carries all four cases.

The prefix form of the guard is adopted from dogtag, which changed to it deliberately and recorded
why: its `owner.` namespace is guarded by prefix "vs the old exact-match-only guard" so that "no
future attribute can be named into ambiguity with an owner-control leaf"
(`crates/dogtag-standard-rs/src/profile_tree.rs:54-66`). What transfers is the argument, not the
string operation. Guarding only the exact reserved names would leave `roax.recordIdX` reachable,
which is dogtag's point restated in this encoding.

This is inference applied to a new case: dogtag's comment establishes that an exact-match guard was
insufficient in dogtag's namespace, and the same structural argument applies to `roax.`.
It is not a second independently observed failure.

### 11.3 Anything outside the root is attacker-controlled

Stated normatively: **fields outside the root are hints and never authority.**

dogtag paid for this. Its `check_integrity` folds only `data` plus `privacy.obfuscated`, leaving
the whole `issuer` block outside the root - "including `documentStore`, the address every
`isValid()` is called against. Point `documentStore` at a contract you control that returns `true`
from `isValid`, and integrity AND the on-chain read both pass" (`AGENTS.md:333`, condensed).
The fix was an extra mandatory issuer-whitelist pillar that exists only to compensate.

The tension is real in both directions, and dogtag hit both ends:

- Put routing metadata **inside** the root and a deployed record cannot be re-stamped when
  infrastructure moves. dogtag hit exactly this with `statusBaseUrl` and deliberately kept it
  outside, so that stamping it "neither disturbs an anchored `R` nor lets a forged value make an
  invalid record verify" (`crates/dogtag-standard-rs/src/wrap.rs:75-85`).
- Put it **outside** and every consumer must re-derive authority from the anchoring layer and never
  trust the document.

The split above puts identity inside and routing outside. This is decision D8 and it is **ruled**,
in that form.

**A normative sentence is not enough on its own, and this is the one place this document says so
about its own prose.** dogtag had the equivalent understanding written down and still shipped the
`documentStore` bug, then needed an entire extra mandatory issuer-whitelist pillar to compensate for
it. Prose that an implementer agrees with and then does not apply is the failure mode here, not
prose an implementer disputes.

> **Normative:** the conformance corpus MUST carry vectors that **fail** an implementation which
> treats an outside-the-root field as authority. `docs/conformance-corpus.md` class 18 defines them,
> and it covers the four surfaces where the mistake is reachable: `hashAlg`, which section 7.4
> requires a verifier to take from the anchoring registry; `anchor`, which names the registry a
> naive verifier would read; `typeMap`, whose ID is only authoritative after the content-ID and
> reserved-leaf checks in sections 4.2 and 10; and the other top-level copies of reserved-leaf
> values, which a verifier can trust in place of the leaves actually committed inside the root.

A test that catches this costs a day. The pillar dogtag needed to compensate for not catching it cost
far more.

---

## 12. Versioning

Five axes, deliberately not collapsed:

| Axis | Field | Changes when | Inside the root? |
|---|---|---|---|
| Canonicalization | `canon` | the hashing rules change | **Yes**, via `DOMAIN` in every leaf preimage |
| Hash algorithm | `hashAlg` | a record selects a different hash family | **Via `DOMAIN` only.** Not a leaf: a leaf cannot bind the algorithm it is hashed under. Authority comes from the anchoring registry (section 7.4) |
| Record schema | `recordType` + `schemaVersion` | a profile publishes a new version | **Yes**, as ordinary reserved leaves |
| Type-map artifact | `typeMap.id` + `typeMap.version` | a base map or issuer-scoped additive child is published | **Yes.** The exact ID is an ordinary reserved leaf, and it transitively binds the artifact version (sections 4.2 and 11.2) |
| Envelope / routing | `anchor` | deployment changes | **No** |

Because `DOMAIN` is folded into every leaf hash (section 8), the
canonicalization version is **cryptographically bound**. A v2 library reading a v1 record reads
`canon: "ROAX-CANON/1"` and must run the v1 rules; it cannot accidentally apply v2 rules and get a
matching root, and it cannot be tricked into it, because the root commits to the version.

**The algorithm axis is weaker and section 7.4 says so precisely.** `DOMAIN` being
algorithm-qualified removes cross-algorithm root ambiguity by construction, but it does not stop an
attacker who computes an entire record under a weak algorithm, because he computes the domain string
under that algorithm too. Authority for `hashAlg` comes from the anchoring registry and from the
verifier's own allow-list, not from the document.

The algorithm axis is separate from the canonicalization axis on purpose. Swapping the hash while
keeping path encoding, type tags, value encoding, leaf composition and tree shape identical is a
change of `hashAlg`, not of `canon`, and section 7.4 records what still has to be pinned before the
second algorithm can be used.

**Rule for libraries:** verification code for every published `canon` version is retained forever;
issuance code exists only for the current one.

Keeping these axes separate is adopted from dogtag, which keeps its on-chain contract-set axis and
its artifact axis in separate keyspaces for exactly this reason: an artifact rotation
"must NOT change what an already-minted tag claims. Resolve the two independently; never collapse
them back into one version" (`crates/dogtag-standard-rs/src/wrap.rs:30-42`).
That lesson is why this document does not treat any contract set as permanent.

`hashAlg` is a permanent, per-record selection between a ZK-friendly and a non-ZK hash, and both
families are first-class. That is decision B in `docs/decisions.md`, and it is **ruled**, which is
what makes the binding above mandatory rather than tidy: an algorithm identifier that a verifier
acts on cannot sit outside the root.

Hash agility is not free, and the cost is unchanged by the ruling: two records with identical
content and different `hashAlg` have different roots, and every verifier eventually implements both.
Only `SHA-256` has a defined construction in `ROAX-CANON/1`; `Poseidon-BN254` is registered and its
parameterization is not yet pinned, so it MUST NOT be issued against. See section 7.4.

### 12.1 Version identifiers keep their owners' rules

> **Normative:** `schemaVersion` and `unicodeVersion` are opaque and matched only for equality.
> ROAX-owned `corpusVersion` and `typeMapVersion` retain three-part semver shape, but a verifier
> still MUST NOT range-resolve a type map or choose its latest version, under section 4.2.

`schemaVersion` is an **opaque, profile-defined label**. It is validated by exact match against the
profile registry (`docs/profiles/`), never by shape, and `schemas/envelope-2.0.json` and
`schemas/type-map-artifact-1.0.json` therefore constrain it to a non-empty string and nothing more.

**An earlier draft imposed a dotted numeric pattern, and the evidence is that no such pattern can be
correct.** FHIR's own `CapabilityStatement.fhirVersion` enumeration holds exactly 22 values, of
which 4 are two-part (`0.01`, `0.05`, `0.06`, `0.11`) and 18 are three-part. A two-part pattern
admits 4 of 22 and a three-part pattern admits 18 of 22, so there is no dotted numeric pattern that
accepts FHIR's own version identifiers. The premise that the field has a shape is what was wrong,
not the choice of shape. Counted by reading the shipped `fhir/4.0.1/schema.json` in place, and
re-counted on Node v22.21.0.

Two further reasons, both external:

- FHIR states outright that these strings are not orderable: "There is also no expectation that
  versions can be placed in a lexicographical sequence." That sentence is repeated across 28
  resource definitions in the shipped schema.
- SD-JWT VC reached the same design independently. It carries no version field at all: the type
  identifier `vct` is opaque, and an incompatible change means a new `vct` value rather than a
  version bump.

And one internal reason, which is the decisive one: **nothing in this protocol orders externally
owned versions.**
The only structural use of `schemaVersion` is exact match as one component of the type-map selection
tuple in section 4.2.
A shape constraint that no code path needs can only reject valid input.

**The dividing line, stated so it is not re-litigated per field.** A version identifier this project
**owns** may carry a shape; a version identifier defined **elsewhere** is opaque.

| Field | Owner | Constraint |
|---|---|---|
| `corpusVersion` (`schemas/conformance-corpus-2.0.json`) | ROAX | three-part semver, legitimately |
| `typeMapVersion` (`schemas/type-map-artifact-1.0.json`) | ROAX | three-part semver, exact metadata rather than a range selector |
| `schemaVersion` (envelope and type map) | the profile, and beyond it FHIR or a health authority | opaque, exact match only |
| `unicodeVersion` (corpus) | the Unicode Consortium | opaque, non-empty; `15.1` is the canonical form for this pin |
| `canon` | ROAX | a `const` domain string, and not a version field at all |

**The honest cost.** A typo in `schemaVersion` is no longer caught by JSON Schema. It is caught one
step later and less pleasantly, by type-map lookup failing closed (section 4.2, decision D7). Range
comparison becomes inexpressible, which costs nothing, because FHIR says these strings are not
orderable and nothing here compares them.

### 12.2 Future-proofing is a standing constraint, not a section

Every rule in this document is written to be extended without reissuing anything. Stated as
requirements rather than as intentions:

- **New profiles and new versions arrive by a registry entry, never by editing this specification.**
  The registry is `docs/profiles/`, one document per `recordType`. This is why
  `schemas/envelope-2.0.json` constrains `recordType` to a form rather than to a closed list: the
  registry, not the schema, is the extension point.
- **The registry is itself versioned**, so that "which profiles existed when this record was issued"
  is answerable rather than assumed.
- **An unknown profile MUST fail closed, with a stated reason, and MUST NEVER default to a guess.**
  A silent default is exactly how two libraries diverge, which is the failure this whole project
  exists to prevent. This is the same rule section 4.2 applies to an unknown path, applied one level
  up.
- **The reserved-leaf set, the algorithm set and the profile set MUST each be extensible without
  invalidating anything already issued.**

**The honest limit, because a stronger promise would be false.** An anchored root **freezes** the
content it commits: that is what an anchor is for, and any design that let an issued record's
committed content change would have destroyed the property being sold. So "future-proof" here can
only mean one thing, and it is worth saying in full:

> **New records gain capabilities; existing records keep exactly what they were issued with; both
> remain verifiable.**

An upgrade that required re-anchoring every existing record would not be an upgrade, it would be a
migration, and this document does not promise to avoid one by fiat. What it promises is that adding
a profile, an algorithm or a reserved leaf does not force one.

---

## 13. Why not JCS, dCBOR or RDFC-1.0

### 13.1 JCS (RFC 8785) is disqualified, and here is how to check

RFC 8785 section 3.2.2.3 mandates:

> "Such data MUST be serialized according to Section 7.1.12.1 of [ECMA-262], including the 'Note 2'
> enhancement."

That is ECMAScript `Number::toString` over an IEEE-754 double.

**Reproduce it.** Save as `jcs.mjs` and run with Node >= 21:

```js
const lits = ["0.010","0.01","1.50","1.5","2.0","1e2","100",
              "9223372036854775807","1234567890123456789.1"];
const out = new Map();
for (const l of lits) {
  const s = String(JSON.parse(l));
  console.log(`  ${l.padEnd(22)} -> ${s}`);
  if (!out.has(s)) out.set(s, []);
  out.get(s).push(l);
}
console.log("collisions:");
for (const [s, ls] of out) if (ls.length > 1)
  console.log(`  ${ls.join("  ==  ")}   both -> "${s}"`);
console.log("1.4e+9999 ->", JSON.parse("1.4e+9999"));
```

Output, on Node v22.21.0, a conformant implementation of that exact ECMA-262 clause:

```
  0.010                  -> 0.01
  0.01                   -> 0.01
  1.50                   -> 1.5
  1.5                    -> 1.5
  2.0                    -> 2
  1e2                    -> 100
  100                    -> 100
  9223372036854775807    -> 9223372036854776000
  1234567890123456789.1  -> 1234567890123456800
collisions:
  0.010  ==  0.01   both -> "0.01"
  1.50  ==  1.5   both -> "1.5"
  1e2  ==  100   both -> "100"
1.4e+9999 -> Infinity
```

`0.010` and `0.01` are values FHIR R4 says **SHALL** be treated as different (section 6.2).
JCS gives them the same digest.
`9223372036854775807` is silently corrupted.
`1.4e+9999` is JSON-legal and FHIR-pattern-legal, and JCS section 3.2.2.3 requires the
implementation to terminate with an error.

This is not an obscure corner. `decimal` is reachable from the shipped `lite-schema.json` - the one
the PDT and recovery healthcerts `$ref` - at 15 sites, including `Quantity.value`, `Observation`
via `valueQuantity`, `Extension.valueDecimal`, `Money.value`, `Range`, `Ratio`, `SampledData` and
`Timing_Repeat.duration`.

**Conclusion: JCS cannot be the canonical form for a FHIR-carrying protocol.**
Not "is risky" - is non-conformant with a FHIR R4 `SHALL`.

Two further JCS problems, also reproducible with the script in
`docs/conformance-corpus.md` appendix:

```
--- UTF-16 (JCS 3.2.3) vs UTF-8 key order ---
  UTF-16: U+007A , U+00E9 , U+1F600 , U+FF3A
  UTF-8 : U+007A , U+00E9 , U+FF3A , U+1F600
  same?  false
--- JCS s3.1 forbids normalization ---
  NFC bytes: c3a9  NFD bytes: 65cc81
  render identically: true  JCS-distinct: true
```

RFC 8785 section 3.2.3 sorts by UTF-16 code units, which the RFC itself admits is a
JavaScript/Java/.NET artifact. Rust, Go and Swift must convert to UTF-16 first, and the orders
genuinely differ. And RFC 8785 section 3.1 requires components to "preserve Unicode string data
'as is'", so two records that render identically hash differently - defensible for a signature over
bytes-you-received, wrong for a health record that passes through a normalizing form field.

Worth saying plainly: **JCS is the closest specified thing to what OpenAttestation does.**
Its number rule *is* JavaScript's number rule. Adopting JCS would be adopting a better-documented
version of the thing this project exists to replace.

### 13.2 Deterministic CBOR is the strongest rejected option

RFC 8949 is STD 94 and its ecosystem is excellent. Three reasons it is not the pick:

1. RFC 8949 section 4.2.2 explicitly does **not** pin what matters. It says the protocol "needs to
   specify whether smaller integers are also expressed using these tags", lists three possible
   int-versus-float rules without mandating one, and requires the protocol to pick a NaN
   representation. Adopting it relocates the design work into an application profile you still have
   to write and test; it does not remove it.
2. dCBOR, which does pin those, is `draft-mcnally-deterministic-cbor-17` with no formal IETF
   standing, and its section 2.5 numeric reduction forces integral floats to integers - so `2.0`
   becomes `2`, reintroducing the FHIR precision bug from a different direction.
3. **It gives no selective disclosure.** You would canonicalize to CBOR and still need a per-field
   commitment layer on top, which is this scheme, built twice.

If a binary wire format is wanted, the right move is to keep this document's semantics and serialize
the *envelope* in dCBOR - not to make dCBOR the digest rule.

**That is decision D3 and it is ruled: JSON for version 1, with deterministic CBOR permitted later as
a transport.** JSON is what every FHIR toolchain, every health authority and every existing
healthcert already speaks, so it costs an adopter nothing, and the property that actually matters -
the digest rule being independent of the wire format - is what keeps a future binary transport from
becoming a `canon` bump.

> **Normative:** a serialization format MUST NOT become the digest rule. The value, leaf and tree
> constructions of sections 6, 8 and 9 are defined over byte strings and are the only inputs to a
> root. In particular, deterministic CBOR MAY be used to carry an envelope and MUST NOT be used to
> compute one.

The prohibition is the load-bearing half of this ruling. `draft-mcnally-deterministic-cbor-17`
section 2.5 forces integral floats to integers, so `2.0` becomes `2`, which is the section 13.1
precision bug arriving from a direction nobody would be watching for it.

### 13.3 RDFC-1.0 has a documented denial-of-service class

RDFC-1.0 is a W3C Recommendation (21 May 2024) and is the most formally rigorous option.
It is wrong here for reasons the specification itself states.

The algorithm exists to solve blank-node labelling, which its section 1 calls "the graph isomorphism
problem, a problem that is believed to be difficult to solve quickly in the worst case".
Its section 4.4.3 requires implementations to "defend against potential denial-of-service attacks
by raising suitable exceptions and terminating early", and section 7.1 covers dataset poisoning.

A protocol whose canonical form has a documented DoS class, whose defence is an
implementation-chosen iteration limit, cannot give the same digest in every language by
construction: **two conformant implementations with different limits disagree on which records they
will canonicalize at all.** Add that FHIR-to-RDF needs the FHIR RDF ontology and JSON-LD context
resolution, that no Swift implementation was found, and that it provides no selective disclosure.

---

## 14. Reconciliation with dogtag

The canonicalization research read dogtag closely and built this scheme on its family.
The OpenAttestation audit, which is where the abstraction-boundary conclusion came from, **did not
reference dogtag at all.** So the boundary conclusion was reached without checking how dogtag drew
the same boundary. This section closes that gap and states, item by item, where dogtag's shape is
adopted and where it is departed from.

All dogtag references are to the `dogtag-mono-repo` working tree as read on 2026-07-28, by file and
line. That repository is internal and is not linked here.

### 14.1 The boundary question, checked

The audit's recommended boundary (its section 6.3) is that the protocol layer knows only: protocol
version, algorithm identifiers, a committed profile identifier, the typed payload, salted
commitments and disclosure proofs, and optional anchoring metadata - while everything clinical lives
in profile layers above.

**dogtag draws the boundary differently and more narrowly.**
Its `schema.rs` is a single hard-coded credential validator, not a pluggable profile registry.
The file header says it "Operates on a pre-wrap, plain `serde_json::Value` credential object", and
its entry point is `validate_schema(c: &Value)` with one credential shape and jurisdiction rules
compiled in, including its own JSON-LD context URI constant
(`crates/dogtag-standard-rs/src/schema.rs:1-9` and `:159`).

**The honest reading is that this is not evidence against the audit's boundary.**
dogtag never needed a profile registry because it has exactly one record family.
ROAX has four, and two of them carry structurally incompatible `fhirBundle` layouts - the PDT and
recovery healthcerts wrap a genuine FHIR Bundle whose entries contain a nested `.resource`, while
the vaccination healthcert puts `resourceType` and `fullUrl` directly on each entry
(audit sections 2.3 and 5.1).

So: **dogtag's single-profile shape is deliberately NOT adopted.** The audit's boundary stands,
having now been checked against the one prior implementation in the organization rather than
assumed. The four profile documents under `docs/profiles/` exist because of it.

### 14.2 Adopted, departed, and why - full table

| Item | dogtag | ROAX | Why |
|---|---|---|---|
| Typed leaf with mandatory type tag | `hash_leaf(keypath, salt, typedScalar)` over path, salt, type tag, value plus a domain separator (`leaf.rs:17-29`); tags at `types.rs:4-13` with the comment that the tag exists so `"5"` does not collide with `5` | **Adopted**, section 8 | This is the core idea and it is sound. |
| Numbers canonicalized over the input string, never a float | `encode.rs:35-36` is explicit about it | **Adopted**, section 6.2 | Same requirement, stronger reason: FHIR. |
| NFC normalization | `encode.rs:11` | **Adopted**, section 6.1 | Also resolves the conflict with the audit's section 15.3; see section 6.1. |
| Pinned Unicode version | `encode.rs:6-7`, `UNICODE_VERSION = "15.1"` | **Adopted**, section 6.1 | Code-level evidence only, not a written scar. Cited at that strength. |
| Unpaired-surrogate rejection | `packages/dogtag-standard-ts/src/encode.ts:14-28` | **Adopted**, section 3.2 | The rejection must be explicit on the JavaScript side or implementations diverge. |
| Record identifier in the KDF preimage | `AGENTS.md:1744-1745`; builder at `profile_tree.rs:14-24` | **No longer applicable**, section 7.1 | Adopted while this document specified derived salts, as defense in depth for unlinkability. Decision D4 was ruled D4b, so there is no KDF and no preimage to bind it into. The property it defended is now structural: independent salts have no shared secret to reuse. |
| One preimage builder, never a second | `AGENTS.md:1747-1751`: "A second preimage builder is the drift" | **Adopted**, section 8 | dogtag's consent key stayed wallet-level for a whole release because it had its own hand-rolled preimage. Under D4b `leafHash` is the only preimage builder in the design, which is the shape this lesson recommends. |
| Non-redactable path set | `NON_OBFUSCATABLE`, `verify.rs:253`, enforced at `:273-277` | **Adopted**, section 10.2 | Neither research report specifies it. Without it a disclosed copy can hide what the record is. |
| Prefix-guarded reserved namespace | `OWNER_NAMESPACE_PREFIX`, `profile_tree.rs:54-66`, changed from exact-match | **Adopted**, section 11.2 | Applied by inference to `roax.`; stated as inference in 11.2. |
| Never trust a fold primitive as a membership check | `merkle.rs:86-91`; `verify.rs:263-264` rebuilds the whole tree | **Adopted**, section 10 | The recompute-the-leaf-from-fields step is mandatory. |
| Explicit tree-shape recovery from a proof | `Sibling \| Promote` steps, `merkle.rs:57-64` | **Convergent, not adopted verbatim** | RFC 9162 gets it structurally from `(index, size)`. Same requirement, obtained for free. |
| Separate version axes, never collapsed | `wrap.rs:30-42` | **Adopted**, section 12 | |
| Routing metadata outside the root, as hint only | `wrap.rs:75-85`; the cost recorded at `AGENTS.md:333` | **Adopted**, section 11.3 | |
| Decimal trailing zeros stripped | `encode.rs:51-59` pops trailing `0` then a trailing `.` | **DEPARTED**, section 6.2 | `0.010` becomes `0.01`, which FHIR R4 says implementations SHALL NOT do. Correct for a pet's weight, wrong for a lab result. |
| Empty array, empty object and null collapse to one leaf | `flatten.rs:96-115` maps all three to `TypedScalar::Null` | **DEPARTED**, tags 6 and 7 in section 6.1 | A real collision. In FHIR the difference between "no entries" and "field absent" can be clinically meaningful. |
| String key path with reserved characters rejected | `flatten.rs:17-20` rejects `.`, `[`, `]` in keys | **DEPARTED**, section 5 | Length-prefixed encoding needs no rejection rule and no escaping. |
| Poseidon over BN254 | `poseidon.rs`, `field.rs` | **DEPARTED as the only hash**, and registered alongside SHA-256 | Measured 52-63x slower on real records, no native primitive in Swift, Kotlin or Go, so it cannot be the sole hash. Decision B is ruled: both families are first-class and selected per record via `hashAlg`, which is why section 7.4 binds the algorithm identifier into `DOMAIN` and into the root. Only SHA-256 has a defined construction in v1; the Poseidon parameterization is not pinned. |
| Sorted-by-hash commutative tree with odd promotion | `merkle.rs:22-46` | **DEPARTED**, RFC 9162 | Position-bound, published, and no commutative-fold hazard. |
| Stored 16-byte salt per leaf inside the document | `wrap.rs` | **ADOPTED**, section 7 | This reverses an earlier draft, which derived salts from a per-record master salt and departed from dogtag on size. Decision D4 was ruled D4b: dogtag's choice removes a silent cross-record linkage hazard that no MUST can reliably guard, and the storage it costs is about 1.4 KB on an 87-leaf record. dogtag reached the same answer for the same reason. |
| Single hard-coded profile validator | `schema.rs:1-9`, `:159` | **DEPARTED**, per-family profiles | See section 14.1. |
| Four-language agreement via two implementations plus FFI | Rust plus TypeScript are independent; Swift and Kotlin call Rust through UniFFI 0.28 (`Cargo.toml:33`; the generated Swift binding is `apps/ios/DogTag/dogtag_standard.swift`). There is no Swift or Kotlin Poseidon in the repository | **Structural lesson, decision D / D10 is ruled to five independent builds** | See 14.3. |

### 14.3 The structural lesson about five libraries

dogtag got four-language agreement by having **two** implementations, not four, and shipping one of
them to two more platforms over FFI. Agreement between the two real implementations is enforced by
a shared JSON test-vector corpus, `packages/dogtag-standard-ts/testvectors.json`, which was
inspected directly and contains **15 leaf vectors, 5 `bytesToField` vectors, 11 Merkle-root vectors
and 110 inclusion vectors** plus the field modulus. `crates/dogtag-standard-rs/tests/ffi_parity.rs`
drives the Rust side over the same file.

ROAX wants Go as well, and Go over UniFFI is awkward - UniFFI has no first-class Go backend.

**If ROAX ships five genuinely independent libraries, the conformance corpus stops being a safety
net and becomes the entire enforcement mechanism.** That is why `docs/conformance-corpus.md` is
normative rather than decorative.

dogtag also supplies the warning for that path. Its TypeScript `verify` silently diverged from the
Rust one and the divergence is **recorded rather than fixed**, because it has no production consumer
(`AGENTS.md:357`, which states the divergence in detail and says "Do NOT wire it into a product
surface before reconciling it with the Rust implementation"). An independent implementation not
covered by the corpus will drift.

This is decision D / D10 and it was ruled to five independent, corpus-enforced builds on 2026-07-29.

---

## 15. Decisions: what is ruled and what is still open

**Two of the open decisions belong to the project owner.**
This specification takes no position on any of them and defines nothing that depends on one.

- **A** - whether roax-lib needs EU recognition, which would mandate SD-JWT VC and ISO mdoc export
  profiles.
- **C** - what happens to the Singapore healthcerts already issued under OpenAttestation.

**D was ruled on 2026-07-29:** five independent, corpus-enforced libraries rather than a shared core over a binding layer.
A further open question, D14, was identified after the engineering rulings below and is stated at the end of this section.

**B is ruled and is no longer open in the "which one" sense.** ZK-friendly and non-ZK hashes are
both first-class and selectable per record, permanently, via `hashAlg`. That ruling is what makes
the algorithm binding of section 7.4 mandatory rather than optional. What remains open under B is
narrower: the exact `Poseidon-BN254` parameterization, which is not pinned by this document and MUST
be pinned before any record is issued under it, and the cost consequences already tabulated in
`docs/decisions.md`.

**The ten engineering decisions were ruled on 2026-07-28** and this document is written on those
rulings rather than on a recommendation. Eight confirmed what it already said; two changed it.

| Decision | Ruling | Where it lands here |
|---|---|---|
| **D3** wire format | JSON for v1; dCBOR permitted as a transport and normatively forbidden as the digest rule | 13.2 |
| **D4** salt strategy | **D4b**, one independently random CSPRNG salt per leaf. **Changed this document**: the KDF, the master salt and the record identifier in a preimage are gone | 7, 7.1, 7.2, 7.3, 8, 10.2, 11.2 |
| **D5** leaf ordering | D5a, by `encodePath` bytes, with the residual gap leak stated | 9, 9.3, 10.1, 2.2 |
| **D6** absence proofs | Out of scope for v1, capability deliberately preserved | 2.2, 9.3 |
| **D7** unknown paths | D7a, fail closed, with the type map stated as a versioned issuer-extensible artifact | 4.2, 4.3 |
| **D8** inside the root | Identity in, routing out, plus a mandatory corpus vector that fails a verifier trusting an outside field | 11.2, 11.3 |
| **D9** big blobs | Inline for v1; **extended this document** with a content-addressed binding defined now and selected by no v1 profile, plus a pinned canonical base64 form | 6.1, 6.3, 6.5 |
| **D11** detached signature | None in v1, with the constraints on any future one stated normatively now | 2.2 |
| **D12** normalization | D12a, NFC pinned at Unicode 15.1, with an end-to-end corpus vector | 6.1 |
| **D13** clinical validation | D13a at the protocol layer, plus a normative prohibition on claiming clinical facts from root validity | 2.3 |

**One further question is open and was identified after these rulings, while building the vector
D12 required: whether the type-map lookup matches over an NFC-normalized key or over the bytes as
received.** Section 6.1 pins NFC for hashing and section 4.2 requires an uncovered path to fail
closed; neither says which form the lookup that precedes hashing compares. Both reference
implementations currently match raw, so a decomposed key is refused by the fail-closed rule while
its composed twin commits, and the two render identically. That is decision D14 in
`docs/decisions.md` and this document does not settle it.

**All of them, with their alternatives, their reasoning and the constraints they were ruled under,
are in [`docs/decisions.md`](../decisions.md).** A decision that looks settled here and still reads
as open there is a defect in this documentation set, not a nuance; the two files move together.

---

## 16. Citations

### Standards

| Spec | Sections used |
|---|---|
| RFC 2119 / RFC 8174 (BCP 14) | requirement keywords |
| RFC 9162 (Certificate Transparency v2) | 2.1.1 tree hash, 2.1.3 inclusion proof, 2.1.3.2 verification |
| RFC 8785 (JCS) | 3.1 no normalization, 3.2.2.3 number serialization, 3.2.3 UTF-16 key sort |
| RFC 8949 (CBOR, STD 94) | 4.2 deterministic encoding, 4.2.2 what the protocol must still pin |
| RFC 4648 (Base16, Base32, Base64) | 3.5 non-canonical trailing bits, 4 the pinned base64 alphabet and padding, 5 the URL-safe alphabet this document rejects |
| `draft-mcnally-deterministic-cbor-17` | 2.5 numeric reduction |
| W3C RDF Dataset Canonicalization RDFC-1.0 (Rec, 21 May 2024) | 1 graph isomorphism, 4.4.3 DoS defence, 7.1 dataset poisoning |
| FHIR R4 Data Types | `decimal` precision SHALL - <https://hl7.org/fhir/R4/datatypes.html> |
| Unicode Standard Annex #15 | Normalization Form C |
| ECMA-262 | 7.1.12.1 `Number::toString`, as incorporated by RFC 8785 |

### Reference schemata

Cited by path only and never copied into this repository, per repository policy:
`references/schemata/src/sg/gov/moh`, which is excluded by `.gitignore` and lives outside this
repository by design. That checkout was read at Open-Attestation/schemata commit
`09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`.

### dogtag

The `dogtag-mono-repo` working tree, read 2026-07-28.
File and line references are given inline throughout section 14 and elsewhere.

### Evidence strength

- **Reproduced during the writing of this document:** the JCS number collisions, the UTF-16 versus
  UTF-8 key ordering, and the NFC/NFD distinction, all in section 13.1, on Node v22.21.0. The
  script is included so a reader can check rather than trust.
- **Measured, and it corrected this document:** the `leafCount` case in section 11.1. An 8-leaf tree
  was built per section 9.1, and the internal node `MTH(L[0:4])` presented as the leaf at index 0
  with a forged tree size of 2 was confirmed to verify against the genuine root under RFC 9162
  section 2.1.3.2, on Node v22.21.0. It came out of the conformance corpus work and it removed a
  claimed defence that did not exist. Section 9.3 and `docs/conformance-corpus.md` class 9 carry the
  same correction.
- **Ruled rather than derived:** the ten decisions listed in section 15, ruled 2026-07-28 with their
  reasoning recorded in `docs/decisions.md` part 2. Where this document now states one of them
  normatively, the authority is that ruling.
- **Inference made in this document rather than carried from a ruling:** pinning the `BLOB_REF` blob
  digest to SHA-256 independently of `hashAlg`, labelled as such at section 6.5 with its reasoning
  and the consequence it accepts.
- **Confirmed by reading dogtag source at the cited file and line:** every claim in section 14,
  including the test-vector counts in 14.3, which were read out of the file rather than quoted.
- **Carried from the research reports and not independently re-run here:** the performance
  measurements in the Poseidon row of 14.2, the byte sizes in section 10.3, the five-language
  agreement result, and the Swift `JSONSerialization` behaviour in section 6.4.
- **Inference, labelled as such where it appears:** the prefix-guard argument in section 11.2.
