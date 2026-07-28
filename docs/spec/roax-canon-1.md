# ROAX-CANON/1 - canonical serialization, commitment and selective disclosure

**Status:** draft for review. Not frozen. No library code exists yet.
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
7. [Salt derivation](#7-salt-derivation)
8. [Leaf construction](#8-leaf-construction)
9. [Tree construction](#9-tree-construction)
10. [Selective disclosure](#10-selective-disclosure)
11. [The envelope](#11-the-envelope)
12. [Versioning](#12-versioning)
13. [Why not JCS, dCBOR or RDFC-1.0](#13-why-not-jcs-dcbor-or-rdfc-10)
14. [Reconciliation with dogtag](#14-reconciliation-with-dogtag)
15. [Open decisions](#15-open-decisions)
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
  re-derived from the anchoring chain, not read from the document. An offline-verifiable signature
  is a separate decision; if added it MUST sign the root and MUST NOT become an alternative to
  anchoring. See decision D11 in `docs/decisions.md`.
- **No anchoring registry design.** What the on-chain registry looks like - one root per record
  versus batched roots, and revocation semantics - is not specified here and is not settled.
  A further smart-contract round is expected, so no contract set is treated as permanent by this
  document. **This document does place one requirement on that design, and hands it forward rather
  than pretending it is closed here: the registry MUST record the pair `(root, hashAlg)`, and a
  verifier MUST take `hashAlg` from the registry rather than from the envelope.** Section 7.4 shows
  why that is the only one of the three algorithm bindings that actually works.
- **The type map does not exist yet.** Section 4 establishes that it is REQUIRED and that the
  design is unsafe without it. Building it is mechanical but it is real work on the critical path,
  and it is not done. This is the single largest gap between this specification and a working
  library.
- **No absence proofs.** Proving "this record asserts no allergy" is possible under the leaf
  ordering chosen in section 9, but it is a clinical claim with liability attached and is deferred
  as a product question (decision D6).
- **No confidentiality.** The full copy of a record is plaintext. This document provides selective
  disclosure, which is a different property: it lets a holder reveal a subset without invalidating
  the root. It does not encrypt anything.
- **No leaf-count privacy.** A verifier of a disclosed copy learns how many leaves the record has.
  For a record whose profile is known, the leaf count is weak but nonzero information about record
  shape. This is inherent to the construction and is not mitigated.
- **Kotlin/JVM is unverified.** Every other target language has a confirmed mechanism for
  preserving JSON numeric literals (section 6.4). Kotlin does not, in the sense that nobody has yet
  checked. Treat the Kotlin row of that table as an open engineering question, not as a solved one.

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
        |  (C) LEAF HASH          (per-leaf derived salt, sections 7 and 8)
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
  if node is a map and is empty:        emit (path, EMPTY_OBJECT, -)
  if node is a map and is non-empty:    for each key k: flatten(node[k], path ‖ KEY(k))
  if node is an array and is empty:     emit (path, EMPTY_ARRAY, -)
  if node is an array and is non-empty: for each index i: flatten(node[i], path ‖ INDEX(i))
  otherwise:                            emit (path, typeTag(path, node), node)
```

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
single leaf (`crates/dogtag-standard-rs/src/flatten.rs:96-115` in the dogtag monorepo - an empty
array and an empty object both yield `TypedScalar::Null`, which is also what a genuine null yields).
Section 14.2 explains why ROAX does not inherit that.

**A record that contributes zero leaves of its own MUST be rejected at issuance rather than
anchored.** The rejection is on the record's own contribution, because the union above always
carries the reserved leaves, so the tree itself is never empty: its floor is 5 leaves, being the
four always-emitted reserved leaves plus at least one from the record. Section 11.2 gives the
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

- The type map is a **data file**, versioned with this specification and part of the conformance
  corpus (see `docs/conformance-corpus.md`, class 11).
- It is keyed by **(path pattern, observed JSON kind)**, not by path alone. Polymorphic fields are
  already present in the reference records: in the shipped vaccination sample,
  `fhirBundle.entry[0].identifier[0].type` is the string `"PPN"` while `identifier[1].type` is the
  object `{ text: "NRIC" }`. A map keyed by path alone cannot express that.
- It MUST cover the **union of three distinct schema scopes**, not one. The PDT and recovery
  healthcerts reference the lite FHIR schema for `fhirBundle`; the vaccination healthcert
  references neither and defines its `fhirBundle` inline against its own seven definitions. The
  lite schema omits `Immunization` and `ImmunizationRecommendation` entirely while the full schema
  has them. See `docs/profiles/` for the per-family detail.
- **Unknown paths MUST fail closed.** A path the type map does not cover is an error, not a guess.
  Defaulting to STRING or to the observed JSON kind means two libraries with different type-map
  versions produce different roots silently, which is precisely the failure this project exists to
  avoid. This is decision D7 and the recommended answer is written into this specification.

### 4.3 Status

**The type map has not been built.** Section 2.2 records this as the largest gap.
What has been established is that it is necessary (this section), tractable (the lite FHIR schema
is closed - every one of its 66 `additionalProperties` occurrences is `false`), and roughly sized
(85 lite definitions, 50 `Extension.value[x]` variants, the vaccination healthcert's own seven
definitions, plus whatever slice of the 680-definition full schema is in scope).

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
identical in five languages. It is decision D5.

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

Tags 6 and 7 give empty containers distinct identities. See section 14.2.

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

The alternative - preserve the exact scalar sequence, per the audit's preferred reading - and its
consequence are stated as decision D12 in `docs/decisions.md`.

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
same grammar `schemas/envelope-1.0.json` pins for a DECIMAL value:

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

### 6.3 Bytes

`BYTES` carries the bytes themselves.
Where a record embeds base64 (`logo`, `attachments[].data`), the profile document states whether
the field is bound as `STRING` over the base64 text or as `BYTES` over the decoded content.
Binding it as `STRING` is RECOMMENDED for v1 because it requires no base64 canonicalization rule;
base64 has multiple valid encodings of the same bytes (padding and line-wrap variants), and a
`BYTES` binding would need to pin one. See decision D9 for the related size question.

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

---

## 7. Salt derivation

```
salt(path) = HMAC-SHA-256(masterSalt, saltPreimage(path))[0..16]

saltPreimage(path) =
      u32be(len(DOMAIN))   ‖ DOMAIN       // DOMAIN = ASCII "ROAX-CANON/1/" ‖ hashAlg
    ‖ u32be(len(LABEL))    ‖ LABEL        // LABEL  = ASCII "/salt"
    ‖ u32be(len(RID))      ‖ RID          // RID    = utf8(recordId), from the envelope (section 11)
    ‖ u32be(len(P))        ‖ P            // P      = encodePath(path)
```

`DOMAIN` is **algorithm-qualified**: it is the ASCII string `ROAX-CANON/1/` followed by the
envelope's `hashAlg` value, so for v1's defined algorithm it is `ROAX-CANON/1/SHA-256`.
Section 7.4 states why the algorithm identifier is bound here and not merely declared.

**Every component is length-prefixed, exactly as in section 8, and for the same reason.**
This is spelled out as a byte layout rather than as a concatenation expression because it is a place
two implementations could otherwise diverge: without the prefixes, a future `ROAX-CANON/2` whose
domain string is a different length could overlap preimages with v1 under an adversarially chosen
`recordId`, and an implementer would have to infer the framing from section 8's style rather than
read it here.

- `masterSalt` MUST be 32 bytes freshly generated from a CSPRNG, **per record**.
- It MUST NOT be derived from record content, from a record identifier, from the issuer's signing
  key, or from any other issuer-stable secret.
- It is held by the issuer and then the holder. **It MUST NEVER appear in any envelope**, full or
  disclosed. What an envelope carries is the individual `salt(path)` values, per section 7.3.

There is exactly **one** salt-derivation preimage builder in a conforming implementation.

> **Salts are generated by the protocol, not supplied by the issuing institution.**
> Both `masterSalt` and every `salt(path)` are produced at issuance by the issuing library itself,
> from a CSPRNG. They are not clinical data, not a record field, and not something a hospital, a
> laboratory or any other issuer collects, stores in its own systems, or adds to an existing dataset.
> Section 7.3 requires a full copy to carry every leaf's salt, and that is purely a matter of
> envelope format: it imposes **no new data-collection burden on any issuer**.
> This is stated because "include the random numbers in the dataset" is an easy and expensive
> misreading, and an implementer who takes it as an integration requirement would levy real work on
> issuing institutions for a value the library computes on its own.

**`recordId` is not circular, though it looks it.** It is an input to every salt (above) and is also
itself committed as a reserved leaf at `roax.recordId` (section 11.2). There is no cycle: the
preimage consumes it as a plain UTF-8 string taken from the envelope, never a leaf hash or a salt.
So `salt(roax.recordId)` is computed the same way as every other salt, and the leaf at
`roax.recordId` is then built from it normally.
Implement it in that order and nothing recurses.

`hashAlg` raises no such question, because section 7.4 removes it from the leaf set: it enters the
domain string only.

### 7.1 Why the record identifier is in the preimage

This is adopted from dogtag and it is the most substantive thing this specification takes from it
that the source research reports did not carry over.

dogtag binds a per-record identifier (`dogTagId`) into every KDF preimage, and states the reason
plainly: "Binding to `dogTagId` is what keeps one wallet's two tags mutually unlinkable"
(dogtag `AGENTS.md:1744-1745`; the shared builder is `kdf::kdf`, documented at
`crates/dogtag-standard-rs/src/profile_tree.rs:14-24` as
`domain ‖ dogTagId[32B BE] ‖ u64be(len(extra)) ‖ extra ‖ seed`).

Without that binding, unlinkability rests entirely on `masterSalt` freshness - a single MUST
carrying the whole property. Reusing `masterSalt` across two records for the same patient makes
every shared path with a shared value produce the *same* leaf hash in both, so a verifier who sees
both disclosures can link them.

**State the benefit precisely.** Binding `recordId` is **defense in depth, not a fix.**
It converts "one MUST protects everything" into "two independent things must both go wrong."
If `recordId` is content-derived, or reused across a reissuance of the same record, the linkage
returns. It does not make `masterSalt` reuse safe, and the MUST above remains load-bearing.
The conformance corpus catches a violating implementation (`docs/conformance-corpus.md`, class 12).

### 7.2 Why derived rather than stored

dogtag stores 16 random bytes per leaf inside the document.
For an 87-leaf record that is 1,392 bytes of salt, and far more for a large FHIR bundle.
Derivation replaces that with one 32-byte secret.

**Scope that saving correctly: it is a saving in what the issuer stores, not in what an envelope
ships.** Section 7.3 requires a full copy to carry every leaf's salt under either answer to
decision D4, so a full copy is the same size either way. What derivation avoids is the issuer
holding, backing up and reissuing from 16 bytes per leaf per record indefinitely. A disclosed copy
is small under both, because it carries only the salts of the leaves it reveals.

#### What the `salts` array actually costs, in bytes

**Path bytes dominate, not the 16-byte salt.** Each entry repeats the leaf's whole structured path,
so a reader who budgets 16 bytes per leaf will be wrong by roughly an order of magnitude and will
optimize the wrong thing.

Worked from `fhirBundle.entry[0].identifier[0].type`, a real path in the vaccination sample
(section 4.2), serialized as the `salts` entry `schemas/envelope-1.0.json` defines:

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

At about 153 bytes an entry, the 92-leaf vaccination envelope of section 11.1 gains roughly
**13.8 KB**. That is comparable to the same record's own 14,314-byte embedded logo, which
`docs/decisions.md` D9 tabulates to the byte, and it is the largest single format cost this
document imposes.

Two things that cost is **not**. It is a **full-copy-only** cost: a disclosed copy carries one salt
per revealed leaf, so the 583-versus-2,720-byte figures in section 10.3 are untouched. And it is
not a cost derivation can avoid, because it lands identically under D4a and D4b.

**The obvious smaller encoding is rejected on purpose.** A positional array in `encodePath` order
with the segments dropped would cost 35 bytes an entry instead of 153. It would also make
salt-to-leaf pairing depend on each implementation reproducing the section 9 sort identically before
it can even read the salts, which is precisely the cross-implementation divergence this project
exists to prevent. Explicit segments make the pairing self-describing and independent of the sort,
and that is worth the bytes.

Disclosing leaf A means disclosing `salt(A)` only. HMAC is one-way, so a verifier holding `salt(A)`
cannot derive `salt(B)` and therefore cannot brute-force any withheld low-entropy field - which
matters because a birth date or a gender has only a few thousand or a few possible values.

Nothing here is reduced into a prime field, so this does **not** inherit dogtag's modular-bias
hazard (`AGENTS.md:1740-1741`: "Reduce the full 64-byte digest, never a 32-byte prefix: a bare
32-byte hash mod r is measurably biased"). Truncating a uniform 32-byte HMAC output to 16 bytes is
uniform.

This is decision D4, and the alternative - dogtag's stored per-leaf salt - is genuinely defensible.
See `docs/decisions.md`.

### 7.3 Which copy carries which salts

Three rules, and the third is absolute:

1. **A full copy MUST carry the salt of every leaf**, each 16 bytes in lowercase hex, addressed by
   its structured path. "Every leaf" means the union of section 3.3, so the reserved `roax.*` leaves
   of section 11.2 are included and the count equals `leafCount`.
2. **A disclosed copy MUST carry the salt of every leaf it reveals and the salt of no other leaf.**
   See section 10.1 for why the second half of that sentence is the load-bearing one.
3. **`masterSalt` MUST NEVER appear in any envelope**, full or disclosed.

`schemas/envelope-1.0.json` enforces all three structurally. The `salts` array is required alongside
`record` and forbidden alongside `disclosure`, and there is no `masterSalt` field to populate.

Without rule 1 a full copy is not verifiable at all, which would make the definition in section 1
false. `leafHash` (section 8) needs `salt(path)`, and the record body carries no salts, so a
verifier holding a full copy would have no route to any leaf hash and therefore none to the root.

**Carrying every salt in a full copy discloses nothing extra.** A full copy already reveals every
value at every path. A salt is only useful for confirming a value you do not already have, and a
full copy withholds nothing, so there is nothing left for the salts to protect. The property salts
exist for is defeating a dictionary search against a **withheld** low-entropy leaf (sections 7.2
and 10.1), and that property belongs entirely to the disclosed copy.

#### Why the carrier is the per-leaf salt and not `masterSalt`

**This settles nothing about decision D4, and it is written this way precisely so that it cannot.**

Decision D4 is OPEN. Its alternative D4b is dogtag's stored per-leaf random salt, under which there
is no `masterSalt` at all. An envelope format that *required* `masterSalt` would be unimplementable
under D4b, so choosing it would have silently foreclosed an open decision from inside a schema,
which is the exact failure `docs/decisions.md` exists to prevent.

The per-leaf salt is the agnostic carrier:

| Under | How the salts come to exist | What the envelope carries |
|---|---|---|
| **D4a** (written into this specification, section 7) | HMAC-derived from a per-record `masterSalt` | the derived `salt(path)` of every leaf |
| **D4b** (dogtag's stored salts) | independently generated from a CSPRNG per leaf | the stored salt of every leaf |

The envelope bytes are identical either way, and a verifier cannot tell which produced them, because
verification never re-derives a salt: it reads the salt and recomputes `leafHash`.
So the format above is not a ruling on D4 and MUST NOT be read as one.

**The per-record freshness MUST in section 7 is unaffected and remains load-bearing.**
Under section 7.1 reuse across two records for the same patient makes every shared path with a
shared value produce the same leaf hash in both, so a verifier who sees both disclosures links them.
Nothing here changes that, and rule 3 keeps the reuse hazard confined to the issuer: because
`masterSalt` never leaves the issuer, no envelope holder can derive a salt the envelope did not
already give them.

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

**H1. `hashAlg` is a length-prefixed component of `DOMAIN`**, so it enters every salt preimage (this
section) and every leaf preimage (section 8). **Stated honestly, this buys almost nothing
cryptographically**, for the same reason the leaf did not: the attacker computes both records under
the same domain string. What it does buy is real but narrower. It removes cross-algorithm root
ambiguity by construction, so the same content under two algorithms cannot collide on a root by
accident, and it makes the claim in `schemas/envelope-1.0.json` true rather than aspirational.

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
> this specification pins that parameterization. The byte-level preimages in sections 7 and 8 are
> stated over byte strings and do not transfer to a prime-field permutation unmodified.

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

**Salt derivation is the deliberate exception and stays `HMAC-SHA-256` under every `hashAlg`**
(section 7). A salt is a secret *input*, generated once at issuance and never recomputed by a
verifier or inside a proof circuit, so it gains nothing from being ZK-friendly and would pay the
full cost of being so. dogtag is the precedent and reached the same split: its tree is Poseidon over
BN254 while its salts come from a BLAKE-512 KDF (`crates/dogtag-standard-rs/src/profile_tree.rs`
and `poseidon.rs`). Keeping the salt KDF fixed also means a record's salts do not change meaning
when the tree algorithm does.

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
11.2, so `L` is never empty and its length is never below 5. The branch is kept rather than deleted
because a total function is easier to port than one with an undefined case, and because an
implementation that reaches it has a defect worth failing loudly on rather than an input worth
hashing.

### 9.2 Inclusion proofs

RFC 9162 sections 2.1.3 and 2.1.3.2, unchanged, again over already-hashed leaves.
A proof is verified against `(leaf hash, leaf index, tree size, audit path, root)`.

### 9.3 Why RFC 9162 rather than a bespoke tree

- It is **position-bound**. There is no commutative fold, so there is no hazard of the kind dogtag
  demonstrates in its own test suite, where an *internal node* folds to the root just as happily as
  a leaf under a commutative sorted tree with odd-promotion
  (`crates/dogtag-standard-rs/src/merkle.rs:86-99` documents the hazard on `process_proof`; the
  test at `merkle.rs:196-229` demonstrates the forgery). dogtag closes it with a Poseidon5-vs-
  Poseidon3 arity/domain split inside `verify_inclusion`. ROAX avoids it structurally instead.
- Its shape is uniquely determined by the number of leaves (RFC 9162 section 2.1.1), so a verifier
  reconstructs tree shape from `(index, size)` alone. dogtag reached the same requirement from the
  other direction and had to make promotion an **explicit** proof step to get it, because the
  legacy bare-sibling list represented a promote by omission and the verifier could not recover the
  depth (`merkle.rs:57-64`). This is convergent evidence that the requirement is real, not a
  departure from dogtag.
- It has no duplicate-promotion second-preimage problem, and its non-power-of-two handling is
  specified rather than invented.

**Sorting by path rather than by leaf hash** additionally makes the tree shape independent of the
salt values, and makes absence proofs possible in principle: showing the two adjacent leaves in
canonical order proves no leaf exists between them. dogtag sorts by hash
(`merkle.rs:24-26`). This is decision D5; the absence-proof consequence is decision D6.

---

## 10. Selective disclosure

A disclosed copy carries, for each revealed leaf: its path as **structured segments**, its leaf
index, its type tag, its value, its `salt(path)`, and its RFC 9162 audit path.
It MAY additionally carry the display path, which is display only and is never an input to anything
the verifier computes (section 5.2).

> **Normative:** a disclosed copy MUST carry the salt of every leaf it reveals and **MUST NOT carry
> the salt of any withheld leaf**. It MUST NOT carry `masterSalt` (section 7.3).
> Section 10.1 gives the attack this prevents.

A verifier:

1. re-encodes the path from the structured segments, recomputes the encoded value, and recomputes
   `leafHash` per section 8 - it MUST NOT trust a caller-supplied leaf hash;
2. verifies the audit path against `root` per RFC 9162 section 2.1.3.2;
3. checks `root` against the anchoring layer.

Step 1 is not optional and it is where dogtag's most expensive scar lives.
dogtag documents `process_proof` as "a fold **primitive**, NOT a membership check. It trusts the
`leaf_hash` you hand it, so on its own it proves nothing" (`merkle.rs:86-91`), and its
`check_integrity` rebuilds the whole tree rather than trusting a fold
(`crates/dogtag-standard-rs/src/verify.rs:263-264`: "rebuild the WHOLE tree (never trust
processProof alone - C1)").

### 10.1 What a verifier learns, and what it does not

**Learns:** each disclosed path, value and salt; the total leaf count; the disclosed indices; and
the sibling hashes on each audit path.

**Does not learn:** any other path, value or salt - and therefore nothing brute-forceable about
withheld low-entropy fields such as name, national identifier, passport number, birth date or
gender, all of which appear in the reference records.

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
`schemas/envelope-1.0.json` the `salts` array is forbidden alongside `disclosure`, which makes a
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

The per-profile lists live in `docs/profiles/`. At minimum every profile MUST include the reserved
paths of section 11.2.

### 10.3 Disclosure size

Selective disclosure here costs `O(k log n)`, against `O(n)` for the redaction style
OpenAttestation and dogtag use, which carries one 32-byte hash per **withheld** field.
For an 87-leaf record disclosing 2 fields, that was measured at ~583 bytes versus 2,720 bytes, a
4.7x reduction (the canonicalization research, sections 2.3 and 6.3). The gap widens roughly as
`n / (k log n)`.

---

## 11. The envelope

The envelope is a strawman for review. It is the least settled part of this document.

JSON Schema: [`schemas/envelope-1.0.json`](../../schemas/envelope-1.0.json).

### 11.1 Shape

```jsonc
{
  "canon": "ROAX-CANON/1",          // canonicalization version - BOUND INTO THE ROOT
  "hashAlg": "SHA-256",             // hash algorithm - in the domain string AND inside the root
  "recordType": "sg.gov.moh.vaccination-healthcert",
  "schemaVersion": "1.0",
  "recordId": "urn:uuid:...",       // in every salt preimage (section 7.1)

  "root": "<64 hex chars>",
  "leafCount": 92,                  // the UNION - record leaves plus reserved leaves (section 3.3)

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

There is no `masterSalt` field, and adding one would be a violation: section 7.3 rule 3 keeps it out
of every envelope.

The `anchor` values above are illustrative placeholders.
No chain id, registry address or contract set is treated as permanent by this document.

`leafCount` counts the **union** defined in section 3.3, so it includes the reserved leaves of
section 11.2 and not only the leaves the record itself produced. The value shown is the 87-leaf
vaccination record of section 10.3 plus its five reserved leaves, `issuer.keyId` being present
here. An implementation that counts the record alone reports a `leafCount` that does not match its
own root, and every inclusion proof it issues is bound to the wrong tree size.

> **Normative:** `leafCount` is neither a domain component nor a leaf, deliberately. A leaf stating
> the leaf count would change the leaf count, so there is no fixed point to commit.
>
> It is nonetheless checked, and the check differs by copy kind.
> In a **disclosed copy** it is already bound by the RFC 9162 proof, because tree shape is uniquely
> determined by the number of leaves (section 9.3), so a wrong `leafCount` makes the audit path fail.
> In a **full copy** the verifier derives the leaf count itself while rebuilding the tree, and
> **a derived count that disagrees with the `leafCount` field MUST be a rejection**, not a warning
> and not a silent preference for either value.

That last MUST is stated because the field is required in every envelope while the full-copy path
recomputes the same quantity, and a specification that requires a field without saying what a
disagreement means is inviting two implementations to resolve it differently.

**Exactly one of `record` and `disclosure` MUST be present.**
A verifier that sees both MUST reject. The JSON Schema encodes this as two `allOf` clauses, because
it is the security-relevant invariant and is easy to get wrong when written informally.
`salts` follows `record`: it is REQUIRED in a full copy and FORBIDDEN in a disclosed one
(section 7.3), and its length equals `leafCount` because it carries one entry per leaf of the union.

### 11.2 Reserved leaves, and the prefix rule

The envelope fields that say what a record **is** are committed **inside** the root as ordinary
leaves under the reserved first segment `roax`.
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

**Three of the five are mandatory by arithmetic, not by policy.** `recordType` and `schemaVersion`
together select the type map, and `recordId` is in every salt preimage (section 7), so a verifier
that does not have all three cannot run the verification procedure at all. Withholding one does not
produce a weaker proof; it produces no proof. Only `roax.issuer.id` is a policy choice, and it is
included because section 10.2 requires a disclosed copy to say who issued it.

**`roax.issuer.keyId` is committed but OPTIONAL to disclose**, which is the one place this set
departs from the pattern. Requiring its disclosure would break key rotation on already-anchored
records: the key that signed an issuance is fixed in the root forever, so a holder whose issuer has
since rotated keys would be forced to reveal a retired key identifier to make an otherwise valid
record verify. That is the same trap section 11.3 records for mutable routing fields, arriving from
a different direction.

`issuer.keyId` is also the one reserved leaf whose *presence* varies. **An absent `issuer.keyId`
emits no leaf**; it MUST NOT be emitted as a NULL leaf or as an empty string, because those are
three different roots and only one of them can be right. The reserved leaf count is therefore 4 or 5.

**Two leaves that an earlier draft committed have been removed, and the reasons differ.**
`roax.hashAlg` was removed because a leaf cannot bind the algorithm it is hashed under at all
(section 7.4). `roax.canon` was removed because it is redundant rather than wrong: `canon` is
already inside `DOMAIN` in every leaf and every salt (sections 7 and 8), so a v2 library cannot be
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
different string from the one that actually gets committed. That the two differ is easy to
demonstrate: U+212A KELVIN SIGN is the three bytes `e2 84 aa` as received and normalizes under NFC
to ASCII `K`, the single byte `0x4b` (verified on Node v22.21.0). The rule is the general one -
**check the bytes you commit, not the bytes you received** - and it applies here because this guard
and the hashing path must agree about what the key is.

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

The recommended split above puts identity inside and routing outside. This is decision D8.

---

## 12. Versioning

Four axes, deliberately not collapsed:

| Axis | Field | Changes when | Inside the root? |
|---|---|---|---|
| Canonicalization | `canon` | the hashing rules change | **Yes**, via `DOMAIN` in every leaf and every salt |
| Hash algorithm | `hashAlg` | a record selects a different hash family | **Via `DOMAIN` only.** Not a leaf: a leaf cannot bind the algorithm it is hashed under. Authority comes from the anchoring registry (section 7.4) |
| Record schema | `recordType` + `schemaVersion` | a profile publishes a new version | **Yes**, as ordinary reserved leaves |
| Envelope / routing | `anchor` | deployment changes | **No** |

Because `DOMAIN` is folded into every leaf hash (section 8) and every salt (section 7), the
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

### 12.1 Version identifiers are opaque

> **Normative:** the protocol never parses, orders or range-compares a version identifier.
> A version is matched for equality or not at all.

`schemaVersion` is an **opaque, profile-defined label**. It is validated by exact match against the
profile registry (`docs/profiles/`), never by shape, and `schemas/envelope-1.0.json` and
`schemas/type-map-1.0.json` therefore constrain it to a non-empty string and nothing more.

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

And one internal reason, which is the decisive one: **nothing in this protocol compares versions.**
The only structural use of `schemaVersion` is exact match, as half the type-map lookup key
(section 4.2). A constraint that no code path needs is a constraint that can only reject valid
input.

**The dividing line, stated so it is not re-litigated per field.** A version identifier this project
**owns** may carry a shape; a version identifier defined **elsewhere** is opaque.

| Field | Owner | Constraint |
|---|---|---|
| `corpusVersion` (`schemas/conformance-corpus-1.0.json`) | ROAX | three-part semver, legitimately |
| `typeMapVersion` (`schemas/type-map-1.0.json`) | ROAX | three-part semver, legitimately |
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
  `schemas/envelope-1.0.json` constrains `recordType` to a form rather than to a closed list: the
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
the *envelope* in dCBOR - not to make dCBOR the digest rule. That is decision D3.

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
| Record identifier in the KDF preimage | `AGENTS.md:1744-1745`; builder at `profile_tree.rs:14-24` | **Adopted**, section 7.1 | Neither research report carried this over. Defense in depth for unlinkability - see the precise limit in 7.1. |
| One salt-derivation preimage builder | `AGENTS.md:1747-1751`: "A second preimage builder is the drift" | **Adopted**, section 7 | dogtag's consent key stayed wallet-level for a whole release because it had its own hand-rolled preimage. |
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
| Stored 16-byte salt per leaf inside the document | `wrap.rs` | **DEPARTED**, derived salts, section 7 | Size. But this is decision D4 and dogtag's choice is defensible. |
| Single hard-coded profile validator | `schema.rs:1-9`, `:159` | **DEPARTED**, per-family profiles | See section 14.1. |
| Four-language agreement via two implementations plus FFI | Rust plus TypeScript are independent; Swift and Kotlin call Rust through UniFFI 0.28 (`Cargo.toml:33`; the generated Swift binding is `apps/ios/DogTag/dogtag_standard.swift`). There is no Swift or Kotlin Poseidon in the repository | **Structural lesson, decision D / D10 is OPEN** | See 14.3. |

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

This is decision D / D10 and it is OPEN.

---

## 15. Open decisions

This specification is written on the **recommended** answer to every open decision, so that it is
concrete and readable. That does not mean the decisions are made.

Three of the four that belong to the project owner have not been ruled on:

- **A** - whether roax-lib needs EU recognition, which would mandate SD-JWT VC and ISO mdoc export
  profiles.
- **C** - what happens to the Singapore healthcerts already issued under OpenAttestation.
- **D** - five independent libraries versus a shared core over a binding layer.

**B is ruled and is no longer open in the "which one" sense.** ZK-friendly and non-ZK hashes are
both first-class and selectable per record, permanently, via `hashAlg`. That ruling is what makes
the algorithm binding of section 7.4 mandatory rather than optional. What remains open under B is
narrower: the exact `Poseidon-BN254` parameterization, which is not pinned by this document and MUST
be pinned before any record is issued under it, and the cost consequences already tabulated in
`docs/decisions.md`.

Ten more are recorded alongside them: D3 wire format, D4 salt strategy, D5 leaf ordering,
D6 absence proofs, D7 unknown paths, D8 what goes inside the root, D9 big blobs, D11 detached
signature, D12 normalization, D13 clinical validation level.

**All of them, with alternatives and consequences, are in
[`docs/decisions.md`](../decisions.md).** Nothing in this document should be read as settling them.

---

## 16. Citations

### Standards

| Spec | Sections used |
|---|---|
| RFC 2119 / RFC 8174 (BCP 14) | requirement keywords |
| RFC 9162 (Certificate Transparency v2) | 2.1.1 tree hash, 2.1.3 inclusion proof, 2.1.3.2 verification |
| RFC 8785 (JCS) | 3.1 no normalization, 3.2.2.3 number serialization, 3.2.3 UTF-16 key sort |
| RFC 8949 (CBOR, STD 94) | 4.2 deterministic encoding, 4.2.2 what the protocol must still pin |
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
- **Confirmed by reading dogtag source at the cited file and line:** every claim in section 14,
  including the test-vector counts in 14.3, which were read out of the file rather than quoted.
- **Carried from the research reports and not independently re-run here:** the performance
  measurements in the Poseidon row of 14.2, the byte sizes in section 10.3, the five-language
  agreement result, and the Swift `JSONSerialization` behaviour in section 6.4.
- **Inference, labelled as such where it appears:** the prefix-guard argument in section 11.2.
