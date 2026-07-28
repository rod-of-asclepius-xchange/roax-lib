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

### 1.2 The corpus expresses what is REQUIRED, and no more

> **Standing rule, binding on every vector class in this document and on every class added later:**
>
> The corpus expresses what is **required** of any conforming implementation, and no more.
> Anything still open must be **expressible either way, or absent**.
> A corpus that mandates one side of an open design question has quietly **decided** it, because
> every implementation built against the corpus inherits that decision as though it were settled.

**Why this is dangerous, and why it is easy to miss.** This is the same class of defect as the
corpus contradicting the specification (section 1.1), but it is harder to see, because it does not
look like disagreement. It looks like **completeness**. A required field reads as thoroughness, and
nothing in the corpus flags that the field presumes an answer to a question `docs/decisions.md`
records as open. The specification says a decision is open, the corpus quietly says it is not, and
the corpus is the artifact implementations are actually built against.

**It has already happened twice in this design.** `schemas/envelope-1.0.json` required `masterSalt`
in every full copy, which is unimplementable under decision D4b where no `masterSalt` exists; that
was removed and the envelope now carries per-leaf salts, which are expressible under either answer.
The corpus then still required `masterSaltHex` on every `recordVector`, reproducing the same
foreclosure one file over. Twice in the same design is a pattern, which is why the rule is written
down rather than fixed case by case.

**This is a future-proofing constraint, not a tidiness one**, and it connects directly to
specification section 12.2. A corpus that hard-codes one salt strategy is not upgradeable. If D4 is
ruled the other way, every implementation that passed such a corpus has already baked in the
assumption, and reconciling them is not a version bump. It is a fork.

**How to apply it to a new vector class.** For each required field, ask which decision in
`docs/decisions.md` it presumes. If that decision is open, the field belongs in one of three places:
optional, absent, or expressible both ways through a `oneOf`. The exception is a vector class whose
**subject** is the open mechanism: `saltVector` requires `masterSaltHex` because it tests the
section 7 derivation, and `unlinkabilitySide` requires it because class 12 is where master-salt
freshness *is* the assertion. Testing a mechanism is not the same as presuming it, and
`schemas/conformance-corpus-1.0.json` records that distinction on each of those definitions so a
later editor does not "harmonize" them.

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

**Seventeen classes.** A class with no vectors is a coverage gap and the corpus build MUST report it
rather than passing silently.

The count is stated because a gap check built off it is the intended use, and a stale count means
the highest-numbered class is skipped silently. `schemas/conformance-corpus-1.0.json` sets the
`classRef` maximum to 17 to match.

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

**Plus the vector class 1 delegates here.** `1e2` bound as DECIMAL and `100` bound as INTEGER MUST
be different leaves, even though both encode to the digits `100`, because the type tag differs and
the tag is inside the leaf preimage (specification section 8). This is the pair that proves the tag
is doing work independently of the encoded value, which is why it belongs in this class rather than
in class 1's equality table. The seed material at section 4 already exercises it.

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

**The floor is the four reserved paths specification section 11.2 marks mandatory to disclose**,
plus whatever the profile adds on top, and this class MUST carry a vector proving where its upper
edge is: a disclosed copy that **omits `roax.issuer.keyId` MUST be ACCEPTED** when the record
committed one. That path is committed inside the root but OPTIONAL to disclose, because requiring
it would permanently bind an anchored record to the key it was issued under and leave no rotation
path, which specification section 12.2 rules out. Without that vector, an implementation that
over-tightens the floor to every reserved path passes this class while breaking key rotation, and
nothing else in the corpus would catch it.

JSON Schema cannot express any of this, so it is enforced in code and can only be pinned here. See
specification sections 10.2 and 11.2.

### Class 15 - reserved-namespace guard

A record-supplied path is rejected when its **first segment** is a `KEY` whose **NFC-normalized**
key begins with the ASCII prefix `roax.` (specification section 11.2). Reserved paths are
**single segments carrying the literal dotted name**, so this is a test on one key's own characters,
not on a rendered display path and not on a sequence of segments.

| Vector, as segments | Expected | Why |
|---|---|---|
| `[KEY("roax.recordId")]` | **Reject** | It *is* a reserved path. A direct collision. |
| `[KEY("roax.anythingElse")]` | **Reject** | The guard is on the `roax.` prefix within the first key, not on the exact reserved names, so a future reserved leaf cannot be squatted before it is defined. |
| `[KEY("roax")]` | **Accept** | An ordinary record field. No reserved path is the bare segment `KEY("roax")`, so it collides with nothing. |
| `[KEY("roaxX"), KEY("foo")]` | **Accept** | A different key entirely. |
| `[KEY("a"), KEY("roax.foo")]` | **Accept** | The guard applies to the FIRST segment only. This path differs from every reserved path in segment count and cannot collide with one. |
| `[KEY("Kelvin")]`, which NFC-normalizes to `Kelvin` | **Accept** | A first-segment key that changes under NFC and still does not begin with `roax.`. Pins that the guard normalizes and then compares, rather than over-rejecting anything non-ASCII. |

**Four of these assert acceptance, and that is the point of the class.** A corpus containing only
rejection vectors is passed by an implementation that over-rejects, and over-rejection is the more
likely failure here: it is what a guard written against a display path, or applied to every segment
instead of the first, actually does.

**This class was rewritten, and the earlier version was wrong in a way worth recording.** It
required rejecting the bare namespace `roax` and the adjacent squat `roaxX`. Both are ordinary
record keys under the single-segment reserved-path model of specification section 11.2, and
rejecting them is over-broad: it would refuse a legitimate record for using a field name that
collides with nothing. That class had been written for a string-path model this specification
deliberately departed from, and it survived the departure because nobody re-derived it.

**The NFC case, stated honestly about its own limit.** An earlier version of this class carried a
row reading "a key that NFC-normalizes into the reserved prefix, MUST be rejected". **No such key
exists, so that row promised a vector nobody could build.** Scanning every assigned code point on
Node v22.21.0 finds no non-ASCII character whose NFC form contains `r`, `o`, `a`, `x` or `.`; the
only ASCII letter reachable that way at all is uppercase `K`, from U+212A KELVIN SIGN, which is not
in `roax.`.

So specification section 11.2's MUST that the guard compare the **normalized** key is currently
**unobservable at the guard**: for every input a record can supply, checking before or after
normalization gives the same verdict. Section 11.2 states that limit in the same terms and explains
why the rule stands regardless, which is that it is a fact about today's prefix characters rather
than about the design.

That is why the row above tests what can actually be demonstrated instead. `[KEY("Kelvin")]`, whose
first key is `U+212A` followed by `elvin`, is a real key that changes under NFC, and it MUST be
**accepted**, because its normalized form does not begin with `roax.`. It catches the failure that
is reachable today, which is a guard that over-rejects anything non-ASCII rather than one that
under-rejects a crafted collision.

**The demonstrable half of the normalization requirement is class 4**, which already carries NFC
versus NFD in keys and asserts that the hashing path normalizes. This class does not restate it.

U+212A appears in specification section 11.2 as evidence that NFC can cross into ASCII, and it must
not be read there or here as an instance of a key that normalizes into the reserved prefix. This
class follows the same convention as class 16, which says outright when it detects a property by
declaration rather than by demonstration.

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

### Class 17 - a disclosed copy MUST NOT leak a withheld leaf's salt

A disclosed copy carries the salt of every leaf it reveals and the salt of **no other leaf**
(specification sections 10 and 10.1).

| Vector | Expected |
|---|---|
| A disclosed copy carrying exactly the salts of its revealed leaves | **Accept** |
| The same copy with one withheld leaf's salt added | **Reject** |
| A disclosed copy carrying a `salts` array, the full-copy field | **Reject** |
| A disclosed copy carrying a `masterSalt` field | **Reject** |
| A full copy whose `salts` array omits one leaf of the union | **Reject** |
| A full copy whose `salts` array length does not equal `leafCount` | **Reject** |

**This class exists because the violation verifies correctly.** Extra salts do not change any leaf
hash, so an implementation that ships every salt in a disclosed copy produces an envelope that
passes the root check, passes the inclusion proofs and passes every other class in this list, while
leaking every withheld field to a dictionary search. There is no failing assertion anywhere else to
catch it.

`schemas/envelope-1.0.json` closes most of this structurally by forbidding `salts` alongside
`disclosure`, which leaves no place to put a withheld leaf's salt. The rows this class still has to
carry in code are the count relationships in the last two rows, which JSON Schema cannot express
because they relate `salts.length`, `leafCount` and the actual leaf set to each other.

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

Classes 3, 8, 9, 10, 11, 12, 13, 14, 15, 16 and 17 are not covered by that seed and are new work.

The one partial exception is the pair class 1 delegates to class 7, `1e2` as DECIMAL against `100`
as INTEGER, which the seed already discriminates - see the fourth line of the block above.

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
