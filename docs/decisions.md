# Decisions: settled, open, and the reasoning

**Status:** three decisions are genuinely open.
Two are in Part 1 and belong to the project owner - **A** and **C**.
The third, **D14**, was identified on 2026-07-29 while building a conformance vector and is in Part 2a; it is open because nobody has ruled it, not because it is awaiting the owner specifically.
Everything else has been ruled.
**Decision B** was ruled earlier, with the residual open questions named inside it.
**Decision D** was ruled Da on 2026-07-29: five independent, corpus-enforced libraries.
The **ten engineering decisions in Part 2 - D3, D4, D5, D6, D7, D8, D9, D11, D12 and D13 - were ruled on 2026-07-28**, and each carries its reasoning so that it can be overturned on the reasoning rather than on authority.

Eight of those ten confirmed what the specification already recommended.
Two changed it: **D4** moved to D4b, independently random per-leaf salts, and **D9** gained a content-addressed blob binding that is defined but selected by no version-1 profile.

The protocol specification is **written on the recommended answer to each decision that is still open**, so that it is concrete and readable rather than hedged into uselessness.
That is a drafting choice, not a ruling.
A specification that hides a live decision behind confident prose is worse than one that names it, so each is named here with its alternatives and their consequences.

`docs/conformance-corpus.md` class 19 records the vector that would settle D14 and states why it is deliberately not built.

**A decision that looks settled in the specification but is still marked OPEN here is worse than either**, so the two documents move together in one change.
That warning is in this document because it has already been a problem.

## Numbering

The design research numbered its forks D1 through D10.
Three were renumbered here so that the four decisions named by the project owner keep the letters used there.
The rest kept their numbers.

| Here | Design research | Topic |
|---|---|---|
| **S1** (settled) | D1 | Canonical form |
| **B** | D2 | Hash function |
| **D** | D10 | Independent libraries versus a shared core |
| D3 - D9 | D3 - D9 | Unchanged |
| D11, D12, D13 | new | Detached signature; normalization; clinical validation level |

`D10` therefore does not appear below; it is **Decision B**'s sibling, listed as **Decision D**.

---

## Part 0 - The load-bearing finding

Everything else in this document sits on one result, so it is stated first and separately.

### The JavaScript number model is unfit for FHIR, established twice independently

Two research legs reached this from **different directions**, using different evidence, without sharing a method.
That independence is the argument; either alone would be weaker.

**Source 1 - from the specification text, forward.**
FHIR R4 says of `decimal`: "The precision of the decimal value has significance: e.g. 0.010 is regarded as different to 0.01, and the original precision should be preserved", and "Implementations **SHALL** handle decimal values in ways that preserve and respect the precision of the value as represented for presentation purposes" (<https://hl7.org/fhir/R4/datatypes.html>).

RFC 8785 (JCS) section 3.2.2.3 mandates serialization "according to Section 7.1.12.1 of [ECMA-262]", which is ECMAScript `Number::toString` over an IEEE-754 double.
Running that on FHIR-legal decimals collapses `0.010` and `0.01` to the same string, and silently corrupts `9223372036854775807` into `9223372036854776000`.

**Source 2 - from the OpenAttestation source, backward.**
The OpenAttestation audit reached the same conclusion by reading what the deployed system actually does.
Its salting step computes `` `${typeof value}:${String(value)}` ``, so the loss happens before any serialization.
Reproduced against the pinned source at OA `v6.9.7`:

```
JSON.parse("9007199254740993")                         = 9007199254740992
JSON.parse("9007199254740993") === JSON.parse("9007199254740992") = true
typed JSON.parse("1") === typed JSON.parse("1.0")      = true
1e21 -> number:1e+21        1e20 -> number:100000000000000000000
NaN  -> number:NaN          Infinity -> number:Infinity
```

The audit states the consequence plainly: FHIR R4 defines separate integer and decimal primitives with decimal precision significant in exchange, and "they should not be silently collapsed into one JavaScript number domain."

**Why the independence matters.**
Source 1 could be dismissed as a specification-lawyer reading of a `SHALL` that nobody enforces.
Source 2 could be dismissed as an implementation defect that a careful port would avoid.
Together they are neither: the standard forbids it, and the deployed system does it anyway, because the language model makes it the path of least resistance.

**This is the justification for the entire design.**
It is why ROAX carries numbers as arbitrary-precision strings and never parses them through a float (specification section 6.2), why implementations MUST NOT use a floating-point type at the parse boundary (section 6.4), and why JCS is disqualified rather than merely disfavoured (section 13.1).

**Reproduced while writing this documentation set**, on Node v22.21.0, from the source-1 direction.
The script and its output are in [`conformance-corpus.md`](conformance-corpus.md) section 5.
The source-2 reproductions are carried from the audit and were not independently re-run.

---

## Part 1 - The four decisions that belong to the project owner

Two of them - A and C - have not been ruled on.
**B and D have been ruled**, and are kept here rather than moved to Part 3 because the option records and their reasoning belong with the other owner decisions.

### Decision A - Does roax-lib need EU recognition? **OPEN**

**Written into the spec:** nothing.
The specification takes no position and defines no export profile.

| Option | Consequence |
|---|---|
| **A1. No EU recognition sought** | Simplest. ROAX stays a commitment-and-anchoring protocol with its own disclosure model. Cost: outside the EU public-sector acceptance path, permanently. |
| **A2. Profile SD-JWT VC as an export format** | Moderate cost: claim-name mapping for record paths, plus pinning the HAIP options. Gets the standards-track answer to "how do you do selective disclosure" without reinventing it. |
| **A3. Dual format, SD-JWT VC and ISO mdoc** | What eIDAS 2.0 actually mandates for wallet attestations. Expensive: two additional codecs to build and maintain, and mdoc's flat element-namespace model fits nested FHIR badly. |

**What makes this a product call and not an engineering one.**
The EUDI Architecture and Reference Framework lists mdoc, SD-JWT VC and W3C VCDM 2.0 as the credential formats; Member States must offer wallets and the public sector must accept them.
Healthcare attestations - patient summaries, ePrescriptions - appear as future use cases.
So "we invented our own credential format" is a real barrier to EU public-sector acceptance, not a stylistic objection.

**But it is a market question, not a technical one.**
If ROAX is never EU-facing, A1 is correct and A3 is waste.

**Why it is urgent even though the answer is not.**
Selective disclosure is the affected layer.
If A2 or A3 is ever chosen, the sane design maps ROAX leaves onto SD-JWT disclosures rather than running two unrelated disclosure systems side by side.
That mapping is much cheaper to preserve as a design constraint now than to retrofit.
**A ruling of "not now, but keep it possible" is materially different from "no", and is worth making explicitly.**

### Decision B - SHA-256, or Poseidon now? **RULED. Both, permanently.**

**The ruling.**
ZK-friendly and non-ZK hashes are **both first-class and selectable per record, permanently.**
This is not "SHA-256 now with an escape hatch later" and it is not "Poseidon now".
It is a standing commitment that `hashAlg` is a real per-record choice between two supported families, and that neither is provisional.

**What the ruling changed in the specification, and why it is a security matter rather than a labelling one.**
If both families are permanent then the algorithm identifier is load-bearing: `hashAlg` is the field that selects which hash function a verifier runs.
Left as a bare envelope field it would sit in exactly the region specification section 11.3 declares normatively to be attacker-controlled and never authority.

**The obvious fix does not work, and finding that out changed the answer.**
An intermediate draft committed `hashAlg` inside the root as a reserved leaf `roax.hashAlg`.
That leaf is hashed *under the algorithm it names*, so an attacker who computes an entire record under a weak algorithm `W` produces a self-consistent record whose `roax.hashAlg` leaf says `W` and whose root is the one he was aiming at.
Committing a field inside a root the attacker controls buys nothing.
The leaf was removed rather than kept as belt-and-braces, because a binding that does not bind is worse than none: it invites a verifier to rely on it.

Three mechanisms replace it (specification section 7.4), and they are recorded with what each is actually worth rather than as a list of equals:

1. **H1.**
   The domain string is algorithm-qualified - `DOMAIN = ASCII "ROAX-CANON/1/" + hashAlg` - and sits in every leaf preimage (specification section 8).
   Honestly, this buys almost nothing cryptographically, for the same reason the leaf did not: the attacker computes both records under the same domain.
   It removes cross-algorithm root ambiguity by construction and makes the envelope schema's claim true, and that is all.
   *(This sentence previously also said "every salt preimage".
   D4's ruling to D4b deleted salt derivation, so there is no salt preimage; `DOMAIN` itself is untouched by that ruling and the ruling under B is unaffected.)*
2. **H2, the one that matters.**
   The anchoring registry MUST record the pair `(root, hashAlg)` and a verifier MUST take `hashAlg` from the **registry**, never from the envelope.
   Authority for the algorithm then comes from the same place authority for the root comes from.
   This document does not design the anchoring registry, so this is handed forward to that work as a stated requirement (specification section 2.2).
3. **H3.**
   A verifier MUST reject any `hashAlg` absent from its own configured allow-list, which is what closes the retired-algorithm case that H2 alone does not.

Before the ruling the envelope schema **claimed** a binding the specification defined nowhere, which is the defect this records the fix for.
The general shape is worth keeping in mind for any future self-describing field: **a document cannot authenticate its own description**, so the description has to come from outside.

**What remains open under B.**
Two things, and they are narrower than the original question:

- **The `Poseidon-BN254` parameterization is not pinned**, and no parameterization is invented here.
  The field, the rate and capacity, the round constants, and the encoding from a length-prefixed byte string to field elements all have to be pinned before any Poseidon record is issued.
  The byte-level preimage in specification section 8 is stated over byte strings and does **not** transfer to a prime-field permutation unmodified.
  Section 7 no longer states a preimage of its own, because D4 was ruled D4b and salt derivation is gone, so section 8's leaf preimage is the only one left to carry across.
  `ROAX-CANON/1` therefore **defines** the construction for `SHA-256` only and **registers** `Poseidon-BN254`, with a normative MUST NOT against issuing under it until a revision pins the parameterization.
- **The cost consequences below are unchanged by the ruling** and still have to be planned for rather than discovered.
  They are what makes selecting Poseidon a deliberate per-record act.

**Written into the spec:** `hashAlg` as an algorithm-qualified domain component and deliberately **not** as a reserved leaf (sections 7, 7.4, 8, 11.2, 12), with the enum in `schemas/envelope-2.0.json` carrying both values and the Poseidon caution stated in the schema itself.
An earlier version of this line said "and a reserved leaf", which contradicted the paragraph above it: `roax.hashAlg` was removed because a leaf is hashed under the algorithm it names and therefore cannot bind it, and specification section 11.2 records that removal.
Section 7 stays in the citation list because it is where `DOMAIN` is stated to be algorithm-qualified; sections 7.4 and 8 carry the binding and the leaf preimage, 11.2 records the removed leaf, and 12 carries the versioning consequence.

| | **SHA-256** | **Poseidon over BN254** |
|---|---|---|
| Whole-record root, real MOH vaccination cert (87 leaves) | 0.74 ms | 41.2 ms (**56x**) |
| Same, PDT (130 leaves) | 0.907 ms | 57.4 ms (63x) |
| Same, recovery (65 leaves) | 0.339 ms | 17.6 ms (52x) |
| Rust | `sha2`, stdlib-adjacent | `light-poseidon` + `ark-bn254` + `ark-ff` |
| Swift | `CryptoKit`, first-party Apple | none native; FFI only |
| Kotlin | `java.security.MessageDigest`, JDK | none native; FFI only |
| Go | `crypto/sha256`, stdlib | no maintained circom-compatible BN254 Poseidon found |
| TypeScript | `node:crypto` / WebCrypto | `circomlibjs` |
| Hardware acceleration | Yes, ARMv8 / x86 SHA extensions | No |
| Usable inside a SNARK | Very expensive | Cheap - this is its entire purpose |

A single embedded PNG - the real vaccination `logo`, 14 KB - costs about 14 ms of Poseidon against about 41 microseconds of SHA-256.

**The honest framing, restated under the ruling.**
dogtag needs Poseidon because it proves consent in zero knowledge, and a SHA-256 Merkle path inside a circuit is prohibitive.
Where ROAX's disclosure story is "reveal this leaf plus an inclusion proof" there is no circuit, so SHA-256 is the right selection and Poseidon would buy nothing while costing a 52-63x slowdown, a prime-field dependency in five languages, and the loss of native crypto on both mobile platforms.
Where a record genuinely needs zero-knowledge consent proofs, that cost is the price of the capability.
**The ruling is that this is a per-record engineering choice rather than a project-wide one**, which is why `hashAlg` had to become cryptographically real rather than declarative.

**Hash agility is not free, and the ruling does not make it free.**
Two records with identical content and different `hashAlg` have different roots, and every verifier eventually implements both.
That cost was previously an argument for deferring the choice; it is now a planned cost.

**What still moves with a Poseidon selection:** D9 in particular.
Blob handling stops being an optimization and becomes necessary for any record issued under Poseidon, since blobs are 60-70% of hashed bytes and a 14 KB logo costs about 14 ms rather than about 41 microseconds.

**Why this is not a `canon` bump.**
Path encoding, type tags, value encoding, leaf composition and tree shape are unchanged when the hash changes, so the algorithm is its own versioning axis (specification section 12) rather than a new canonicalization version.
The schema binding, the conformance corpus structure and every library's flatten logic survive a Poseidon record untouched.
What does not survive untouched is the byte-string preimage, which is precisely the parameterization gap recorded above.

**Evidence note:** the timings are carried from the canonicalization research, which benchmarked `light-poseidon` 0.3 with `Poseidon::<Fr>::new_circom(n)` over `ark_bn254::Fr` - the exact primitive dogtag uses - and validated its harness by reproducing dogtag's own pinned anchor vector.
They were **not** re-run while writing this document.

### Decision C - What happens to the Singapore healthcerts already issued under OpenAttestation? **OPEN**

**Written into the spec:** nothing.
No migration path is specified.

| Option | Consequence |
|---|---|
| **C1. Dual-issue** - OA wrap for legacy verification, ROAX wrap for portable | No big-bang cutover. Cost: two roots and two verifiers, indefinitely. |
| **C2. ROAX-only for new issuance**, with importers for OA documents | Clean end state. Cost: migration tooling, and old documents need a verifier that still exists. |
| **C3. Verifier bridge** - reimplement OA's rules in Rust so ROAX verifiers read old certificates | Reads old certificates natively. Cost: high and fragile, because it means reimplementing the exact canonicalization this project exists to escape. |

**What the audit established about C3's feasibility.**
A byte-compatible OpenAttestation v2 verifier **is** feasible in Rust, Swift, Kotlin or Go.
The work is tedious rather than impossible: Flatley path rules, exact ECMAScript string quoting, UTF-8, legacy Keccak-256 (not FIPS SHA3-256 - the wire label `SHA3MerkleProof` is misleading), lowercase hex, sorted hash-array aggregation, and the batch Merkle rules.

**But it must emulate a historically reconstructed JavaScript compatibility profile, not implement a language-neutral specification.**
The de facto specification is the JavaScript composition at a pinned dependency set: OA `v6.9.7`, Flatley 5.2.0, `js-sha3` 0.8.0.

**And some of it is not merely tedious.**
Three states have no portable equivalent: `undefined` and sparse-array holes, unpaired UTF-16 surrogates, and duplicate JSON names.
OA also has a genuine wire bug that a bridge inherits - redacting an individual array element leaves a hole that serializes as `null`, which adds a visible leaf and makes verification fail after a JSON round trip:

```
in-memory redacted array:  ["fixed:zero", <hole>, "fixed:two"]
JSON wire form:            ["fixed:zero", null,   "fixed:two"]
digest before round trip:  6d5d47f4...
digest after parse:        c2f79bbf...      equal: false
```

**A consideration that is easy to miss.**
The vaccination healthcert's flattened `fhirBundle.entry[]` layout interacts with this decision.
Normalizing it to genuine FHIR would change every path and therefore every root, so any migration that also normalizes is a semantic rewrite, not a re-wrap.
See [`profiles/vaccination-healthcert.md`](profiles/vaccination-healthcert.md) section 2.1.

**This is a product and regulatory decision, not a technical one.**
All three options are buildable.
The question is who has to keep verifying what, for how long.

### Decision D - Five independent libraries, or a shared core over a binding layer? **RULED Da**

**Ruling (2026-07-29): Da.**
ROAX will ship five independent, corpus-enforced libraries rather than a shared Rust core.
Each implementation is written from `docs/spec/roax-canon-1.md`, and byte-identical corpus output is the release requirement under `docs/conformance-corpus.md` section 2.

**Written into the spec:** the conformance corpus is the release gate for all five independent implementations, as specified in ROAX-CANON/1 section 1.1 and `docs/conformance-corpus.md` section 2.

Both options are labelled with a letter suffix, matching every other decision in this document.
They were previously `D1` and `D2`, which collided with the renumbering table above, where `D1` became `S1` and `D2` became `B`.

| Option | Consequence |
|---|---|
| **Da. Five independent, corpus-enforced** | Genuinely idiomatic libraries in each language. The corpus becomes the entire enforcement mechanism, with no fallback. |
| **Db. Rust core plus a binding layer for Swift and Kotlin; independent TypeScript and Go** | What dogtag actually does, and it works. Go still ends up independent, because UniFFI has no first-class Go backend. |

**What dogtag proves.**
It got four-language agreement with **two** implementations, not four.
Rust and TypeScript are independent and mirror each other file for file; Swift and Kotlin call the Rust crate through UniFFI 0.28.
There is no Swift Poseidon and no Kotlin Poseidon in that repository - the Swift binding is generated (`apps/ios/DogTag/dogtag_standard.swift`).
Agreement between the two real implementations is enforced by a shared vector file with 15 leaf, 5 `bytesToField`, 11 Merkle-root and 110 inclusion vectors, driven from the Rust side by `crates/dogtag-standard-rs/tests/ffi_parity.rs`.

**What dogtag also proves about the risk of Da.**
Its TypeScript `verify` silently diverged from the Rust one and the divergence is recorded rather than fixed, because it has no production consumer (`AGENTS.md:357`).
An independent implementation not covered by the corpus will drift.

**Why the corpus is specified as though Da were chosen.**
Under Db the corpus is a safety net; under Da it is the only thing standing between five libraries and silent divergence.
Building it to the Da standard costs more now and is correct under either ruling.
Building it to the Db standard and then choosing Da means discovering the gap after divergence has already shipped.

**The ruling accepts Da's cost knowingly.**
The corpus is the entire cross-language enforcement mechanism, and a library that is not covered by it is not ready to claim conformance under `docs/conformance-corpus.md` section 2.

---

## Part 2 - The further decisions

**All ten were ruled on 2026-07-28.**
Eight confirmed what the specification already recommended, so for those the ruling records the reasoning rather than changing a rule.
Two changed the specification: **D4** moved to D4b and **D9** gained a content-addressed blob binding.

Each section keeps the option table it carried while the decision was open, because that table is the auditable record of what was weighed, and adds the ruling above it.

### The standing constraints these rulings were made under

Recorded here rather than repeated in each section, because they decided several of the close calls and a reader who does not know them will read some of these rulings as over-engineering.

1. **Silent divergence between two conformant implementations is the failure this project exists to remove.**
   Any option that lets two correct implementations produce different roots without either detecting it loses, even when it is cheaper.
2. **Development cost carries little weight**, against quality, simplicity, robustness, scalability and long-term maintainability.
3. **Every rule must be future-proof and must permit upgrades**, which is the constraint specification section 12.2 states as a standing requirement.
4. **No surface may state a fact it has not established.**
   This applies to a protocol claiming clinical meaning exactly as it applies to any other surface, and it is what D13 turns on.

### D3 - Wire format of the envelope. **RULED 2026-07-28: JSON, as recommended**

**Written into the spec:** JSON, with deterministic CBOR explicitly allowed later as a transport and normatively forbidden as the digest rule (specification section 13.2).

**The ruling.**
JSON is the version-1 wire format.
Deterministic CBOR remains explicitly permitted later as a **transport**, and MUST NOT become the digest rule.

**Reasoning.**
JSON is what every FHIR toolchain, every health authority and every existing healthcert already speaks, so it costs an adopter nothing.
And the property that actually matters - the digest rule being independent of the wire format - is preserved, which is what keeps a future binary transport from being a breaking change rather than a `canon` bump.

**The prohibition is the load-bearing half.**
`draft-mcnally-deterministic-cbor-17` section 2.5 forces integral floats to integers, so `2.0` becomes `2`.
Making dCBOR the digest rule would reintroduce the exact FHIR precision bug of Part 0, arriving from a direction nobody would be watching.
The specification therefore states the prohibition normatively rather than as advice.

### D4 - Salt strategy. **RULED 2026-07-28: D4b. One independently random CSPRNG salt per leaf**

**This ruling changed the specification.**
The specification previously recommended D4a - one master salt, HMAC-derived per leaf, with the record identifier folded into the preimage - and section 7 was rewritten for D4b.

**Written into the spec now:** each leaf carries its own 16-byte salt drawn independently from a CSPRNG (specification section 7).
There is no master salt, no KDF, and no salt preimage.

| Option | For | Against |
|---|---|---|
| **D4a. Derived from one master salt** | The issuer holds one 32-byte secret per record instead of 16 bytes per leaf, so it stores, backs up and reissues from about 1.4 KB less on an 87-leaf record and far less on a large FHIR bundle. | Has a sharp failure mode that D4b simply does not have. |
| **D4b. Independently random 16 bytes per leaf** (dogtag's choice) | No shared secret exists, so there is nothing to reuse and no unlinkability failure mode at all. A holder can disclose a leaf without the issuer regenerating a salt. | Issuer-side storage size. |

**Why the specification's own analysis leads to D4b.**
Specification section 7.3 already required a full copy to carry the salt of **every** leaf under either option, because a full copy is otherwise unverifiable: the verifier needs the salt of each leaf and the record body has none.
So the envelope is byte-identical either way, and a disclosed copy is small either way.
The entire argument for D4a was therefore **issuer-side storage** - 16 bytes per leaf against one 32-byte secret per record, about 1.4 KB on an 87-leaf record.

**Against that sits a failure mode D4b does not have at all.**
Under D4a, reusing `masterSalt` across two records for the same patient makes every shared path with a shared value produce the *same* leaf hash in both, so anyone who sees both disclosures links them.
In a protocol whose purpose is patient privacy that is the worst failure available, and it is **silent**: both records verify perfectly.

The specification's defence was to bind `recordId` into every salt preimage, adopted from dogtag, which does the same to keep one wallet's two tags mutually unlinkable (`AGENTS.md:1744-1745` in the `dogtag-mono-repo`).
That defence was real, and the specification was honest that it was defence in depth rather than a fix: if `recordId` is content-derived or reused across a reissuance, the linkage returns.
But "derive the record identifier deterministically so reissuance reproduces the same root" is an *attractive-sounding* thing for an implementer to do, and the specification said so itself.
A hazard a competent engineer can walk into while trying to be helpful is not adequately guarded by a MUST.

**Trading a kilobyte of issuer storage for a silent cross-record patient-linkage hazard is a bad trade, and 1.4 KB is not a real cost in 2026.**

**The ruling also simplifies the protocol, which is a second and independent reason for it.**
It deletes the KDF, the master salt, the `recordId`-in-preimage rule, and the old conformance class 12, whose only job was to enforce a MUST that no verifier can actually check.
Five independent implementations have five fewer places to disagree subtly.
dogtag reached this same answer for this same reason.

**Consequences applied in the same change:**

- Specification section 7 rewritten for independent per-leaf salts.
  `masterSalt` disappears entirely; it was already forbidden in every envelope, so **no envelope bytes change**.
- Salt entropy is now normative: at least 128 bits from a CSPRNG, and `ROAX-CANON/1` pins the length at exactly 16 bytes.
  It is the only thing standing between a withheld low-entropy leaf and a dictionary search.
- Conformance class 12 keeps its number and its subject and loses its mechanism: it now asserts that two records for the same subject sharing a path and a value produce **different** leaf hashes.
- `DOMAIN` stays algorithm-qualified exactly as it was.
  This ruling does not touch it.
- **A consequence the ruling did not enumerate:** `roax.recordId` was mandatory to disclose **by arithmetic**, because a verifier needed it to rebuild a salt preimage.
  With the preimage gone it is mandatory **by policy** instead, alongside `roax.issuer.id`.
  `roax.recordType`, `roax.schemaVersion` and `roax.typeMap.id` are arithmetic because they select and authenticate the exact type-map artifact.
  The floor now has five entries because the type-map work added `roax.typeMap.id` after the salt ruling.
  Specification sections 4.2, 10.2 and 11.2 and the four profile documents carry the combined result.

### D5 - Leaf ordering. **RULED 2026-07-28: D5a, by `encodePath` bytes, as recommended**

**Written into the spec:** by `encodePath` bytes (specification section 9), with the residual leak now stated in sections 2.2, 9.3 and 10.1 rather than left implicit.

| Option | Consequence |
|---|---|
| **D5a. By encoded path** | Tree shape becomes independent of salt values, and absence proofs become possible. Order is deterministic but **not alphabetical** (specification section 5.3). |
| **D5b. By leaf hash** (dogtag's choice, `merkle.rs:24-26`) | Hides a leaf's position among its siblings, a small privacy gain. Tree shape then depends on salts. |
| **D5c. Document order** | Fragile: depends on map iteration order, which is exactly the OpenAttestation trap. Not recommended under any reading. |

**Reasoning.**
D5b buys a genuine but small privacy gain: it hides a leaf's position among its siblings.
D5a buys a tree shape fully determined by the path set, and wins on three grounds.

The tree shape becomes reproducible and therefore *checkable*, so two implementations can be compared structurally, which matters enormously when five of them must agree.
It keeps absence proofs available later at nearly no cost, which is what D6 then preserves deliberately.
And under the D4b ruling above salts are now independently random, so D5b would make tree shape effectively random per record, which is the worst case for debugging a cross-implementation disagreement.

**The residual leak is stated in the specification rather than left implicit.**
Under D5a, a disclosure revealing leaves at two paths also reveals how many withheld leaves sort between them.
In practice this is bounded, because these profiles are published and their path sets are largely known already, but it is a real structural leak and the privacy text must say so plainly rather than letting a reader infer that sorting by path costs nothing.

D5c stays rejected.
It depends on map iteration order, which is precisely the OpenAttestation trap.

### D6 - Absence proofs. **RULED 2026-07-28: out of scope for version 1, capability deliberately preserved**

**Written into the spec:** not supported in version 1, with the construction recorded as admitting them (specification sections 2.2 and 9.3).

**Reasoning.**
Absence proofs fall out of D5a nearly free, so the cost of keeping the door open is close to zero and the specification records that the tree construction permits them.

They stay unimplemented because "this record asserts no allergy" is a clinical claim with liability attached.
That is a product and legal decision rather than a cryptographic one, and it is not one to make on the project owner's behalf.

The version-1 specification therefore says three things together: the construction admits absence proofs, this version does not define them, and defining them requires a clinical-liability decision.
That is honest, it forecloses nothing, and it stops a future implementer from reading the omission as an oversight and adding them unilaterally.

### D7 - Unknown paths not in the type map. **RULED 2026-07-28: D7a, fail closed, as recommended**

**Written into the spec:** fail closed (specification section 4.2), with the type map now stated as a first-class, independently versioned, issuer-extensible artifact (sections 4.2 and 4.3).

| Option | Consequence |
|---|---|
| **D7a. Fail closed** | Two libraries with different type-map versions cannot silently disagree - they refuse instead. |
| **D7b. Default to STRING** | Records always process. Two libraries with different type maps produce different roots **silently**, which is the exact failure this project exists to avoid. |
| **D7c. Default by observed JSON kind** | Same silent-divergence problem as D7b, plus it reintroduces syntactic type inference through the back door. |

**Reasoning.**
This one is not close.
D7b and D7c both let two libraries carrying different type-map versions produce different roots silently, which is the exact failure this project exists to remove, and D7c additionally smuggles syntactic type inference back in through a side door after the design went to some length to remove it (specification section 4.1).

**The operational cost is real and is planned for rather than absorbed.**
The PDT base object permits additional properties, so a legitimate PDT record may carry fields the type map has never seen, and D7a rejects it at issuance.
This lands hardest on PDT; see [`profiles/pdt-healthcert.md`](profiles/pdt-healthcert.md) section 5.

So the type map is **not a lookup table shipped once**.
It is a first-class, independently versioned, issuer-extensible artifact with a defined extension path, and that is an explicit deliverable rather than a footnote.
If extending it is slow or unclear, D7a becomes an adoption blocker for exactly the profile that already has the most real-world traffic, and the pressure to "just default it to STRING for now" will arrive from a real issuer with a real record, which is precisely when it will be hardest to refuse.

**One constraint on that extension path is load-bearing and is stated normatively:** an issuer extension MUST be additive.
Retagging a path the map already covers changes the root of every already-issued record that reaches it, which specification section 12.2 forbids.

### D8 - What goes inside the root. **RULED 2026-07-28: as recommended, plus a mandatory corpus vector**

**Written into the spec:** `canon` is bound through the domain string in every leaf; `roax.recordType`, `roax.schemaVersion`, `roax.typeMap.id`, `roax.recordId` and `roax.issuer.id` are the five mandatory reserved leaves; `roax.issuer.keyId` is the conditional reserved leaf; routing hints stay outside; and outside-the-root fields are hints and never authority (specification sections 8, 11.2 and 11.3).

**The tension is real in both directions and dogtag hit both ends.**

Put routing metadata **inside** and a deployed record cannot be re-stamped when infrastructure moves.
dogtag hit this with `statusBaseUrl` and deliberately kept it outside, so that stamping it "neither disturbs an anchored `R` nor lets a forged value make an invalid record verify" (`crates/dogtag-standard-rs/src/wrap.rs:75-85`).

Put it **outside** and everything there is attacker-controlled.
dogtag paid for this: its `check_integrity` folds only `data` plus `privacy.obfuscated`, so the whole `issuer` block including `documentStore` - the address every `isValid()` is called against - sits outside the root.
"Point `documentStore` at a contract you control that returns `true` from `isValid`, and integrity AND the on-chain read both pass" (`AGENTS.md:333`).
The fix was a whole extra mandatory issuer-whitelist pillar that exists only to compensate.

The ruled split puts identity inside and routing outside, which respects both ends of that evidence.

**One addition to the ruling, and it is the part that matters.**
A normative sentence saying "outside-the-root fields are hints, never authority" is **not enough on its own** - dogtag had the equivalent understanding written down and still shipped the bug, then needed an entire extra mandatory pillar to compensate.
The conformance corpus therefore MUST carry a vector that **fails** an implementation which trusts an outside-the-root field as authority.
That is conformance class 18.
A test that catches the mistake costs a day; the pillar dogtag needed to compensate for it cost far more.

### D9 - Big blobs. **RULED 2026-07-28: inline for version 1, AND the content-addressed binding defined now**

**This ruling extended the specification.**
The specification previously recommended inline only and treated content-addressing as a later question.

**Written into the spec:** explicitly typed healthcert blobs are hashed inline and bound as `STRING` over the base64 text, while FHIR `base64Binary` remains unresolved between STRING and BYTES (specification section 6.3); the content-addressed binding is **defined** as type tag 8 `BLOB_REF` and **selected by no version-1 profile**, so a record that selects it MUST be rejected (section 6.5); and one canonical base64 form is pinned (section 6.3).

`logo` and `attachments[].data` are **60-70% of all hashed bytes** across the three reference records: 14,314 bytes in the vaccination sample, 17,440 in the endorsed PDT, 2,618 in recovery.

**Why inline is right for now.**
Under `hashAlg: "SHA-256"` a 14 KB blob costs about 41 microseconds.
That is nothing, and inline keeps a record genuinely self-contained, which is worth a great deal in a setting where a traveller may present a credential offline at a border.

**Why the alternative had to be specified now rather than later.**
Decision B ruled that both hash families are permanent per-record selections, so D9 now hangs on whether any record family will select Poseidon.
Under Poseidon the same blob costs about 14 ms, and for a Poseidon-selecting family blob handling stops being an optimization and becomes a requirement.

Retrofitting a second leaf-binding form **after** five independent implementations exist is exactly the kind of change that splits a library family: some implement it, some do not, and a record that verifies in one fails in another.
Specifying it once now, while there is no code to migrate, costs almost nothing.
This is the standing future-proofing constraint applied where it is cheapest.

**Consequences applied in the same change:**

- The content-addressed binding commits to the blob's **length as well as its digest**.
  A digest alone lets a substituted blob of different size pass anything that does not separately check the size, so the length is inside the commitment rather than beside it.
- It is **registered but unselected**, mirroring exactly how `Poseidon-BN254` is handled: present in the schemas with a normative caution, and MUST NOT be issued against until a profile declares it.
- **One canonical base64 form is pinned now**, because a `BYTES` or `BLOB_REF` binding is otherwise ambiguous: RFC 4648 section 4, with padding, no line wrapping, standard alphabet.
  Padding and line-wrap variants encode identical bytes differently, and that ambiguity is a root-divergence bug waiting to happen.
- **Under-specified by the ruling and decided here, labelled as such:** the ruling did not say which digest the binding commits to.
  The specification pins SHA-256 regardless of `hashAlg`, and section 6.5 states the inference and its reason - binding the blob digest to `hashAlg` would make a Poseidon record hash the whole blob through Poseidon, which is the cost the binding exists to avoid.
  That is a design choice made here, not a ruling carried over.

### D11 - Detached signature. **RULED 2026-07-28: no signature field in version 1, as recommended**

**Written into the spec:** no signature field, plus the constraints on any future signature stated normatively now (specification section 2.2).

Under this design the root is anchored and authority is re-derived from the chain, exactly as dogtag insists - resolve the issuing clone "from the verifier's own `DogTagIssuerFactory.rootIssuer(R)`, NEVER from `wrappedDoc.issuer.documentStore`" (`AGENTS.md:326`).

**The constraints are written before the feature exists, and that is the point of this ruling.**
A detached signature MUST sign the root, MUST NOT become an alternative to anchoring, and a verifier MUST NOT accept a signature in place of a chain read.

Writing the constraint before the feature is what stops it being added wrongly.
A signature that lets a verifier skip the chain is a straight regression into the failure mode D8 describes, and the pressure to add exactly that will come from a real and sympathetic requirement - offline verification at a border with no connectivity - at a moment when saying no will be unpopular.
Better to have said it already.
This costs nothing now and is the same reasoning as D9.

### D12 - Unicode normalization. **RULED 2026-07-28: D12a, NFC pinned at Unicode 15.1, as recommended**

**Written into the spec:** NFC, with the Unicode version pinned at 15.1 (specification section 6.1), plus a conformance vector at class 19.

**This decision existed because two of the three research inputs disagreed**, and the disagreement is recorded rather than quietly resolved in favour of one of them.

- The canonicalization research specifies **mandatory NFC**.
- The OpenAttestation audit says a successor should use "either no normalization or an explicitly versioned normalization rule", adding that "preserving exact sequence is the least surprising for FHIR".

| Option | Consequence |
|---|---|
| **D12a. NFC with a pinned Unicode version** | Two records that render identically hash identically. Satisfies the audit too, since it explicitly admits a versioned normalization rule. Cost: every implementation's NFC tables must match the pinned version, and NFC is version-dependent. |
| **D12b. Preserve the exact scalar sequence** | No Unicode-version dependency at all. Cost: a record that passes through any normalizing form field - which is ordinary web-form behaviour - gets a different root, and the two forms render identically to a human, making the failure invisible. |

**Reasoning, and the disagreement resolves cleanly on this project's own thesis.**
D12b has no Unicode-version dependency, which is genuinely attractive.
Its cost is that a record passing through any normalizing form field - ordinary web-form behaviour, not an edge case - gets a different root, and the two forms **render identically to a human**.
That is an invisible failure, and invisible failures are what this project exists to remove.

D12a's cost is that every implementation's NFC tables must match the pinned version.
That is a real dependency, but it is **explicit and checkable**: `unicodeVersion` is already carried as an opaque equality-matched field, so a mismatch is detected rather than silently producing a different root.
An explicit dependency that fails loudly beats no dependency that fails silently.

The audit's position is satisfied too, since it explicitly admits a versioned normalization rule.
dogtag chose to normalize (`crates/dogtag-standard-rs/src/encode.rs:11`) and separately found it necessary to pin a Unicode version (`encode.rs:6-7`), which is the strongest available evidence that the pin is needed in practice rather than in theory.
That pin is recorded only in dogtag's source and not in its written scar list, so it is cited at that strength.

**A conformance vector is required, not optional.**
Class 19 carries a string that differs before and after NFC with its expected root, because without it the rule is prose that every implementation is trusted to have followed.

### D13 - Clinical validation level. **RULED 2026-07-28: D13a at the protocol layer, with a mandatory honesty statement and a split**

**Written into the spec:** a new section 2.3 stating what a valid root proves and what it does not, with a normative prohibition on asserting a clinical fact from root validity alone, and clinical validation recorded as a separate independently versioned layer that is out of scope here.

| Option | Consequence |
|---|---|
| **D13a. Base FHIR only** | Broad interoperability, weak healthcare semantics. |
| **D13b. Base FHIR plus named implementation profiles** | Actually enforces subject, event, cardinality and reference rules. Cost: more work and ongoing profile governance. |

**The finding this rests on is the important part and it now lives in the specification.**
The four profile documents establish that the reference schemas enforce far less than they appear to.
A minimal `{"resourceType":"Bundle"}` satisfies both PDT and recovery.
The recovery schema never checks that the result is positive.
The vaccination schema never requires any entry at all.

So today a valid ROAX root proves that a typed payload was committed by an identified issuer, and **nothing clinical whatsoever**.
Any product surface saying "negative PDT result" or "proof of recovery" on the strength of root validity alone is stating a fact it has not established.

**The ruling is a clean split.**
The protocol layer stays honest and narrow: it proves commitment and issuer identity, and it says so in those words.
Clinical validation is a **separate, independently versioned conformance layer** that a deployment may adopt, where D13b's named implementation profiles enforce subject, event, cardinality and reference rules.

That split gets the honesty immediately, keeps the canonicalization layer clean, and lets D13b arrive later as an additive layer without touching a single byte of the digest rule.
Merging the two would put clinical governance on the critical path of a cryptographic specification, which is how both end up moving at the speed of the slower one.

---

## Part 2a - Newly identified, and genuinely open

### D14 - Does type-map matching normalize the key it matches on? **OPEN**

**Identified on 2026-07-29 while building the conformance vector decision D12's ruling required.**
It is recorded here rather than settled in passing, because settling it changes matching in both reference implementations and in the type-map tooling at once.
It also reaches the Rust library, which takes neither side: `LookupKeyMode` has no default, and the construction and verification paths reject a key whose binding differs between the two readings rather than choosing one (`rust/README.md`).
So a ruling retires that guard as well as changing the matchers.
It reaches the TypeScript and Python libraries too, and each of those compares a display pattern against a segment key raw today, with no `nfc()` on either side and a note at the site saying that adding one would rule D14 silently (`src/typemap.ts:182-191`; `python/src/roax_canon/typemap.py:25-33` and `:195`).
That is a statement of what those two do while the decision is open rather than a reading of it, and neither exposes a switch, so a ruling lands in both of them: as an edit under D14a and as specified behaviour under D14b.

**Written into the spec:** nothing.
Specification section 6.1 pins NFC for **hashing**, and section 4.2 requires an uncovered path to fail closed.
Neither says whether the type-map **lookup** that runs *before* hashing compares a normalized key or the bytes as received.

**Why it is not academic.**
Both reference implementations currently match **raw**, with no `nfc()` on either the pattern token or the segment key (`corpus/tools/roax_ref.py` `_match_from`; `corpus/tools/roax_ref.mjs` `matchPattern`).
So a record whose key is written decomposed fails the lookup and is **refused outright by the fail-closed rule**, while the identical record written composed resolves and commits.
The two render identically to a human.

**That is the invisible-divergence failure D12 exists to prevent, arriving one layer up.**
D12 reasoned that a record passing through a normalizing form field must not get a different root; under raw matching it does not get a different root, it gets rejected instead, and the rejection is just as invisible to whoever typed the value.

**The evidence that this is unresolved rather than merely undocumented.**
The synthetic type map in `corpus/tools/synthetic_records.py` carries the Kelvin key under **both** spellings, so `record-guard-kelvin-key` resolves identically under either reading.
That is a workaround standing in for a decision, and it is why no existing vector settles the question.
`corpus/README.md` records the same gap in its specification-reading notes.

**The matchers in this repository already answer it differently, and that is the substance of the question rather than a detail of it.**
`docs/type-maps.md` section 3 step 2 requires a conforming resolver of the published DFA artifacts to NFC-normalize a KEY segment before taking its transition, so those artifacts are already described as reading D14a.
The corpus reference implementations are display-pattern matchers over `corpus/type-maps/` rather than the DFA, and they compare raw, as above.
Neither document is wrong about the thing it owns, and neither is the specification, which says nothing.
What is open is which reading the specification states for both, and until it does, the cost line below understates D14b: matching raw normatively would also change the resolver semantics `docs/type-maps.md` section 3 already publishes, not only leave the corpus matchers alone.

| Option | Consequence |
|---|---|
| **D14a. Match over NFC-normalized keys** | Follows specification section 11.2's general rule, "check the bytes you commit, not the bytes you received", and makes the two spellings behave identically end to end. Cost: every type map and both implementations change together, and a pattern authored in one form silently starts matching the other. |
| **D14b. Match raw, and say so normatively** | No code changes. Cost: the divergence above becomes a specified behaviour rather than an accident, and every type map must enumerate every spelling it intends to accept - which is what the Kelvin workaround already does by hand. |

**Not ruled here, and the conformance vector that would settle it is deliberately not built.**
`docs/conformance-corpus.md` class 19 carries the **value** case only and says why the **key** case is absent: building it would decide this question rather than test a decided one.

---

## Part 3 - Settled

These are not open.
They are recorded with their reasons so the reasons are auditable later.

| # | Settled | Why |
|---|---|---|
| **S1** | Canonical form is a **typed field-path scheme**, not JCS, not deterministic CBOR, not RDFC-1.0 | JCS is disqualified by a demonstrated collision against a FHIR R4 `SHALL` (specification section 13.1, reproducible). dCBOR relocates rather than removes the design work and gives no selective disclosure (13.2). RDFC-1.0 has a documented denial-of-service class whose defence is an implementation-chosen iteration limit, so two conformant implementations disagree on which records they will canonicalize at all (13.3). |
| **S2** | Tree is **RFC 9162** | Position-bound, so no commutative-fold hazard of the kind dogtag demonstrates in its own tests. Published, with specified non-power-of-two handling rather than invented. |
| **S3** | Numbers are **arbitrary-precision strings, never floats** | Part 0. |
| **S4** | The type tag comes from the **schema, not the literal's syntax** | Specification section 4. Three issuers writing the same logical value otherwise produce three different roots. |
| **S5** | Empty array, empty object and null are **three distinct leaves** | dogtag collapses them; in FHIR the difference between "no entries" and "field absent" can be clinically meaningful. |
| **S6** | Path encoding is **length-prefixed with no reserved characters** | Removes the need for a rejection rule, and removes the OpenAttestation array-versus-object and empty-key collisions by construction. |
| **S7** | Each profile declares a **minimum-disclosure floor** | Adopted from dogtag's `NON_OBFUSCATABLE` (`verify.rs:253`). Without it a disclosed copy can withhold what the record is and still verify. |
| **S8** | Reserved namespaces are guarded by a **prefix on one key, not by exact name match** | Each reserved path is a SINGLE segment carrying the literal dotted name, so the guard tests the NFC-normalized key of a record path's FIRST segment for the ASCII prefix `roax.` (specification section 11.2). Guarding only the exact reserved names would leave `roax.recordIdX` reachable, which is dogtag's recorded reason for moving off exact match (`profile_tree.rs:54-66`). What transfers is that argument, not the string operation. Two corrections to an earlier draft are folded in here: reserved paths are single dotted segments rather than one segment per dot component, because the per-component reading collides with any record carrying an ordinary top-level field named `roax` and these families already carry non-clinical top-level keys; and consequently an ordinary key named `roax` or `roaxX` is ACCEPTED, where the earlier draft rejected both. |
| **S9** | The **corpus is a release gate**, including validation by a different author's implementation | [`conformance-corpus.md`](conformance-corpus.md) section 2. |
| **S10** | **No contract set is permanent** | dogtag keeps its contract-set axis and its artifact axis in separate keyspaces precisely so rotating one does not change what an already-issued record claims (`wrap.rs:30-42`). Another smart-contract round is expected. |

---

## Part 4 - Where the evidence is thin

Recorded so that nobody mistakes a gap for a conclusion.

| Gap | Status |
|---|---|
| **Some reference-schema paths remain untyped.** | Four executable base maps and their issuer extension mechanism are published. The remaining gap is evidence, not machinery: vaccination `dose` and `expiryDateTime`, PDT's 20 endorsed-sample path-kind pairs, FHIR XHTML, `base64Binary` and null placeholders remain unbound and fail closed. `docs/type-maps.md` sections 1 and 2 give the evidence and exact coverage. |
| **Kotlin/JVM literal-preserving JSON is unverified.** | Every other target language has a confirmed mechanism. Kotlin was not tested by any research leg. |
| **The five reference implementations share one author.** | They do not share a JSON parser, number representation, Unicode API, map or sort. They do share one reading of the specification. Hence gate 3 in the corpus. |
| **No character with version-dependent NFC has been identified.** | The Unicode pin is inferred from dogtag having found it necessary in code, not from an exhibited failing character. Conformance class 16 says so explicitly. |
| **The ROAX chain integration is not designed.** | Anchoring registry shape, batching and revocation semantics are a real design space that no research leg covered. |
| **The `Poseidon-BN254` parameterization is not pinned.** | Decision B is ruled: both hash families are first-class and selectable per record. What is not settled is the parameterization - field, rate and capacity, round constants, and the byte-string-to-field-element encoding, which the byte-level preimage of specification section 8 does not survive without. Section 7 no longer states a preimage, because D4 was ruled D4b. `ROAX-CANON/1` defines SHA-256 only and registers Poseidon-BN254 with a MUST NOT against issuing under it. No parameterization has been invented to fill the gap. |
| **Which record families will select Poseidon is unknown.** | Blob handling is an optimization for a SHA-256 record and a requirement for a Poseidon one. D9 is ruled and no longer waits on this: the content-addressed binding is **defined** in `ROAX-CANON/1` and **selected by no version-1 profile**, so the answer to this question decides when a profile selects it rather than whether the binding exists. |
| **The audit's boundary conclusion was reached without consulting dogtag.** | **Closed.** Checked during this work; the conclusion survives, and dogtag's narrower single-profile shape is explained rather than adopted. See specification section 14.1. |
