# The ROAX conformance corpus

**Status:** definition.
A corpus artifact exists and is governed by the 1.0 schema below; no artifact validates against the successor contract this document defines yet.
**Schema:** [`schemas/conformance-corpus-2.0.json`](../schemas/conformance-corpus-2.0.json), which is the contract this document defines.
[`schemas/conformance-corpus-1.0.json`](../schemas/conformance-corpus-1.0.json) is retained because it, and not the successor, governs the corpus artifact as committed today.
The successor is a major bump because it REQUIRES the exact type-map artifact identity on the type-map and record vectors, which the committed artifact does not carry, so that artifact does not validate against it and has to be rebuilt to it.
It is not a major bump for the D4b vector shapes: those landed in the 1.0 file and in the artifact together, under the same-change rule in section 1.1.
The requirements below are stated against the successor.

---

## 1. Why this is normative and not decoration

Two independent reasons, and either alone would be sufficient.

**The engineering reason.**
dogtag achieved four-language agreement with **two** implementations, not four: Rust and TypeScript are independent, and Swift and Kotlin call the Rust crate through UniFFI.
There is no Swift Poseidon and no Kotlin Poseidon anywhere in that repository.
Agreement between the two real implementations is enforced by a shared JSON vector file, `packages/dogtag-standard-ts/testvectors.json`, which contains 15 leaf vectors, 5 `bytesToField` vectors, 11 Merkle-root vectors and 110 inclusion vectors.

ROAX additionally wants Go, and Go over UniFFI is awkward - UniFFI has no first-class Go backend.
So if ROAX ships five genuinely independent libraries, **the corpus stops being a safety net and becomes the entire enforcement mechanism.**
That is no longer conditional: decision D was ruled Da on 2026-07-29 to five independent, corpus-enforced libraries (`docs/decisions.md`, decision D).
The corpus was already built as though it would be, because retrofitting it after divergence has shipped is far worse.

**The review reason.**
Stated in the standards research as a disqualifier rather than a nice-to-have: "we invented our own canonicalization without cross-language test vectors" fails healthcare security review.
ROAX is inventing a canonical form.
That is defensible - sections 13.1 through 13.3 of the specification give the reasons - but only if the invention is accompanied by hostile cross-language vectors published before any library claims conformance.

**And dogtag supplies the warning for exactly this path.**
Its TypeScript `verify` silently diverged from the Rust one, and the divergence is *recorded rather than fixed* because it has no production consumer (`AGENTS.md:357`, which ends "Do NOT wire it into a product surface before reconciling it with the Rust implementation").

> An independent implementation that is not covered by the corpus **will** drift.
> There must be no "we will reconcile it later" path.

### 1.1 Precedence: the specification governs

This document and the corpus file it defines are the **executable arbiter** between two implementations that disagree, but they are **derived from** [`docs/spec/roax-canon-1.md`](spec/roax-canon-1.md) rather than independent of it.

**The specification is normative for meaning.
Where the two diverge, the specification governs.**

A divergence is a **release-blocking corpus defect**, and the corpus build MUST report it rather than letting an implementation pass against a vector the specification does not support.
Neither document may be changed alone: a change to a canonicalization rule lands in the same change as the corpus vectors that assert it, in both directions.

This is stated because of what section 1 just argued.
If the corpus is the entire enforcement mechanism, an arbiter that disagrees with the specification it arbitrates is worse than no arbiter: it certifies divergence as conformance.
The same statement appears as section 1.1 of the specification, deliberately, so that a reader arriving at either document finds it.

### 1.2 The corpus expresses what is REQUIRED, and no more

> **Standing rule, binding on every vector class in this document and on every class added later:**
>
> The corpus expresses what is **required** of any conforming implementation, and no more.
> Anything still open must be **expressible either way, or absent**.
> A corpus that mandates one side of an open design question has quietly **decided** it, because every implementation built against the corpus inherits that decision as though it were settled.

**Why this is dangerous, and why it is easy to miss.**
This is the same class of defect as the corpus contradicting the specification (section 1.1), but it is harder to see, because it does not look like disagreement.
It looks like **completeness**.
A required field reads as thoroughness, and nothing in the corpus flags that the field presumes an answer to a question `docs/decisions.md` records as open.
The specification says a decision is open, the corpus quietly says it is not, and the corpus is the artifact implementations are actually built against.

**It had already happened twice in this design, and the case is worth keeping now that it is closed.**
`schemas/envelope-1.0.json` required `masterSalt` in every full copy, which was unimplementable under decision D4b where no `masterSalt` exists; that was removed and the envelope carries per-leaf salts, which were expressible under either answer.
The corpus then still required `masterSaltHex` on every `recordVector`, reproducing the same foreclosure one file over.
Twice in the same design is a pattern, which is why the rule is written down rather than fixed case by case.

**Decision D4 has since been ruled D4b**, so `masterSalt` no longer exists anywhere in the design and neither foreclosure is reachable today.
That does not retire the rule.
It retires this example, which is kept because it is the clearest one available and because the rule still binds on decision C, which remains open (`docs/decisions.md` Part 1).
Decision A was ruled on 2026-08-02 and no longer holds anything open here, but the rule bound on it until that date, which is the point: the corpus never encoded a side of it.
D14 was the third case the rule held open, and it shows the rule working end to end: the class-19 key vector was withheld while D14 was open and was built under the ruling on 2026-07-30, so no implementation ever inherited an unruled answer from a data file.

**This is a future-proofing constraint, not a tidiness one**, and it connects directly to specification section 12.2.
A corpus that hard-codes one side of an open question is not upgradeable.
Every implementation that passed such a corpus has already baked in the assumption, and reconciling them is not a version bump.
It is a fork.

**How to apply it to a new vector class.**
For each required field, ask which decision in `docs/decisions.md` it presumes.
If that decision is open, the field belongs in one of three places: optional, absent, or expressible both ways through a `oneOf`.
The exception is a vector class whose **subject** is the open mechanism, because testing a mechanism is not the same as presuming it.
**That exception currently has no instance.**
The two it used to have, `saltVector` and `unlinkabilitySide.masterSaltHex`, both existed to test the derived-salt mechanism and were removed with it when D4 was ruled.
`saltVector` is gone from both `schemas/conformance-corpus-1.0.json` and `schemas/conformance-corpus-2.0.json` entirely, because under section 7 a salt is an input rather than something derived from anything, and `leafVector.saltHex` already carries it.
The deletion reached the 1.0 file rather than the successor alone because section 1.1 above requires a canonicalization change to land with the vectors that assert it, and the committed corpus was rebuilt in the same change.
A later editor adding such a class should record the distinction on the definition itself, as those two did.

## 2. Release gates

These are requirements on the project, not on the file.

1. **The corpus is a single versioned artifact in this repository**, normative, versioned with the specification.
2. **Every language's CI runs it and fails on any mismatch.**
   dogtag's `crates/dogtag-standard-rs/tests/ffi_parity.rs` is the model: one file, both sides, byte identity asserted.
3. **The corpus is not considered validated until an implementation written by a different author, from the specification text alone, passes it unmodified.**

Gate 3 is the one that is easy to drop and it is the one that matters most.
The canonicalization research produced five implementations - Python, Rust, Go, Swift, TypeScript - that agree byte-for-byte on all three real MOH records and on a 26-leaf adversarial corpus.
That is real evidence.
But the author of that research wrote all five, and said so plainly: they do not share a JSON parser, a number representation, a Unicode API, a map implementation or a sort implementation, but they do share one author's reading of the specification.

**A shared misreading is exactly the failure a corpus exists to catch, and five implementations by one author cannot catch it.**
So gate 3 is a release gate, not a caveat.

### 2.1 Gate 3 status: partially satisfied, ruled 2026-07-29

**Gate 3 is PARTIALLY SATISFIED.
It is not met, and it MUST NOT be recorded as met.**
This subsection owns that status; other documents point here rather than restating it.

**What the ruling credits.**
The ROAX libraries written so far were each produced by a different team from the one that built the corpus.
Each was explicitly instructed not to read [`corpus/tools/roax_ref.py`](../corpus/tools/roax_ref.py) or [`corpus/tools/roax_ref.mjs`](../corpus/tools/roax_ref.mjs) while implementing, and each was validated against the corpus only after it had been written.
That is genuine independence from the corpus tooling, and independence from the corpus tooling is what gate 3 chiefly protects.
Five of them live in this repository: the Rust library under [`rust/`](../rust), the TypeScript library under [`src/`](../src), whose disagreements with this corpus are recorded in [`docs/typescript-implementation-findings.md`](typescript-implementation-findings.md), the Python library under [`python/`](../python), whose disagreements are recorded in [`python/FINDINGS.md`](../python/FINDINGS.md), the Swift library under [`swift/`](../swift), whose disagreements are recorded in [`swift/FINDINGS.md`](../swift/FINDINGS.md), and the Kotlin library under [`kotlin/`](../kotlin), whose disagreements are recorded in [`kotlin/FINDINGS.md`](../kotlin/FINDINGS.md).

**What the ruling withholds.**
A single briefing author wrote every implementation brief, and those briefs carried specific warnings: trailing zeros in a decimal are significant, the display path is never hashed, and an unbound path fails closed.
A genuinely unrelated third party reading only the specification text would not have had those warnings.
So a briefed implementation cannot demonstrate that the specification text alone carries those three rules, which is the demonstration gate 3 asks for.

**Gate 3 is fully cleared only when an implementation passes that the same briefing author did not brief.**
Until then the gate stays open, and no document may describe the corpus as validated in the sense gate 3 requires.

## 3. Mandatory vector classes

**Twenty classes.**
A class with no vectors is a coverage gap and the corpus build MUST report it rather than passing silently.

The count is stated because a gap check built off it is the intended use, and a stale count means the highest-numbered class is skipped silently.
Both `schemas/conformance-corpus-1.0.json` and `schemas/conformance-corpus-2.0.json` set the `classRef` maximum to 20 to match.

**A class with no vectors is not the only way this corpus can fail to gate.**
A vector GROUP a runner does not read is worse, because it is invisible: the runner contributes zero assertions for it and reports the same green it reported before the group existed, and the coverage check above cannot see it either.
Every runner MUST therefore enumerate the groups the corpus file carries and FAIL on one it does not consume, rather than defaulting an unknown group to the empty list.
That is enforced in `corpus/tools/check_corpus.mjs` and in all five library runners, and it was added BEFORE class 20 so that each runner went red for a reason its author controlled.

**Both new classes are expressible under both schema versions.**
Class 19's vector shape is the `normalization` group, which `schemas/conformance-corpus-1.0.json` carries alongside `schemas/conformance-corpus-2.0.json`, because the committed artifact was rebuilt in the same change that added the class rather than left to a later migration.
Class 18 needs no new group and is expressible through `envelopeVector.verifierConfig`.

**Classes 18 and 19 were added, and class 12 was rewritten, when the ten engineering decisions were ruled on 2026-07-28.**
Class numbers are stable: class 12 kept its number and its subject and lost only its mechanism, so nothing renumbered and every existing citation of classes 13 through 17 in the specification and the schemas still points where it did.

**Three of the classes below assert a relation rather than a pinned value**, and that is deliberate rather than incomplete.
Class 12 asserts two leaf hashes are **different**, class 19 asserts two records produce the **same** root, and class 18 asserts accept or reject.
Each is fully determined without a hexadecimal expected value, and a corpus build that has not yet computed one has not therefore left the class under-specified.

### Class 1 - FHIR decimals

`0.010` versus `0.01`; `1.50` versus `1.5`; `2.0` versus `2`; `-0.0`; `0.00000000000000000001`; a 40-digit integer part; a 40-digit fraction.

Every pair above MUST produce **different** leaves, which is the point of the class.

**Exponent forms are the exception in this class, and the corpus states which way each goes so it cannot be misread.**
At a path bound to DECIMAL, under the expansion rule of specification section 6.2:

| Vectors | Expected | Why |
|---|---|---|
| `1e2`, `1.0e2`, `100` | **All three EQUAL.** Same encoded value `100`, same leaf. | Trailing zeros of the integer part carry no precision in the output grammar and cannot. |
| `100.0` versus that trio | **DISTINCT.** Encodes `100.0`. | Trailing zeros of the fraction are significant, per FHIR R4 SHALL. |
| `1.00e1` | `10.0` | `f' = max(0, 2 - 1) = 1`. |
| `1.5e-2` | `0.015` | `f' = 1 + 2 = 3`. |
| `0e5` | `0` | Integer part normalizes to a single `0`. |

The INTEGER-versus-DECIMAL distinction is a separate matter and belongs to class 7: `1e2` bound as DECIMAL and `100` bound as INTEGER carry different type tags and are different leaves regardless of sharing the encoded digits `100`.

This class is the reason the whole scheme exists.
See specification section 6.2.

### Class 2 - integers beyond 2^53

`9223372036854775807`, `-9223372036854775808`, and a 40-digit integer.

### Class 3 - rejection vectors

MUST error, never silently canonicalize: `1.4e+9999`; `01`; `1.`; `.5`; `+1`; `NaN`; `Infinity`; a decimal with an empty fraction.

An implementation that accepts any of these is non-conformant even if it produces a "reasonable" value.

`1.4e+9999` is the one of these that the input grammar admits, so it needs an explicit rule rather than a grammar rejection.
Specification section 6.2 supplies it: the expanded positional form MUST NOT exceed 1024 total digits, and that bound is a fixed constant rather than an implementation choice, for the reason section 13.3 gives against RDFC-1.0.
This class MUST also carry a vector just inside the bound that is accepted, so an implementation cannot pass by rejecting everything large.

### Class 4 - Unicode

- NFC versus NFD in values **and** in keys.
- A key and a value above the BMP (U+1F600).
- A fullwidth character (U+FF3A) alongside its ASCII counterpart.
  This is the pair that separates UTF-16 from UTF-8 ordering, and it is why the ordering demonstration in specification section 13.1 works.
- An unpaired surrogate in the input - MUST be rejected.

### Class 5 - structure

Empty array, empty object and explicit null, at the same path in three sibling records, asserting **three distinct roots**.

This is the class that would catch an implementation that inherited dogtag's collapse of all three to a single leaf (`crates/dogtag-standard-rs/src/flatten.rs:96-115`).

### Class 6 - path

A key containing `.`, `[`, `]`; a key that is the empty string; a nested `a.b` versus a literal `"a.b"` key; an array of one; deep nesting; an array index at `2^32 - 1`, and one at `2^32` which MUST be rejected.

### Class 7 - type tags

`"5"` versus `5` versus `5.0`; `"true"` versus `true`.

**Plus the vector class 1 delegates here.**
`1e2` bound as DECIMAL and `100` bound as INTEGER MUST be different leaves, even though both encode to the digits `100`, because the type tag differs and the tag is inside the leaf preimage (specification section 8).
This is the pair that proves the tag is doing work independently of the encoded value, which is why it belongs in this class rather than in class 1's equality table.
The seed material at section 4 already exercises it.

### Class 8 - tree shape

Leaf counts **1, 2, 3, 5, 7, 8, 9, 130**, and an inclusion proof for **every** leaf at each of those sizes.

RFC 9162's split rule - `k` is the largest power of two strictly smaller than `n` - is where a hand-rolled tree goes wrong, and it goes wrong only at non-power-of-two sizes.
A corpus that tests only 8 and 16 proves nothing.

### Class 9 - negative proof vectors

MUST NOT verify: a valid proof against a wrong root; a proof with one sibling flipped; a proof presenting an **internal node as a leaf**; an index out of range; a truncated audit path; an extended audit path; and a proof carrying a **forged tree size** chosen to make an internal node land where a leaf should be.

The internal-node case is dogtag's C1 hazard, which it demonstrates in its own test suite at `crates/dogtag-standard-rs/src/merkle.rs:196-229`.

**Building this class produced a correction to the specification, and the corrected reasoning is what the class is required to test.**
An earlier version of this document said RFC 9162 rejects the internal-node case structurally because it is position-bound.
It does not.
RFC 9162 section 2.1.3.2 takes the tree size as an **input**, so an attacker who supplies both the leaf hash and the tree size can pick a shape that walks an internal node to the genuine root: on an 8-leaf tree, `MTH(L[0:4])` presented as the leaf at index 0 with a forged tree size of 2 and the audit path `[MTH(L[4:8])]` verifies.
That was measured and reproduced on Node v22.21.0; specification section 11.1 records it in full.

**What actually closes the case is the `0x00` leaf-domain byte plus specification section 10 step 2**, which requires a verifier to recompute the leaf hash from the disclosed path, tag, value and salt rather than accept one.
A recomputed leaf hash is `0x00`-domained and an internal node is `0x01`-domained, so the substitution needs a second preimage.

**Consequence for how this class is run.**
These vectors MUST be driven through the full disclosed-copy verification path, not through a bare fold primitive.
A runner that hands `verifyInclusion` a leaf hash directly is testing the primitive dogtag documents as proving nothing on its own (`merkle.rs:86-91`), and it will record a pass for an implementation that has no defence at all.

**The committed 1.0 corpus does not yet meet that requirement.**
Its two internal-node rows carry the honest tree sizes 8 and 130, no row carries attack `forged-tree-size`, and the `negativeProof` carrier supplies no structured path, tag, value or salt from which a verifier could recompute a leaf hash (`corpus/conformance-corpus-1.0.json`, `negative-internal-node-as-leaf` and `negative-internal-node-as-leaf-n130`; `schemas/conformance-corpus-1.0.json`, `$defs.negativeProofVector`).
The class therefore remains a named release-gate gap until a corpus rebuild adds an expressible full-disclosure attack row.

### Class 10 - the three real MOH records

Whole, with their roots and leaf counts.

Records are referenced by file, never inlined, so that no reference schema or sample is copied into this repository.
The reference material lives outside the repository by design.

**A vector in this class MUST name a carrier the salts come with, and there are exactly two.**
Either a bare record file together with the salts file its root was computed under, or a single full envelope copy, which carries the record body and its `salts` array together (specification section 7.3).
`schemas/conformance-corpus-1.0.json` expresses that as a two-branch `oneOf` on `recordVector` rather than as advice, and the second branch forbids a salts file alongside an envelope so the two carriers cannot disagree about which set the asserted root was computed under.

**Why this is structural now and was not before.**
Under the deleted D4a construction a bare record file plus a `masterSaltHex` and the record identifier was enough to re-derive every salt, so carrying them was optional.
Decision D4 is ruled D4b and every salt is an independent random draw that nothing can re-derive (specification section 7), so a vector naming only a bare record file asserts a root no runner can recompute: schema-valid, and vacuous, in the class this document calls mandatory.

#### Why this class pairs its salts positionally, and every other carrier pairs by path

**Read this before making the two consistent, because the consistent-looking direction is the unsafe one.**

A salt set names a salt for each leaf, and there are two ways to say which salt belongs to which leaf.
Every hand-authored fixture in this corpus, and every envelope, pairs **by path**: each entry carries explicit path segments, exactly as the `salts` array of `schemas/envelope-1.0.json` is defined.
The class-10 vectors pair **positionally**: a bare array of salts in `encodePath` order.
`recordVector.saltPairing` names which shape a vector uses, and it is required rather than inferred, because the two are not distinguishable by inspection and a runner that guesses wrong computes a wrong root instead of reporting an error.

**Specification section 7.2 rejects positional pairing for an envelope**, and the reason is precise: it makes salt-to-leaf pairing depend on the reader reproducing the section 9 sort correctly before it can read the salts at all.
In production that is a hazard, because a sort that is subtly wrong yields a wrong root rather than a complaint.

**In a corpus vector, reproducing that sort is the thing under test.**
The property that makes positional pairing dangerous in an envelope is exactly what makes it valid here: an implementation whose sort disagrees mispairs the salts and fails the vector, which is the detection the class exists to provide rather than a defect it introduces.

**Why this class needs it at all**, stated so the tradeoff is not mistaken for an optimization.
The class-10 records are the genuine third-party MOH reference samples, at 69 and 70 leaves.
A path-keyed salt set for one of them would enumerate every path of a shipped reference sample into this repository, which is public, and `AGENTS.md` forbids committing the reference schemata - not even a fragment.
A positional array discloses only the leaf count, and `leafCount` is already published in the same vector, so it adds nothing a reader did not already have.

> **If these two are ever harmonized, the dangerous direction is making envelopes positional.**
> That would move the sort dependency from a test, where it is the subject, into a deployed record, where specification section 7.2 rules it out.
> Harmonizing the other way - making class 10 path-keyed - is merely forbidden by the references policy.
> Neither is an improvement.

This is the second consequence of the D4b ruling that the ruling itself did not work through; the first was `roax.recordId` moving from mandatory-by-arithmetic to mandatory-by-policy in the minimum-disclosure floor (specification sections 10.2 and 11.2).
Both are recorded rather than absorbed, because a reader who finds one unexplained will not trust the other.

### Class 11 - the schema binding itself

The type map is a data file and MUST be in the corpus, with vectors asserting that a given structured path and observed JSON kind under a given map yield a given tag, and that an uncovered path-kind pair fails closed, as required by specification section 4.2.
Each vector MUST name the exact content ID, semver, `recordType`, opaque `schemaVersion` and `jsonKind` of the artifact lookup under test, as required by specification section 4.2.

This is the highest-risk surface in the design (specification section 4) and also the easiest to diff, which is the one piece of good news about it.

At minimum the fail-closed rows MUST cover PDT `$template.name`, FHIR `Narrative.div`, FHIR `base64Binary`, and an unknown empty array and empty object, because `docs/type-maps.md` sections 1 and 3 record those as the reachable places where a proposal or mechanically known empty-container tag could otherwise be mistaken for an operative binding.
The two FHIR entries stay on that list after being ruled on 2026-07-30, because neither the published artifacts nor the corpus-side profile maps carry those bindings; their tag semantics are pinned over the synthetic profile instead (`docs/type-maps.md` section 1.6).

**Vaccination `dose` and `expiryDateTime` were on that list until the same date, and the ruling inverted the requirement for them.**
The rows now assert the ruled tags, INTEGER and STRING, because the corpus-side vaccination map binds both (`docs/type-maps.md` section 1.1).
What stays fail-closed there is `dose` at a kind the ruling does not bind, which is what keeps one ruled `(pattern, kind)` binding from reading as permission for every kind.

**One row was added when decision D9 was ruled:** a type map binding any path to **tag 8 `BLOB_REF`** MUST be **rejected**, because the content-addressed binding is defined and selected by no version-1 profile (specification section 6.5).
That is a rejection of the map rather than a fail-closed on a path, so it is a third outcome and both corpus schemas give it its own `oneOf` branch.
Without this vector, "registered but unselected" is a sentence, and the schemas accept tag 8 in order to pin its carrier form - which is exactly the combination that lets an implementation quietly honour a binding no profile has declared.

### Class 12 - cross-record unlinkability under independent per-leaf salts

**Two records for the same subject, sharing a path and a value at that path, MUST produce different leaf hashes for that path.**
**And within a single record, no two leaves may share a salt**, which specification section 7 states as its own MUST rather than as a consequence of the first: an implementation MUST draw each salt independently and MUST NOT reuse one across leaves.
Both halves are asserted here, because the second is not observable anywhere else in this document.

This class kept its number and its subject when decision D4 was ruled D4b and lost its mechanism.
The old version built the two records with two different `masterSalt` values and asserted the same outcome.
There is no master salt now (specification section 7), so the assertion is made directly against the property that matters, which is what the old version was proxying for anyway.

**It is the only class that catches an implementation whose salts are not independent**, and that violation is invisible to every other class in this list because each record verifies perfectly on its own.
The reachable ways to get it wrong are worth naming, because the class has to catch all three:

- **A deterministic salt.**
  Deriving a salt from the path, from the value, or from a content-derived seed, so that reissuing a record reproduces the same root.
  This reads like a feature - "reissuance is idempotent" - which is exactly why the specification forbids it in section 7 and why a vector rather than a sentence enforces it.
  *Caught by `expectDistinctSaltsAcrossIssuances`.*
- **A salt reused across leaves.**
  One draw per record rather than one per leaf.
  *Caught by `expectDistinctSaltsWithinIssuance`, and by nothing else in this document.*
- **A salt reused across records**, which is the patient-linkage failure itself.
  *Caught by `expectDistinctSaltsAcrossIssuances` and by `expectDistinctLeafHashesAcrossIssuances`.*

#### The shape this class has to take, and its honest limit

**This class asserts a relation between generated values rather than a pinned expected value**, and that is forced by the ruling rather than a shortcut.
Under D4b the salts are independently random, so no fixed hexadecimal expectation can exist: a vector file cannot pin what the implementation under test is required to draw freshly.
An `unlinkabilityVector` therefore describes an issuance to perform and the relations the results MUST satisfy.

**The vector carries at least two DISTINCT paths, and that is what makes the second mistake reachable.**
It names a `paths` array, one `tag` and one `value`, and each of its `trials` independent issuances emits a leaf at every one of those paths carrying that same tag and value.
The runner then asserts three things:

**The record and the type map this class issues against are SYNTHETIC, and the corpus build constructs both.**
No referenced MOH sample is involved, and none could be: the class needs one value carried at two paths, and a tag is a property of a path under a type map rather than of a vector, with an uncovered path failing closed (specification section 4.2, decision D7 ruled D7a).
So the build binds every entry in `paths` to the vector's `tag` in a map it makes for the purpose, and MUST reject a vector it cannot construct one for.
This is stated because the one tag shared by two paths is otherwise a claim the vector file cannot make good on by itself.

1. **Within each issuance**, the salts at the `paths` entries are all distinct.
   This is the only assertion in this document that fails an implementation drawing one salt per record and reusing it across that record's leaves.
   A one-path vector cannot see that mistake at all: the single salt still differs from trial to trial, so both cross-issuance assertions pass while the unlinkability property specification section 7 requires has been destroyed.
2. **At each path across issuances**, the salt drawn in every trial differs from the salt drawn at that path in every other trial.
3. **At each path across issuances**, the leaf hash differs likewise.

**There is deliberately no within-issuance leaf-hash assertion.**
Two leaves at different paths carry different encoded paths inside the leaf preimage (specification section 8), so their hashes differ whether or not their salts do, and asserting it would read as coverage it is not.
The salts are where the property is observable within one record, which is why assertion 1 is stated on salts alone.

**The distinctness of `paths` is enforced by the schema, not asked for in prose, because assertion 1 is the only guard of its kind in this corpus.**
Two entries naming the same path would have it assert distinctness over a path a record can hold only once, which switches the guard off while the vector still validates, and a guard a malformed vector can disable is not a guard.
`schemas/conformance-corpus-1.0.json` uses `uniqueItems` on `paths`, and that is exact rather than partial here: the array's items are the structured segment lists themselves, and two paths are equal exactly when their segment sequences are equal (specification section 5.1).
One tag and one value are shared by every path for the same reason - it is what lets the entries be bare segment lists that `uniqueItems` can compare - and it makes the vector strictly stronger, because two leaves carrying the same tag and value at different paths additionally expose a salt derived from record content, which per-path values would mask.

**One residue the corpus build must enforce in code**, stated rather than left for a reader to find: two keys differing only in Unicode normalization form are unequal as JSON text and equal as paths once NFC is applied (specification section 6.1), so the build MUST compare NFC-normalized segments and reject such a pair.
That is the same kind of check the build already owns for class coverage.

> **The limit, stated rather than left for a reader to discover.**
> This detects a **deterministic** or **reused** salt, which is the failure that has actually happened in comparable systems.
> It does **not** detect a weak or predictable CSPRNG: an implementation drawing 16 bytes from a poorly seeded generator passes every trial while providing much less than the 128 bits specification section 7 requires.
> No fixed vector file can test a randomness source.
> That gap belongs to implementation review, and this document states it here rather than letting a passing class read as a guarantee it is not.

This class follows the same convention as classes 15 and 16, which say outright where they detect a property by declaration rather than by demonstration.

### Class 13 - reference-schema hazards

- Loading the PDT and recovery schemas together and asserting that recovery's rules still apply, despite recovery's `$id` pointing at PDT's path.
  See [`docs/profiles/recovery-healthcert.md`](profiles/recovery-healthcert.md) section 2.
- The vaccination flattened `entry[]` layout committing as-is, with a companion vector proving that the normalized layout produces a **different** root.
  See [`docs/profiles/vaccination-healthcert.md`](profiles/vaccination-healthcert.md) section 2.1.

### Class 14 - minimum-disclosure floor

For each profile, a disclosed copy omitting each declared non-redactable path in turn, each of which MUST be rejected - plus one that includes them all and is accepted.

**The floor is the five reserved paths specification section 11.2 marks mandatory to disclose**, including `roax.typeMap.id`, plus whatever the profile adds on top.

**`roax.typeMap.id` joins a copy's floor as a CONSEQUENCE of the section 4.2 binding rather than unconditionally**, and the difference is what lets this class carry both generations at once.
The 54 fixtures that predate the binding commit four or five reserved leaves and name no type map on either side, so demanding the path of every copy would fail 34 vectors that are correct.
A separate `typemap-floor-<profile>-*` family carries the outer member AND commits the leaf, one pair per profile, and its omit row asserts `outer-identity-mismatch` for the same reason the other reserved omissions do: the binding fires before any floor is selected.
This class MUST carry a vector proving where its upper edge is: a disclosed copy that **omits `roax.issuer.keyId` MUST be ACCEPTED** when the record committed one.
That path is committed inside the root but OPTIONAL to disclose, because requiring it would permanently bind an anchored record to the key it was issued under and leave no rotation path, which specification section 12.2 rules out.
Without that vector, an implementation that over-tightens the floor to every reserved path passes this class while breaking key rotation, and nothing else in the corpus would catch it.

JSON Schema cannot express any of this, so it is enforced in code and can only be pinned here.
See specification sections 10.2 and 11.2.

### Class 15 - reserved-namespace guard

A record-supplied path is rejected when its **first segment** is a `KEY` whose **NFC-normalized** key begins with the ASCII prefix `roax.` (specification section 11.2).
Reserved paths are **single segments carrying the literal dotted name**, so this is a test on one key's own characters, not on a rendered display path and not on a sequence of segments.

| Vector, as segments | Expected | Why |
|---|---|---|
| `[KEY("roax.recordId")]` | **Reject** | It *is* a reserved path. A direct collision. |
| `[KEY("roax.anythingElse")]` | **Reject** | The guard is on the `roax.` prefix within the first key, not on the exact reserved names, so a future reserved leaf cannot be squatted before it is defined. |
| `[KEY("roax")]` | **Accept** | An ordinary record field. No reserved path is the bare segment `KEY("roax")`, so it collides with nothing. |
| `[KEY("roaxX"), KEY("foo")]` | **Accept** | A different key entirely. |
| `[KEY("a"), KEY("roax.foo")]` | **Accept** | The guard applies to the FIRST segment only. This path differs from every reserved path in segment count and cannot collide with one. |
| `[KEY("Kelvin")]`, which NFC-normalizes to `Kelvin` | **Accept** | A first-segment key that changes under NFC and still does not begin with `roax.`. Pins that the guard normalizes and then compares, rather than over-rejecting anything non-ASCII. |

**Four of these assert acceptance, and that is the point of the class.**
A corpus containing only rejection vectors is passed by an implementation that over-rejects, and over-rejection is the more likely failure here: it is what a guard written against a display path, or applied to every segment instead of the first, actually does.

**This class was rewritten, and the earlier version was wrong in a way worth recording.**
It required rejecting the bare namespace `roax` and the adjacent squat `roaxX`.
Both are ordinary record keys under the single-segment reserved-path model of specification section 11.2, and rejecting them is over-broad: it would refuse a legitimate record for using a field name that collides with nothing.
That class had been written for a string-path model this specification deliberately departed from, and it survived the departure because nobody re-derived it.

**The NFC case, stated honestly about its own limit.**
An earlier version of this class carried a row reading "a key that NFC-normalizes into the reserved prefix, MUST be rejected".
**No such key exists, so that row promised a vector nobody could build.**
Scanning every assigned code point on Node v22.21.0 finds no non-ASCII character whose NFC form contains `r`, `o`, `a`, `x` or `.`; the only ASCII letter reachable that way at all is uppercase `K`, from U+212A KELVIN SIGN, which is not in `roax.`.

So specification section 11.2's MUST that the guard compare the **normalized** key is currently **unobservable at the guard**: for every input a record can supply, checking before or after normalization gives the same verdict.
Section 11.2 states that limit in the same terms and explains why the rule stands regardless, which is that it is a fact about today's prefix characters rather than about the design.

That is why the row above tests what can actually be demonstrated instead.
`[KEY("Kelvin")]`, whose first key is `U+212A` followed by `elvin`, is a real key that changes under NFC, and it MUST be **accepted**, because its normalized form does not begin with `roax.`.
It catches the failure that is reachable today, which is a guard that over-rejects anything non-ASCII rather than one that under-rejects a crafted collision.

**The demonstrable half of the normalization requirement is class 4**, which already carries NFC versus NFD in keys and asserts that the hashing path normalizes.
This class does not restate it.

U+212A appears in specification section 11.2 as evidence that NFC can cross into ASCII, and it must not be read there or here as an instance of a key that normalizes into the reserved prefix.
This class follows the same convention as class 16, which says outright when it detects a property by declaration rather than by demonstration.

dogtag's own record of the prefix-versus-exact-match change is at `crates/dogtag-standard-rs/src/profile_tree.rs:54-66`.
What transfers is the argument, not the string operation; specification section 11.2 states that distinction.

### Class 16 - Unicode version sensitivity (new, and honest about its limits)

`ROAX-CANON/1` pins Unicode 15.1 (specification section 6.1).
NFC is version-dependent, so an implementation whose tables come from a different Unicode version may legitimately differ.

This class carries strings whose NFC form is stable across recent Unicode versions, plus a marker vector recording which Unicode version produced the expected values, so that a mismatch surfaces as "your ICU is version X" rather than as an unexplained hash difference.

**Stated at the strength of the evidence:** the need for the pin is inferred from dogtag having found it necessary in code (`crates/dogtag-standard-rs/src/encode.rs:6-7`).
No specific character whose NFC changed between Unicode versions has been identified and confirmed for this corpus.
Doing so is outstanding work, and until it is done this class detects version *mismatch* by declaration rather than by demonstration.

### Class 17 - a disclosed copy MUST NOT leak a withheld leaf's salt

A disclosed copy carries the salt of every leaf it reveals and the salt of **no other leaf** (specification sections 10 and 10.1).

| Vector | Expected |
|---|---|
| A disclosed copy carrying exactly the salts of its revealed leaves | **Accept** |
| The same copy with one withheld leaf's salt added | **Reject** |
| A disclosed copy carrying a `salts` array, the full-copy field | **Reject** |
| A disclosed copy whose `salts` member is present but is **not an array** | **Reject** |
| A disclosed copy carrying any seed field, `masterSalt` or otherwise | **Reject** |
| A full copy whose `salts` array omits one leaf of the union | **Reject** |
| A full copy whose `salts` array length does not equal `leafCount` | **Reject** |

**The wrong-typed row is about the TRIGGER rather than about the value.**
The guard above asks whether `salts` is present, so an implementation that reads a present-but-wrong-typed member as ABSENT has switched its own salt-leak guard off from outside: `"salts": {}` never trips the check and the copy verifies while carrying it.
**A guard that turns itself off on malformed input is worse than no guard, because it reports safety it is not providing.**
The shape is general and this row is the cheap instance of it - the same reading applied to `typeMap` switches off the section 4.2 binding, and applied to `record` or `disclosure` it changes which copy kind a verifier thinks it has.
`schemas/envelope-1.0.json` types every one of those members, so the schema rejects this document too, and both halves are worth having: a schema validator is not what runs inside a verifier.

**The seed row survives decision D4's ruling on purpose.**
There is no `masterSalt` in this design any more (specification section 7), and `additionalProperties: false` already rejects an unknown field, so the row is cheap.
It is retained because specification section 7.3 rule 3 binds any future revision that reintroduces a derived salt, and a revision that added a seed to the envelope would hand every holder the ability to recompute every withheld leaf's salt in a copy that still verified.

**This class exists because the violation verifies correctly.**
Extra salts do not change any leaf hash, so an implementation that ships every salt in a disclosed copy produces an envelope that passes the root check, passes the inclusion proofs and passes every other class in this list, while leaking every withheld field to a dictionary search.
There is no failing assertion anywhere else to catch it.

`schemas/envelope-2.0.json` closes most of this structurally by forbidding `salts` alongside `disclosure`, which leaves no place to put a withheld leaf's salt.
The rows this class still has to carry in code are the count relationships in the last two rows, which JSON Schema cannot express because they relate `salts.length`, `leafCount` and the actual leaf set to each other.

### Class 18 - outside-the-root fields are never authority

**This class exists because a normative sentence was demonstrably not enough.**
Specification section 11.3 states that fields outside the root are hints and never authority.
dogtag had the equivalent understanding written down and still shipped the `documentStore` bug, then needed an entire extra mandatory issuer-whitelist pillar that exists only to compensate (`AGENTS.md:333` in the dogtag monorepo).
An implementer who agrees with the sentence and then reads the convenient field anyway is the failure mode, so the corpus has to fail that implementation rather than trust it.

Every vector here **fails an implementation that trusts an outside-the-root field**, and passes one that takes authority from the root and from its own configured anchoring layer.

| Vector | Expected | What it catches |
|---|---|---|
| A disclosed copy whose top-level `recordType` disagrees with the disclosed `roax.recordType` leaf | **Reject** | A verifier that reads the envelope field instead of the committed leaf. The leaf is inside the root; the field is not. |
| The same, for `schemaVersion`, `recordId` and `issuer.id` in turn | **Reject** | The same mistake at the other profile and identity floor paths (specification section 11.2). |
| A top-level `typeMap.id` that disagrees with the disclosed `roax.typeMap.id` leaf | **Reject before resolving a record leaf** | A verifier selecting a convenient map from the discovery hint instead of the ID committed inside the root (specification sections 4.2, 10 and 11.2). |
| The outer `typeMap` member **deleted** while the root still commits `roax.typeMap.id` | **Reject** | A verifier that gates the binding on that member never runs it. The member is supplied by the HOLDER, so gating there hands the trigger to the party the check constrains. |
| Candidate type-map bytes whose content ID does not reproduce the committed `roax.typeMap.id`, including a second artifact with the same semver | **Reject** | A verifier selecting by version or locator rather than the exact immutable artifact ID (specification section 4.2 and [`type-maps.md`](type-maps.md) section 4). |
| An envelope whose `hashAlg` disagrees with the `(root, hashAlg)` pair the verifier's anchoring registry records | **Reject** | A verifier taking the algorithm from the document rather than from the registry. This is exactly what specification section 7.4's H2 requires and what H1 does **not** provide. |
| A `SHA-256` envelope whose `(root, hashAlg)` pair the registry records correctly, verified against a configured allow-list of `["Poseidon-BN254"]` | **Reject** | The retired-algorithm case, which H2 alone does not close. Specification section 7.4, H3. |
| An envelope whose `anchor.registry` and `anchor.chainId` name a registry the verifier is not configured with, and which would return a valid pair | **Reject, without reading that registry** | The dogtag `documentStore` bug in this design's shape: an attacker-supplied address that answers "valid". A verifier MUST resolve the anchoring layer from its own configuration. |
| A well-formed envelope whose `anchor` block is absent entirely, verified against the verifier's own registry | **Accept** | The upper edge. `anchor` is a routing hint, so its absence MUST NOT make a verifiable record unverifiable, and an implementation that hard-requires it has made the field authority in a different way. |

**The allow-list row has to name `SHA-256` as the excluded algorithm, and the earlier phrasing did not.**
It read "an envelope whose `hashAlg` is absent from the allow-list, and present in the registry", which with only two registered values fits a `Poseidon-BN254` envelope alone.
Such an envelope is rejected regardless, for having no defined construction (specification section 7.4), so the vector would record a pass against an implementation that has no allow-list at all.
The discriminating shape is the one the table now states: an algorithm the implementation would otherwise accept, excluded by configuration.

**The last row is the reason this class cannot be only rejections.**
A corpus of rejections alone is passed by an implementation that rejects everything with an `anchor` mismatch including the case where nothing is wrong, and treating a routing hint as required is itself a way of depending on it.

**What a runner needs that no other class needs.**
The registry rows are the only vectors whose outcome depends on what the *verifier* is configured with rather than only on the envelope, so `envelopeVector` carries a `verifierConfig` block stating the anchored `(root, hashAlg)` pair, the allow-list and the configured registry.
`schemas/conformance-corpus-1.0.json` permits that block at class 18 and **forbids** it at every other class, and requires all four members when it is present rather than any subset, so a partial block cannot let a vector pass or fail for a reason the file did not fix.

**Whether a class-18 vector needs the block is a stated limit, not a structural rule.**
It is required for a vector whose outcome turns on verifier configuration and inapplicable to one the envelope alone determines, and no JSON Schema keyword can tell those apart.
The corpus build owns that check.
An earlier revision required the block on *every* class-18 vector, written when this class was expected to be the registry rows alone; it rejected the committed corpus the moment the identity rows arrived, which is how the over-tightening was found.

**The rule the last two rows share, stated because it is the general one and it recurs:**

> **A check whose execution is controlled by the party it constrains is not a check.**
> The trigger must come from what is COMMITTED, never from what was PRESENTED.

`roax.typeMap.id` is the case that made it concrete.
It is mandatory to disclose **by arithmetic** (specification section 11.2), because it selects and authenticates the exact map, so withholding it yields no proof of which map applies rather than a weaker one.
The outer `typeMap` member is optional under `schemas/envelope-1.0.json`, which makes "bind when the member is present" the obvious reading and the wrong one: a holder deletes the member, withholds the leaf, and the binding never runs while every remaining inclusion proof stays genuine.
The binding therefore fires whenever **either** side names a type map, and absence on one side is the same rejection as disagreement.

**The one case no envelope can evidence, named rather than left as a silent limit.**
A copy that drops BOTH the member and the leaf is byte-indistinguishable from a legitimate envelope-1.0 copy issued before the section 4.2 binding existed: the only signal that a further reserved leaf was ever committed is `leafCount`, which specification section 11.1 measured is NOT authenticated in a disclosed copy, so a check leaning on it would reintroduce the forged-size attack that section corrects.
It needs no vector of its own, because **the 34 committed floor fixtures already are that shape**: an implementation that hard-rejects a copy lacking a type map fails class 14 today.
What closes the case is `schemas/envelope-2.0.json` REQUIRING the member, and a verifier that accepts only 2.0 records selecting that policy for itself.

#### What is built, and the named gap

**Built: the four identity rows, plus the two type-map binding rows.**
A disclosed copy whose top-level `recordType`, `schemaVersion`, `recordId` or `issuer.id` disagrees with the reserved leaf committed inside the root is rejected, with every inclusion proof still verifying against the genuine root.
Their **reject** verdict is determined by the envelope alone, since the field and the committed leaf disagree with each other, so they carry no `verifierConfig`.
These four carried class 14 until the D8 ruling created this class; they were always this assertion, and the floor class is about a disclosed copy *omitting* a non-redactable path, which is a different property.

> **NAMED GAP, blocked rather than merely unwritten: the registry rows.**
> The `hashAlg`-from-registry row, the substituted-`anchor.registry` row and the absent-`anchor` accept row are **not built**, and the blocker is a dependency rather than effort.
> This corpus models no anchoring registry, because **specification section 2.2 deliberately leaves the anchoring registry undesigned** and hands it forward as a stated requirement on that future work.
> Building these vectors would make the corpus invent that interface, which section 1.2 of this document forbids outright: the corpus may not require what the design has not decided.
> That rule has already been broken twice in this project, both times over `masterSalt`, which is why it is not being broken a third time for a class this project's own ruling mandated.
>
> **These rows become buildable the moment the anchoring registry is designed, and not before.**
> Until then the H2 and H3 bindings of specification section 7.4 rest on the normative text alone, and this paragraph is the record that they do.

### Class 19 - NFC normalization, end to end, with a root

`ROAX-CANON/1` normalizes strings and object keys to NFC before encoding, under Unicode 15.1 (specification section 6.1, decision D12 ruled D12a).

**This class carries a record whose string differs before and after NFC, in both forms, and asserts they produce the same root.**

| Vector | Expected |
|---|---|
| A record carrying the NFD form of a string that changes under NFC | root `R` |
| The identical record carrying that string's NFC form | **the same root `R`** |
| The same pair with the differing sequence in an **object key** rather than a value | one root, equal across both forms |

Use a string whose NFC form is stable across recent Unicode versions, so that this class tests normalization rather than the version pin; class 16 owns the version question and is honest about what it can and cannot demonstrate.

**The key-site row was deliberately NOT built until decision D14 was ruled, and it is built now.**
A key-site vector has to resolve its key through the type map, and whether that lookup normalized was an open question: the specification pinned NFC for hashing and said nothing about the lookup, so both reference implementations compared a pattern token against a segment key raw (`corpus/README.md`, ambiguity 4).
A vector built then would have passed under one reading and failed under the other, which settles a decision from inside a data file rather than testing a settled one, and section 1.2 forbids exactly that.
**D14 was ruled D14a on 2026-07-30**, normalize, so the vector now tests a decided question.

The corpus carries both sites, and `corpus/tools/build_corpus.py` fails the build if either is missing, which is the check this table's requirement could not have before.
The key vector's map declares the composed spelling alone, so it discriminates: under raw matching the decomposed half fails closed with `type-map-uncovered-path` and the equality assertion is unreachable.
`corpus/README.md` records that measurement and the second discriminator the ruling produced.

**Both forms MUST be computed under one shared salt set, and the vector MUST name the file carrying it.**
Under decision D4b every salt is an independent random draw (specification section 7), so two issuances of the two forms produce different roots for a reason that has nothing to do with normalization, and the equality assertion would then hold nothing.
`schemas/conformance-corpus-1.0.json` requires `saltsFile` on `normalizationVector` for that reason, the same way `recordVector` requires a salt carrier for class 10.

**Why this is not covered by class 4.**
Class 4 asserts NFC against NFD at **leaf** level, in values and in keys.
That catches an implementation whose `encodeValue` skips normalization.
It does not catch one that normalizes in `encodeValue` and then reaches the same string by another route - a key compared before normalization, a reserved-leaf value written straight from the envelope, a path segment re-encoded from a cached form.
Class 19 asserts the property of the whole pipeline, over the union of section 3.3, which is where those routes actually are.

**The assertion is equality, so the class is complete without a pinned hexadecimal root.**
The value of `R` is whatever the corpus build computes; what the vector fixes is that both forms produce one value and that it is the same one.
A pinned `R` is worth adding once the corpus file exists, as a regression against the normalization silently changing, and the vector shape has room for it.

### Class 20 - the issue-then-verify round trip

**Every class above runs an implementation's VERIFIER against bytes another program wrote.**
Every committed envelope fixture is produced by `corpus/tools/build_corpus.py`, so until this class existed nothing asked an implementation to PRODUCE an envelope.
An implementation could therefore issue a disclosed copy that its own verifier refused and pass every vector in the file.

**That is not hypothetical, and the corpus did not find it.**
One library emitted every revealed leaf with no `value` member, so it issued disclosures its own verifier rejected for `disclosed-leaf-named-without-value` - a condition class 17 names in a committed vector - while passing all 488 vectors.
A human reading the library found it.
`swift/FINDINGS.md` finding 10 records the measurement and says outright that closing it is a corpus change rather than a library one.

**What makes the producing side worth a class rather than obvious** is that the disclosure carriers are PER TAG and are not the record's own spellings.
NULL, EMPTY_ARRAY and EMPTY_OBJECT carry no `value` member at all; BOOL carries a JSON boolean; INTEGER and DECIMAL carry STRINGS already in the section 6.2 canonical output form; and BYTES carries lowercase HEX where the record spelled base64.
Four ways to get one wrong, and none of them reachable from a vector that only verifies.

A vector names a record, a committed salt set, a set of paths to disclose, and the two envelopes a conforming implementation produces from them.
A runner MUST:

1. issue a full copy from the record and that salt set, and check its `leafCount` and `root`;
2. compare the full copy it produced against `expectedFullCopyFile`;
3. derive a disclosed copy revealing exactly `disclosePaths` from the SAME commitment, and compare it against `expectedDisclosedCopyFile`;
4. verify BOTH copies it produced through its OWN verifier, and require acceptance.

**Step 4 is the assertion the class exists for and steps 2 and 3 are what stop it being reflexive.**
A vector asserting only "my verifier accepts my output" is self-consistency, and a lax verifier passes it while producing the same malformed copy.
The static class 17 row fails the lax VERIFIER; this class fails the lax PRODUCER.
Neither closes the gap alone.

**The comparison is SEMANTIC and not byte-for-byte**, because JSON member order, whether `displayPath` is emitted, the order of the `disclosure.leaves` array and the order of a full copy's `salts` array are not fixed by the specification, and asserting any of them would fail a conforming implementation for something this document does not require.
`disclosure.leaves` and `salts` are both compared as SETS keyed by what their entries carry - the leaf index and the structured path - rather than in the order a producer emitted them, and `displayPath` is dropped from the comparison on both sides, because `schemas/envelope-1.0.json` leaves it out of `disclosedLeaf.required` and it is display only in any case (specification section 5.2).
Nothing else is relaxed, and the half that stays exact is the half that matters: both array LENGTHS, every leaf's segments, index, tag, value carrier, salt and audit path, and every scalar identity field, so a producer that omitted a per-leaf value carrier still fails.
What must survive intact is every number's SOURCE TEXT: the full copy carries the record's literals, and a runner that rebuilds that envelope through a float-based serializer destroys exactly what the root was computed from (specification sections 6.4 and 7.3).

**Pinned rather than behavioural, unlike class 12.**
Class 12 must draw its own randomness because it is ABOUT randomness.
Nothing here is, so the salt set is a committed input and both produced envelopes are fixed - which is what lets this class fail an implementation on its own rather than only in company with class 17.

**Every vector in this class commits `roax.typeMap.id`, and that is a constraint rather than a choice.**
Specification section 11.2 marks that leaf emitted ALWAYS, so an ISSUANCE without one is not something the current specification permits; `schemas/envelope-1.0.json` keeps the member optional for envelopes ALREADY issued under it, which is what the other fixtures are.
A vector without one would ask an implementation to produce an envelope the specification forbids it to produce.

**EMPTY_ARRAY and EMPTY_OBJECT are deliberately absent from the round-trip record.**
NULL already covers the no-value carrier, so their tags add no form the record does not reach, while the committed corpus emits them without consulting the type map - the reading specification section 3.3 does not take.
`python/FINDINGS.md` item 1, `swift/FINDINGS.md` finding 8 and `docs/typescript-implementation-findings.md` all measure that cost at exactly two class-5 vectors, and putting an empty container here would raise a number three findings documents state.

**What this class found the day it was built, and it is worth more than either defect it was written for.**
Two shipped libraries held mutually exclusive issuance rules: the TypeScript library refused to issue an envelope WITHOUT `roax.typeMap.id`, and the Python library refused to issue one WITH it.
Both passed all 488 vectors.
No verifying-side vector could have found that, because neither library was ever asked to produce anything.
Section 11.2 settles it - the leaf is emitted always - and the Python refusal was narrowed to what it actually needed, which is artifact resolution and not issuance.

## 4. Seed material that already exists

The canonicalization research built a 26-leaf adversarial corpus covering classes 1, 2, 4, 5, 6 and 7, and ran it through five implementations to identical roots.
Its discrimination checks all pass:

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
   That is adequate for a fixed corpus where the tags are pinned by the vector file, and it MUST NOT ship in a library.
2. Those implementations are ~250-350 lines each, with no error taxonomy, no streaming and no schema binding.
   They are specification aids, not libraries.

Classes 3, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18 and 19 are not covered by that seed and are new work.

The one partial exception is the pair class 1 delegates to class 7, `1e2` as DECIMAL against `100` as INTEGER, which the seed already discriminates - see the fourth line of the block above.

## 5. Appendix - the JCS demonstration script

Specification section 13.1 disqualifies JCS on a demonstrated collision rather than an opinion.
This is the script, so a reader can check rather than trust.
Run with Node >= 21.

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

This script belongs in the corpus repository as a standing regression, because the argument it supports is the load-bearing one for the whole design.
