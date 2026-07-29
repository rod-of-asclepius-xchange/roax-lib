# The ROAX conformance corpus

**Status:** definition. A corpus artifact exists and is governed by the 1.0 schema below; no artifact
validates against the successor contract this document defines yet.
**Schema:** [`schemas/conformance-corpus-2.0.json`](../schemas/conformance-corpus-2.0.json), which is
the contract this document defines.
[`schemas/conformance-corpus-1.0.json`](../schemas/conformance-corpus-1.0.json) is retained because
it, and not the successor, governs the corpus artifact as committed today.
The successor is a major bump because it deletes definitions the committed artifact still uses, so
that artifact does not validate against it and has to be rebuilt to it; the requirements below are
stated against the successor and the gap is named in section 3.

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

**It had already happened twice in this design, and the case is worth keeping now that it is
closed.** `schemas/envelope-1.0.json` required `masterSalt` in every full copy, which was
unimplementable under decision D4b where no `masterSalt` exists; that was removed and the envelope
carries per-leaf salts, which were expressible under either answer. The corpus then still required
`masterSaltHex` on every `recordVector`, reproducing the same foreclosure one file over. Twice in the
same design is a pattern, which is why the rule is written down rather than fixed case by case.

**Decision D4 has since been ruled D4b**, so `masterSalt` no longer exists anywhere in the design and
neither foreclosure is reachable today. That does not retire the rule. It retires this example,
which is kept because it is the clearest one available and because the rule still binds on decisions
A, C and D, all of which remain open (`docs/decisions.md` Part 1).

**This is a future-proofing constraint, not a tidiness one**, and it connects directly to
specification section 12.2. A corpus that hard-codes one side of an open question is not upgradeable.
Every implementation that passed such a corpus has already baked in the assumption, and reconciling
them is not a version bump. It is a fork.

**How to apply it to a new vector class.** For each required field, ask which decision in
`docs/decisions.md` it presumes. If that decision is open, the field belongs in one of three places:
optional, absent, or expressible both ways through a `oneOf`. The exception is a vector class whose
**subject** is the open mechanism, because testing a mechanism is not the same as presuming it.
**That exception currently has no instance.** The two it used to have, `saltVector` and
`unlinkabilitySide.masterSaltHex`, both existed to test the derived-salt mechanism and were removed
with it when D4 was ruled; `saltVector` is gone from
`schemas/conformance-corpus-2.0.json` entirely, because under section 7 a salt is an input rather
than something derived from anything, and `leafVector.saltHex` already carries it.
Both definitions survive in `schemas/conformance-corpus-1.0.json`, marked superseded, for the
narrow reason that the committed corpus still carries vectors of both shapes and that file has to
keep describing what it governs; they are not the design as it now stands. A later editor
adding such a class should record the distinction on the definition itself, as those two did.

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

**Nineteen classes.** A class with no vectors is a coverage gap and the corpus build MUST report it
rather than passing silently.

The count is stated because a gap check built off it is the intended use, and a stale count means
the highest-numbered class is skipped silently. Both
`schemas/conformance-corpus-1.0.json` and `schemas/conformance-corpus-2.0.json` set the
`classRef` maximum to 19 to match.

**Class 19 is expressible only under the successor schema.** Its vector shape is the `normalization`
group, which `schemas/conformance-corpus-2.0.json` introduces and
`schemas/conformance-corpus-1.0.json` does not carry, because adding it to the file that governs the
committed artifact would describe vectors that artifact has no way to hold. Class 18 needs no new
group and is expressible under both, through `envelopeVector.verifierConfig`. Until the corpus is
rebuilt against the successor, class 19 has no vectors, and that is a stated gap rather than a
silent one.

**Classes 18 and 19 were added, and class 12 was rewritten, when the ten engineering decisions were
ruled on 2026-07-28.** Class numbers are stable: class 12 kept its number and its subject and lost
only its mechanism, so nothing renumbered and every existing citation of classes 13 through 17 in the
specification and the schemas still points where it did.

**Three of the classes below assert a relation rather than a pinned value**, and that is deliberate
rather than incomplete. Class 12 asserts two leaf hashes are **different**, class 19 asserts two
records produce the **same** root, and class 18 asserts accept or reject. Each is fully determined
without a hexadecimal expected value, and a corpus build that has not yet computed one has not
therefore left the class under-specified.

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
extended audit path; and a proof carrying a **forged tree size** chosen to make an internal node land
where a leaf should be.

The internal-node case is dogtag's C1 hazard, which it demonstrates in its own test suite at
`crates/dogtag-standard-rs/src/merkle.rs:196-229`.

**Building this class produced a correction to the specification, and the corrected reasoning is what
the class now tests.** An earlier version of this document said RFC 9162 rejects the internal-node
case structurally because it is position-bound. It does not. RFC 9162 section 2.1.3.2 takes the tree
size as an **input**, so an attacker who supplies both the leaf hash and the tree size can pick a
shape that walks an internal node to the genuine root: on an 8-leaf tree, `MTH(L[0:4])` presented as
the leaf at index 0 with a forged tree size of 2 and the audit path `[MTH(L[4:8])]` verifies. That
was measured, and reproduced on Node v22.21.0; specification section 11.1 records it in full.

**What actually closes the case is the `0x00` leaf-domain byte plus specification section 10 step 2**,
which requires a verifier to recompute the leaf hash from the disclosed path, tag, value and salt
rather than accept one. A recomputed leaf hash is `0x00`-domained and an internal node is
`0x01`-domained, so the substitution needs a second preimage.

**Consequence for how this class is run.** These vectors MUST be driven through the full disclosed-copy
verification path, not through a bare fold primitive. A runner that hands `verifyInclusion` a leaf
hash directly is testing the primitive dogtag documents as proving nothing on its own
(`merkle.rs:86-91`), and it will record a pass for an implementation that has no defence at all.

### Class 10 - the three real MOH records

Whole, with their roots and leaf counts.

Records are referenced by file, never inlined, so that no reference schema or sample is copied into
this repository. The reference material lives outside the repository by design.

### Class 11 - the schema binding itself

The type map is a data file and MUST be in the corpus, with vectors asserting that a given structured path and observed JSON kind under a given map yield a given tag, and that an uncovered path-kind pair fails closed, as required by specification section 4.2.
Each vector MUST name the exact content ID, semver, `recordType`, opaque `schemaVersion` and `jsonKind` of the artifact lookup under test, as required by specification section 4.2.

This is the highest-risk surface in the design (specification section 4) and also the easiest to
diff, which is the one piece of good news about it.

At minimum the fail-closed rows MUST cover vaccination `dose` and `expiryDateTime`, PDT
`$template.name`, FHIR `Narrative.div`, FHIR `base64Binary`, and an unknown empty array and empty
object, because `docs/type-maps.md` sections 1 and 3 record those as the reachable places where a
proposal or mechanically known empty-container tag could otherwise be mistaken for an operative
binding.

**One row was added when decision D9 was ruled:** a type map binding any path to **tag 8 `BLOB_REF`**
MUST be **rejected**, because the content-addressed binding is defined and selected by no version-1
profile (specification section 6.5). That is a rejection of the map rather than a fail-closed on a
path, so it is a third outcome and both corpus schemas give it its own `oneOf` branch.
Without this vector, "registered but unselected" is a sentence, and the schemas accept tag 8 in order
to pin its carrier form - which is exactly the combination that lets an implementation quietly honour
a binding no profile has declared.

### Class 12 - cross-record unlinkability under independent per-leaf salts

**Two records for the same subject, sharing a path and a value at that path, MUST produce different
leaf hashes for that path.**

This class kept its number and its subject when decision D4 was ruled D4b and lost its mechanism.
The old version built the two records with two different `masterSalt` values and asserted the same
outcome. There is no master salt now (specification section 7), so the assertion is made directly
against the property that matters, which is what the old version was proxying for anyway.

**It is the only class that catches an implementation whose salts are not independent**, and that
violation is invisible to every other class in this list because each record verifies perfectly on
its own. The reachable ways to get it wrong are worth naming, because the class has to catch all
three:

- **A deterministic salt.** Deriving a salt from the path, from the value, or from a content-derived
  seed, so that reissuing a record reproduces the same root. This reads like a feature -
  "reissuance is idempotent" - which is exactly why the specification forbids it in section 7 and why
  a vector rather than a sentence enforces it.
- **A salt reused across leaves.** One draw per record rather than one per leaf.
- **A salt reused across records**, which is the patient-linkage failure itself.

#### The shape this class has to take, and its honest limit

**This class asserts a relation between generated values rather than a pinned expected value**, and
that is forced by the ruling rather than a shortcut. Under D4b the salts are independently random, so
no fixed hexadecimal expectation can exist: a vector file cannot pin what the implementation under
test is required to draw freshly. A `class12Vector` therefore describes an issuance to perform and
the relation the results MUST satisfy.

The runner issues the same `(path, tag, value)` under the vector's `trials` independent issuances,
and asserts that all of the resulting salts are distinct and all of the resulting leaf hashes are
distinct.

> **The limit, stated rather than left for a reader to discover.** This detects a **deterministic**
> or **reused** salt, which is the failure that has actually happened in comparable systems. It does
> **not** detect a weak or predictable CSPRNG: an implementation drawing 16 bytes from a poorly
> seeded generator passes every trial while providing much less than the 128 bits specification
> section 7 requires. No fixed vector file can test a randomness source. That gap belongs to
> implementation review, and this document states it here rather than letting a passing class read as
> a guarantee it is not.

This class follows the same convention as classes 15 and 16, which say outright where they detect a
property by declaration rather than by demonstration.

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

**The floor is the five reserved paths specification section 11.2 marks mandatory to disclose**,
including `roax.typeMap.id`, plus whatever the profile adds on top.
This class MUST carry a vector proving where its upper edge is: a disclosed copy that **omits
`roax.issuer.keyId` MUST be ACCEPTED** when the record
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
| A disclosed copy carrying any seed field, `masterSalt` or otherwise | **Reject** |
| A full copy whose `salts` array omits one leaf of the union | **Reject** |
| A full copy whose `salts` array length does not equal `leafCount` | **Reject** |

**The seed row survives decision D4's ruling on purpose.** There is no `masterSalt` in this design
any more (specification section 7), and `additionalProperties: false` already rejects an unknown
field, so the row is cheap. It is retained because specification section 7.3 rule 3 binds any future
revision that reintroduces a derived salt, and a revision that added a seed to the envelope would
hand every holder the ability to recompute every withheld leaf's salt in a copy that still verified.

**This class exists because the violation verifies correctly.** Extra salts do not change any leaf
hash, so an implementation that ships every salt in a disclosed copy produces an envelope that
passes the root check, passes the inclusion proofs and passes every other class in this list, while
leaking every withheld field to a dictionary search. There is no failing assertion anywhere else to
catch it.

`schemas/envelope-2.0.json` closes most of this structurally by forbidding `salts` alongside
`disclosure`, which leaves no place to put a withheld leaf's salt. The rows this class still has to
carry in code are the count relationships in the last two rows, which JSON Schema cannot express
because they relate `salts.length`, `leafCount` and the actual leaf set to each other.

### Class 18 - outside-the-root fields are never authority

**This class exists because a normative sentence was demonstrably not enough.** Specification section
11.3 states that fields outside the root are hints and never authority. dogtag had the equivalent
understanding written down and still shipped the `documentStore` bug, then needed an entire extra
mandatory issuer-whitelist pillar that exists only to compensate (`AGENTS.md:333` in the dogtag
monorepo). An implementer who agrees with the sentence and then reads the convenient field anyway is
the failure mode, so the corpus has to fail that implementation rather than trust it.

Every vector here **fails an implementation that trusts an outside-the-root field**, and passes one
that takes authority from the root and from its own configured anchoring layer.

| Vector | Expected | What it catches |
|---|---|---|
| A disclosed copy whose top-level `recordType` disagrees with the disclosed `roax.recordType` leaf | **Reject** | A verifier that reads the envelope field instead of the committed leaf. The leaf is inside the root; the field is not. |
| The same, for `schemaVersion`, `recordId` and `issuer.id` in turn | **Reject** | The same mistake at the other profile and identity floor paths (specification section 11.2). |
| A top-level `typeMap.id` that disagrees with the disclosed `roax.typeMap.id` leaf | **Reject before resolving a record leaf** | A verifier selecting a convenient map from the discovery hint instead of the ID committed inside the root (specification sections 4.2, 10 and 11.2). |
| Candidate type-map bytes whose content ID does not reproduce the committed `roax.typeMap.id`, including a second artifact with the same semver | **Reject** | A verifier selecting by version or locator rather than the exact immutable artifact ID (specification section 4.2 and [`type-maps.md`](type-maps.md) section 4). |
| An envelope whose `hashAlg` disagrees with the `(root, hashAlg)` pair the verifier's anchoring registry records | **Reject** | A verifier taking the algorithm from the document rather than from the registry. This is exactly what specification section 7.4's H2 requires and what H1 does **not** provide. |
| An envelope whose `hashAlg` is absent from the verifier's configured allow-list, and present in the registry | **Reject** | The retired-algorithm case, which H2 alone does not close. Specification section 7.4, H3. |
| An envelope whose `anchor.registry` and `anchor.chainId` name a registry the verifier is not configured with, and which would return a valid pair | **Reject, without reading that registry** | The dogtag `documentStore` bug in this design's shape: an attacker-supplied address that answers "valid". A verifier MUST resolve the anchoring layer from its own configuration. |
| A well-formed envelope whose `anchor` block is absent entirely, verified against the verifier's own registry | **Accept** | The upper edge. `anchor` is a routing hint, so its absence MUST NOT make a verifiable record unverifiable, and an implementation that hard-requires it has made the field authority in a different way. |

**The last row is the reason this class cannot be only rejections.** A corpus of rejections alone is
passed by an implementation that rejects everything with an `anchor` mismatch including the case
where nothing is wrong, and treating a routing hint as required is itself a way of depending on it.

**What a runner needs that no other class needs.** These vectors are the only ones whose outcome
depends on what the *verifier* is configured with rather than only on the envelope, so
`envelopeVector` carries an optional `verifierConfig` block stating the anchoring facts and the
allow-list in force for that vector. Without it the expected outcome is not determined by the file.

### Class 19 - NFC normalization, end to end, with a root

`ROAX-CANON/1` normalizes strings and object keys to NFC before encoding, under Unicode 15.1
(specification section 6.1, decision D12 ruled D12a).

**This class carries a record whose string differs before and after NFC, in both forms, and asserts
they produce the same root.**

| Vector | Expected |
|---|---|
| A record carrying the NFD form of a string that changes under NFC | root `R` |
| The identical record carrying that string's NFC form | **the same root `R`** |
| The same pair with the differing sequence in an **object key** rather than a value | one root, equal across both forms |

Use a string whose NFC form is stable across recent Unicode versions, so that this class tests
normalization rather than the version pin; class 16 owns the version question and is honest about
what it can and cannot demonstrate.

**Why this is not covered by class 4.** Class 4 asserts NFC against NFD at **leaf** level, in values
and in keys. That catches an implementation whose `encodeValue` skips normalization. It does not
catch one that normalizes in `encodeValue` and then reaches the same string by another route - a key
compared before normalization, a reserved-leaf value written straight from the envelope, a path
segment re-encoded from a cached form. Class 19 asserts the property of the whole pipeline, over the
union of section 3.3, which is where those routes actually are.

**The assertion is equality, so the class is complete without a pinned hexadecimal root.** The value
of `R` is whatever the corpus build computes; what the vector fixes is that both forms produce one
value and that it is the same one. A pinned `R` is worth adding once the corpus file exists, as a
regression against the normalization silently changing, and the vector shape has room for it.

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

Classes 3, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18 and 19 are not covered by that seed and are new
work.

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
