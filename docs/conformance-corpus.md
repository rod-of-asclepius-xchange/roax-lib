# The ROAX conformance corpus

**Status:** definition. The corpus file itself does not exist yet.
**Schema:** [`schemas/conformance-corpus-1.0.json`](../schemas/conformance-corpus-1.0.json)

---

## 1. Why this is normative and not decoration

Two independent reasons, and either alone would be sufficient.

**The engineering reason.** dogtag achieved four-language agreement with **two** implementations,
not four: Rust and TypeScript are independent, and Swift and Kotlin call the Rust crate through
UniFFI. There is no Swift Poseidon and no Kotlin Poseidon anywhere in that repository. Agreement
between the two real implementations is enforced by a shared JSON vector file,
`packages/dogtag-standard-ts/testvectors.json`, which contains 15 leaf vectors, 5 `bytesToField`
vectors, 11 Merkle-root vectors and 110 inclusion vectors.

ROAX additionally wants Go, and Go over UniFFI is awkward - UniFFI has no first-class Go backend.
So if ROAX ships five genuinely independent libraries, **the corpus stops being a safety net and
becomes the entire enforcement mechanism.** (Whether it does ship five is decision D, and it is
open; but the corpus has to be built as though it will, because retrofitting it after divergence has
shipped is far worse.)

**The review reason.** Stated in the standards research as a disqualifier rather than a nice-to-have:
"we invented our own canonicalization without cross-language test vectors" fails healthcare security
review. ROAX is inventing a canonical form. That is defensible - sections 13.1 through 13.3 of the
specification give the reasons - but only if the invention is accompanied by hostile cross-language
vectors published before any library claims conformance.

**And dogtag supplies the warning for exactly this path.** Its TypeScript `verify` silently diverged
from the Rust one, and the divergence is *recorded rather than fixed* because it has no production
consumer (`AGENTS.md:357`, which ends "Do NOT wire it into a product surface before reconciling it
with the Rust implementation").

> An independent implementation that is not covered by the corpus **will** drift.
> There must be no "we will reconcile it later" path.

### 1.1 Precedence: the specification governs

This document and the corpus file it defines are the **executable arbiter** between two
implementations that disagree, but they are **derived from**
[`docs/spec/roax-canon-1.md`](spec/roax-canon-1.md) rather than independent of it.

**The specification is normative for meaning. Where the two diverge, the specification governs.**

A divergence is a **release-blocking corpus defect**, and the corpus build MUST report it rather
than letting an implementation pass against a vector the specification does not support.
Neither document may be changed alone: a change to a canonicalization rule lands in the same change
as the corpus vectors that assert it, in both directions.

This is stated because of what section 1 just argued. If the corpus is the entire enforcement
mechanism, an arbiter that disagrees with the specification it arbitrates is worse than no arbiter:
it certifies divergence as conformance. The same statement appears as section 1.1 of the
specification, deliberately, so that a reader arriving at either document finds it.

## 2. Release gates

These are requirements on the project, not on the file.

1. **The corpus is a single versioned artifact in this repository**, normative, versioned with the
   specification.
2. **Every language's CI runs it and fails on any mismatch.** dogtag's
   `crates/dogtag-standard-rs/tests/ffi_parity.rs` is the model: one file, both sides, byte
   identity asserted.
3. **The corpus is not considered validated until an implementation written by a different author,
   from the specification text alone, passes it unmodified.**

Gate 3 is the one that is easy to drop and it is the one that matters most. The canonicalization
research produced five implementations - Python, Rust, Go, Swift, TypeScript - that agree
byte-for-byte on all three real MOH records and on a 26-leaf adversarial corpus. That is real
evidence. But the author of that research wrote all five, and said so plainly: they do not share a
JSON parser, a number representation, a Unicode API, a map implementation or a sort implementation,
but they do share one author's reading of the specification.

**A shared misreading is exactly the failure a corpus exists to catch, and five implementations by
one author cannot catch it.** So gate 3 is a release gate, not a caveat.

## 3. Mandatory vector classes

**Sixteen classes.** A class with no vectors is a coverage gap and the corpus build MUST report it
rather than passing silently.

The count is stated because a gap check built off it is the intended use, and a stale count means
the highest-numbered class is skipped silently. `schemas/conformance-corpus-1.0.json` sets the
`classRef` maximum to 16 to match.

### Class 1 - FHIR decimals

`0.010` versus `0.01`; `1.50` versus `1.5`; `2.0` versus `2`; `-0.0`;
`0.00000000000000000001`; a 40-digit integer part; a 40-digit fraction.

Every pair above MUST produce **different** leaves, which is the point of the class.

**Exponent forms are the exception in this class, and the corpus states which way each goes so it
cannot be misread.** At a path bound to DECIMAL, under the expansion rule of specification
section 6.2:

| Vectors | Expected | Why |
|---|---|---|
| `1e2`, `1.0e2`, `100` | **All three EQUAL.** Same encoded value `100`, same leaf. | Trailing zeros of the integer part carry no precision in the output grammar and cannot. |
| `100.0` versus that trio | **DISTINCT.** Encodes `100.0`. | Trailing zeros of the fraction are significant, per FHIR R4 SHALL. |
| `1.00e1` | `10.0` | `f' = max(0, 2 - 1) = 1`. |
| `1.5e-2` | `0.015` | `f' = 1 + 2 = 3`. |
| `0e5` | `0` | Integer part normalizes to a single `0`. |

The INTEGER-versus-DECIMAL distinction is a separate matter and belongs to class 7: `1e2` bound as
DECIMAL and `100` bound as INTEGER carry different type tags and are different leaves regardless of
sharing the encoded digits `100`.

This class is the reason the whole scheme exists. See specification section 6.2.

### Class 2 - integers beyond 2^53

`9223372036854775807`, `-9223372036854775808`, and a 40-digit integer.

### Class 3 - rejection vectors

MUST error, never silently canonicalize: `1.4e+9999`; `01`; `1.`; `.5`; `+1`; `NaN`; `Infinity`; a
decimal with an empty fraction.

An implementation that accepts any of these is non-conformant even if it produces a "reasonable"
value.

`1.4e+9999` is the one of these that the input grammar admits, so it needs an explicit rule rather
than a grammar rejection. Specification section 6.2 supplies it: the expanded positional form MUST
NOT exceed 1024 total digits, and that bound is a fixed constant rather than an implementation
choice, for the reason section 13.3 gives against RDFC-1.0. This class MUST also carry a vector just
inside the bound that is accepted, so an implementation cannot pass by rejecting everything large.

### Class 4 - Unicode

- NFC versus NFD in values **and** in keys.
- A key and a value above the BMP (U+1F600).
- A fullwidth character (U+FF3A) alongside its ASCII counterpart. This is the pair that separates
  UTF-16 from UTF-8 ordering, and it is why the ordering demonstration in specification section 13.1
  works.
- An unpaired surrogate in the input - MUST be rejected.

### Class 5 - structure

Empty array, empty object and explicit null, at the same path in three sibling records, asserting
**three distinct roots**.

This is the class that would catch an implementation that inherited dogtag's collapse of all three
to a single leaf (`crates/dogtag-standard-rs/src/flatten.rs:96-115`).

### Class 6 - path

A key containing `.`, `[`, `]`; a key that is the empty string; a nested `a.b` versus a literal
`"a.b"` key; an array of one; deep nesting; an array index at `2^32 - 1`, and one at `2^32` which
MUST be rejected.

### Class 7 - type tags

`"5"` versus `5` versus `5.0`; `"true"` versus `true`.

### Class 8 - tree shape

Leaf counts **1, 2, 3, 5, 7, 8, 9, 130**, and an inclusion proof for **every** leaf at each of those
sizes.

RFC 9162's split rule - `k` is the largest power of two strictly smaller than `n` - is where a
hand-rolled tree goes wrong, and it goes wrong only at non-power-of-two sizes. A corpus that tests
only 8 and 16 proves nothing.

### Class 9 - negative proof vectors

MUST NOT verify: a valid proof against a wrong root; a proof with one sibling flipped; a proof
presenting an **internal node as a leaf**; an index out of range; a truncated audit path; an
extended audit path.

The internal-node case is dogtag's C1 hazard, which it demonstrates in its own test suite at
`crates/dogtag-standard-rs/src/merkle.rs:196-229`. RFC 9162 should reject it structurally because it
is position-bound; the corpus proves that it does rather than assuming it.

### Class 10 - the three real MOH records

Whole, with their roots and leaf counts.

Records are referenced by file, never inlined, so that no reference schema or sample is copied into
this repository. The reference material lives outside the repository by design.

### Class 11 - the schema binding itself

The type map is a data file and MUST be in the corpus, with vectors asserting that a given path
under a given map yields a given tag, and that an uncovered path fails closed.

This is the highest-risk surface in the design (specification section 4) and also the easiest to
diff, which is the one piece of good news about it.

### Class 12 - salt freshness and cross-record unlinkability

Two records sharing a path **and** a value, built with two different `masterSalt` values, MUST
produce different leaf hashes for that path.

**This is the only class that catches an implementation which derives `masterSalt` deterministically
for reproducible reissuance.** That violation is invisible to every other class in this list,
because each record verifies perfectly on its own. It is also an attractive-sounding thing to build:
"derive the master salt so reissuance reproduces the same root" reads like a feature.

Under specification section 7.1 the record identifier is also in the salt preimage, so this class
gets a second vector: two records with different `recordId` and the **same** `masterSalt` must also
produce different leaf hashes. That vector documents the defense-in-depth property precisely, and it
must not be read as making `masterSalt` reuse safe - it is not, and section 7.1 says why.

### Class 13 - reference-schema hazards

- Loading the PDT and recovery schemas together and asserting that recovery's rules still apply,
  despite recovery's `$id` pointing at PDT's path. See
  [`docs/profiles/recovery-healthcert.md`](profiles/recovery-healthcert.md) section 2.
- The vaccination flattened `entry[]` layout committing as-is, with a companion vector proving that
  the normalized layout produces a **different** root. See
  [`docs/profiles/vaccination-healthcert.md`](profiles/vaccination-healthcert.md) section 2.1.

### Class 14 - minimum-disclosure floor

For each profile, a disclosed copy omitting each declared non-redactable path in turn, each of which
MUST be rejected - plus one that includes them all and is accepted.

JSON Schema cannot express this, so it is enforced in code and can only be pinned here. See
specification section 10.2.

### Class 15 - reserved first-segment guard

The guard is on **decoded segments**, not on a rendered display path: a record-supplied path is
rejected when its **first segment** is `KEY("roax")` (specification section 11.2). The vectors are
stated as segments for that reason, and an implementation that passes this class by string-matching
`"roax."` against a display path is doing the thing specification section 5.2 forbids.

| Vector, as segments | Expected | Why |
|---|---|---|
| `[KEY("roax"), KEY("recordId")]` | **Reject** | Collides with a reserved leaf outright. |
| `[KEY("roax"), KEY("anythingElse")]` | **Reject** | First segment is reserved; the guard is on the segment prefix, not on the exact reserved paths. |
| `[KEY("roax")]` | **Reject** | The bare namespace. A display-string guard against `"roax."` misses this, which is dogtag's recorded case. |
| `[KEY("roaxX"), KEY("foo")]` | **Accept** | A different first segment. The adjacent-name squat is a hazard only for a guard comparing rendered strings. |
| `[KEY("roax.recordId")]` | **Accept** | One key that happens to contain a dot. Length-prefixed encoding makes it provably distinct from the two-segment reserved path (specification section 5.1), so it cannot collide. |

The last two are the vectors that distinguish a correct implementation from one that reconstructed
the guard over display strings, and they assert **acceptance**, which is why they matter: a
string-matching implementation that over-rejects passes a corpus containing only rejection vectors.

dogtag's own record of the prefix-versus-exact-match change is at
`crates/dogtag-standard-rs/src/profile_tree.rs:54-66`. What transfers is the argument, not the
string operation; specification section 11.2 states that distinction.

### Class 16 - Unicode version sensitivity (new, and honest about its limits)

`ROAX-CANON/1` pins Unicode 15.1 (specification section 6.1). NFC is version-dependent, so an
implementation whose tables come from a different Unicode version may legitimately differ.

This class carries strings whose NFC form is stable across recent Unicode versions, plus a marker
vector recording which Unicode version produced the expected values, so that a mismatch surfaces as
"your ICU is version X" rather than as an unexplained hash difference.

**Stated at the strength of the evidence:** the need for the pin is inferred from dogtag having
found it necessary in code (`crates/dogtag-standard-rs/src/encode.rs:6-7`). No specific character
whose NFC changed between Unicode versions has been identified and confirmed for this corpus. Doing
so is outstanding work, and until it is done this class detects version *mismatch* by declaration
rather than by demonstration.

## 4. Seed material that already exists

The canonicalization research built a 26-leaf adversarial corpus covering classes 1, 2, 4, 5, 6 and
7, and ran it through five implementations to identical roots. Its discrimination checks all pass:

```
  [PASS] FHIR 0.010 != 0.01  (precision preserved; RFC 8785 would collapse them)
  [PASS] FHIR 1.50 != 1.5
  [PASS] FHIR 2.0 stays '2.0' not '2'
  [PASS] 1e2 -> DECIMAL '100' vs 100 -> INTEGER '100': different tag, different leaf
  [PASS] int64Max survives exactly (JCS gives ...776000)
  [PASS] beyondDouble survives exactly
  [PASS] -0 canonicalises to 0
  [PASS] string "5" != integer 5 (type tag)
  [PASS] [] != {} != null   (dogtag collapses all three)
  [PASS] nested a.b != literal dotted key "keyCollisionB.c"
  [PASS] all 26 leaf hashes distinct; all 26 encoded paths distinct
```

Those results are carried from that research and were **not** re-run while writing this document.

Two caveats an implementer must know before treating that work as a corpus:

1. Its `flatten` uses **syntactic tag inference**, which specification section 4 says is unsafe.
   That is adequate for a fixed corpus where the tags are pinned by the vector file, and it MUST NOT
   ship in a library.
2. Those implementations are ~250-350 lines each, with no error taxonomy, no streaming and no schema
   binding. They are specification aids, not libraries.

Classes 3, 8, 9, 10, 11, 12, 13, 14, 15 and 16 are not covered by that seed and are new work.

## 5. Appendix - the JCS demonstration script

Specification section 13.1 disqualifies JCS on a demonstrated collision rather than an opinion.
This is the script, so a reader can check rather than trust. Run with Node >= 21.

```js
const lits = ["0.010","0.01","1.50","1.5","2.0","1e2","100",
              "9223372036854775807","1234567890123456789.1"];
console.log("node", process.version);
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

console.log("--- UTF-16 (JCS 3.2.3) vs UTF-8 key order ---");
const keys = ["z","é","\u{1F600}","Ｚ"];
const name = k => "U+" + k.codePointAt(0).toString(16).toUpperCase().padStart(4,"0");
const u16 = [...keys].sort();
const u8  = [...keys].sort((a,b) =>
  Buffer.compare(Buffer.from(a,"utf8"), Buffer.from(b,"utf8")));
console.log("  UTF-16:", u16.map(name).join(" , "));
console.log("  UTF-8 :", u8.map(name).join(" , "));
console.log("  same? ", JSON.stringify(u16) === JSON.stringify(u8));

console.log("--- JCS s3.1 forbids normalization ---");
const nfc = "é", nfd = "é";
console.log("  NFC:", Buffer.from(nfc,"utf8").toString("hex"),
            " NFD:", Buffer.from(nfd,"utf8").toString("hex"));
console.log("  render identically:", nfc.normalize("NFC") === nfd.normalize("NFC"),
            " JCS-distinct:", nfc !== nfd);
```

Expected output on Node v22.21.0, reproduced while writing this document:

```
node v22.21.0
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
--- UTF-16 (JCS 3.2.3) vs UTF-8 key order ---
  UTF-16: U+007A , U+00E9 , U+1F600 , U+FF3A
  UTF-8 : U+007A , U+00E9 , U+FF3A , U+1F600
  same?  false
--- JCS s3.1 forbids normalization ---
  NFC: c3a9  NFD: 65cc81
  render identically: true  JCS-distinct: true
```

This script belongs in the corpus repository as a standing regression, because the argument it
supports is the load-bearing one for the whole design.
