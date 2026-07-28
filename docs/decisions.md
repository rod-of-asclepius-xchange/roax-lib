# Decisions: settled, open, and the reasoning

**Status:** every decision marked OPEN is genuinely open. One - **Decision B**, the hash function -
has since been ruled, and is marked RULED with the residual open questions named inside it. The rest
have not been ruled on.

The protocol specification is **written on the recommended answer to each open decision**, so that
it is concrete and readable rather than hedged into uselessness. That is a drafting choice, not a
ruling. A specification that hides a live decision behind confident prose is worse than one that
names it, so each is named here with its alternatives and their consequences.

## Numbering

The design research numbered its forks D1 through D10. Three were renumbered here so that the four
decisions named by the project owner keep the letters used there. The rest kept their numbers.

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

Two research legs reached this from **different directions**, using different evidence, without
sharing a method. That independence is the argument; either alone would be weaker.

**Source 1 - from the specification text, forward.**
FHIR R4 says of `decimal`: "The precision of the decimal value has significance: e.g. 0.010 is
regarded as different to 0.01, and the original precision should be preserved", and
"Implementations **SHALL** handle decimal values in ways that preserve and respect the precision of
the value as represented for presentation purposes"
(<https://hl7.org/fhir/R4/datatypes.html>).

RFC 8785 (JCS) section 3.2.2.3 mandates serialization "according to Section 7.1.12.1 of [ECMA-262]",
which is ECMAScript `Number::toString` over an IEEE-754 double. Running that on FHIR-legal decimals
collapses `0.010` and `0.01` to the same string, and silently corrupts
`9223372036854775807` into `9223372036854776000`.

**Source 2 - from the OpenAttestation source, backward.**
The OpenAttestation audit reached the same conclusion by reading what the deployed system actually
does. Its salting step computes `` `${typeof value}:${String(value)}` ``, so the loss happens before
any serialization. Reproduced against the pinned source at OA `v6.9.7`:

```
JSON.parse("9007199254740993")                         = 9007199254740992
JSON.parse("9007199254740993") === JSON.parse("9007199254740992") = true
typed JSON.parse("1") === typed JSON.parse("1.0")      = true
1e21 -> number:1e+21        1e20 -> number:100000000000000000000
NaN  -> number:NaN          Infinity -> number:Infinity
```

The audit states the consequence plainly: FHIR R4 defines separate integer and decimal primitives
with decimal precision significant in exchange, and "they should not be silently collapsed into one
JavaScript number domain."

**Why the independence matters.** Source 1 could be dismissed as a specification-lawyer reading of a
`SHALL` that nobody enforces. Source 2 could be dismissed as an implementation defect that a careful
port would avoid. Together they are neither: the standard forbids it, and the deployed system does
it anyway, because the language model makes it the path of least resistance.

**This is the justification for the entire design.** It is why ROAX carries numbers as
arbitrary-precision strings and never parses them through a float (specification section 6.2), why
implementations MUST NOT use a floating-point type at the parse boundary (section 6.4), and why JCS
is disqualified rather than merely disfavoured (section 13.1).

**Reproduced while writing this documentation set**, on Node v22.21.0, from the source-1 direction.
The script and its output are in [`conformance-corpus.md`](conformance-corpus.md) section 5. The
source-2 reproductions are carried from the audit and were not independently re-run.

---

## Part 1 - The four decisions that belong to the project owner

Three of them - A, C and D - have not been ruled on.
**B has been ruled**, and is kept here rather than moved to Part 3 because what remains open under
it is substantive and is named in its own section.

### Decision A - Does roax-lib need EU recognition? **OPEN**

**Written into the spec:** nothing. The specification takes no position and defines no export
profile.

| Option | Consequence |
|---|---|
| **A1. No EU recognition sought** | Simplest. ROAX stays a commitment-and-anchoring protocol with its own disclosure model. Cost: outside the EU public-sector acceptance path, permanently. |
| **A2. Profile SD-JWT VC as an export format** | Moderate cost: claim-name mapping for record paths, plus pinning the HAIP options. Gets the standards-track answer to "how do you do selective disclosure" without reinventing it. |
| **A3. Dual format, SD-JWT VC and ISO mdoc** | What eIDAS 2.0 actually mandates for wallet attestations. Expensive: two additional codecs to build and maintain, and mdoc's flat element-namespace model fits nested FHIR badly. |

**What makes this a product call and not an engineering one.** The EUDI Architecture and
Reference Framework lists mdoc, SD-JWT VC and W3C VCDM 2.0 as the credential formats; Member States
must offer wallets and the public sector must accept them. Healthcare attestations - patient
summaries, ePrescriptions - appear as future use cases. So "we invented our own credential format"
is a real barrier to EU public-sector acceptance, not a stylistic objection.

**But it is a market question, not a technical one.** If ROAX is never EU-facing, A1 is correct and
A3 is waste.

**Why it is urgent even though the answer is not.** Selective disclosure is the affected layer. If
A2 or A3 is ever chosen, the sane design maps ROAX leaves onto SD-JWT disclosures rather than
running two unrelated disclosure systems side by side. That mapping is much cheaper to preserve as a
design constraint now than to retrofit. **A ruling of "not now, but keep it possible" is materially
different from "no", and is worth making explicitly.**

### Decision B - SHA-256, or Poseidon now? **RULED. Both, permanently.**

**The ruling.** ZK-friendly and non-ZK hashes are **both first-class and selectable per record,
permanently.** This is not "SHA-256 now with an escape hatch later" and it is not "Poseidon now". It
is a standing commitment that `hashAlg` is a real per-record choice between two supported families,
and that neither is provisional.

**What the ruling changed in the specification, and why it is a security matter rather than a
labelling one.** If both families are permanent then the algorithm identifier is load-bearing:
`hashAlg` is the field that selects which hash function a verifier runs. Left as a bare envelope
field it would sit in exactly the region specification section 11.3 declares normatively to be
attacker-controlled and never authority.

**The obvious fix does not work, and finding that out changed the answer.** An intermediate draft
committed `hashAlg` inside the root as a reserved leaf `roax.hashAlg`. That leaf is hashed *under
the algorithm it names*, so an attacker who computes an entire record under a weak algorithm `W`
produces a self-consistent record whose `roax.hashAlg` leaf says `W` and whose root is the one he
was aiming at. Committing a field inside a root the attacker controls buys nothing. The leaf was
removed rather than kept as belt-and-braces, because a binding that does not bind is worse than
none: it invites a verifier to rely on it.

Three mechanisms replace it (specification section 7.4), and they are recorded with what each is
actually worth rather than as a list of equals:

1. **H1.** The domain string is algorithm-qualified - `DOMAIN = ASCII "ROAX-CANON/1/" + hashAlg` -
   and sits in every salt preimage (section 7) and every leaf preimage (section 8). Honestly, this
   buys almost nothing cryptographically, for the same reason the leaf did not: the attacker
   computes both records under the same domain. It removes cross-algorithm root ambiguity by
   construction and makes the envelope schema's claim true, and that is all.
2. **H2, the one that matters.** The anchoring registry MUST record the pair `(root, hashAlg)` and
   a verifier MUST take `hashAlg` from the **registry**, never from the envelope. Authority for the
   algorithm then comes from the same place authority for the root comes from. This document does
   not design the anchoring registry, so this is handed forward to that work as a stated
   requirement (specification section 2.2).
3. **H3.** A verifier MUST reject any `hashAlg` absent from its own configured allow-list, which is
   what closes the retired-algorithm case that H2 alone does not.

Before the ruling the envelope schema **claimed** a binding the specification defined nowhere,
which is the defect this records the fix for. The general shape is worth keeping in mind for any
future self-describing field: **a document cannot authenticate its own description**, so the
description has to come from outside.

**What remains open under B.** Two things, and they are narrower than the original question:

- **The `Poseidon-BN254` parameterization is not pinned**, and no parameterization is invented here.
  The field, the rate and capacity, the round constants, and the encoding from a length-prefixed
  byte string to field elements all have to be pinned before any Poseidon record is issued. The
  byte-level preimages in specification sections 7 and 8 are stated over byte strings and do **not**
  transfer to a prime-field permutation unmodified. `ROAX-CANON/1` therefore **defines** the
  construction for `SHA-256` only and **registers** `Poseidon-BN254`, with a normative MUST NOT
  against issuing under it until a revision pins the parameterization.
- **The cost consequences below are unchanged by the ruling** and still have to be planned for
  rather than discovered. They are what makes selecting Poseidon a deliberate per-record act.

**Written into the spec:** `hashAlg` as an algorithm-qualified domain component and a reserved leaf
(sections 7, 7.4, 8, 11.2, 12), with the enum in `schemas/envelope-1.0.json` carrying both values
and the Poseidon caution stated in the schema itself.

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

A single embedded PNG - the real vaccination `logo`, 14 KB - costs about 14 ms of Poseidon against
about 41 microseconds of SHA-256.

**The honest framing, restated under the ruling.** dogtag needs Poseidon because it proves consent
in zero knowledge, and a SHA-256 Merkle path inside a circuit is prohibitive. Where ROAX's
disclosure story is "reveal this leaf plus an inclusion proof" there is no circuit, so SHA-256 is
the right selection and Poseidon would buy nothing while costing a 52-63x slowdown, a prime-field
dependency in five languages, and the loss of native crypto on both mobile platforms. Where a record
genuinely needs zero-knowledge consent proofs, that cost is the price of the capability. **The
ruling is that this is a per-record engineering choice rather than a project-wide one**, which is
why `hashAlg` had to become cryptographically real rather than declarative.

**Hash agility is not free, and the ruling does not make it free.** Two records with identical
content and different `hashAlg` have different roots, and every verifier eventually implements both.
That cost was previously an argument for deferring the choice; it is now a planned cost.

**What still moves with a Poseidon selection:** D9 in particular. Blob handling stops being an
optimization and becomes necessary for any record issued under Poseidon, since blobs are 60-70% of
hashed bytes and a 14 KB logo costs about 14 ms rather than about 41 microseconds.

**Why this is not a `canon` bump.** Path encoding, type tags, value encoding, leaf composition and
tree shape are unchanged when the hash changes, so the algorithm is its own versioning axis
(specification section 12) rather than a new canonicalization version. The schema binding, the
conformance corpus structure and every library's flatten logic survive a Poseidon record untouched.
What does not survive untouched is the byte-string preimage, which is precisely the parameterization
gap recorded above.

**Evidence note:** the timings are carried from the canonicalization research, which benchmarked
`light-poseidon` 0.3 with `Poseidon::<Fr>::new_circom(n)` over `ark_bn254::Fr` - the exact primitive
dogtag uses - and validated its harness by reproducing dogtag's own pinned anchor vector. They were
**not** re-run while writing this document.

### Decision C - What happens to the Singapore healthcerts already issued under OpenAttestation? **OPEN**

**Written into the spec:** nothing. No migration path is specified.

| Option | Consequence |
|---|---|
| **C1. Dual-issue** - OA wrap for legacy verification, ROAX wrap for portable | No big-bang cutover. Cost: two roots and two verifiers, indefinitely. |
| **C2. ROAX-only for new issuance**, with importers for OA documents | Clean end state. Cost: migration tooling, and old documents need a verifier that still exists. |
| **C3. Verifier bridge** - reimplement OA's rules in Rust so ROAX verifiers read old certificates | Reads old certificates natively. Cost: high and fragile, because it means reimplementing the exact canonicalization this project exists to escape. |

**What the audit established about C3's feasibility.** A byte-compatible OpenAttestation v2 verifier
**is** feasible in Rust, Swift, Kotlin or Go. The work is tedious rather than impossible: Flatley
path rules, exact ECMAScript string quoting, UTF-8, legacy Keccak-256 (not FIPS SHA3-256 - the wire
label `SHA3MerkleProof` is misleading), lowercase hex, sorted hash-array aggregation, and the batch
Merkle rules.

**But it must emulate a historically reconstructed JavaScript compatibility profile, not implement a
language-neutral specification.** The de facto specification is the JavaScript composition at a
pinned dependency set: OA `v6.9.7`, Flatley 5.2.0, `js-sha3` 0.8.0.

**And some of it is not merely tedious.** Three states have no portable equivalent: `undefined` and
sparse-array holes, unpaired UTF-16 surrogates, and duplicate JSON names. OA also has a genuine wire
bug that a bridge inherits - redacting an individual array element leaves a hole that serializes as
`null`, which adds a visible leaf and makes verification fail after a JSON round trip:

```
in-memory redacted array:  ["fixed:zero", <hole>, "fixed:two"]
JSON wire form:            ["fixed:zero", null,   "fixed:two"]
digest before round trip:  6d5d47f4...
digest after parse:        c2f79bbf...      equal: false
```

**A consideration that is easy to miss.** The vaccination healthcert's flattened `fhirBundle.entry[]`
layout interacts with this decision. Normalizing it to genuine FHIR would change every path and
therefore every root, so any migration that also normalizes is a semantic rewrite, not a re-wrap.
See [`profiles/vaccination-healthcert.md`](profiles/vaccination-healthcert.md) section 2.1.

**This is a product and regulatory decision, not a technical one.** All three options are
buildable. The question is who has to keep verifying what, for how long.

### Decision D - Five independent libraries, or a shared core over a binding layer? **OPEN**

**Written into the spec:** nothing directly, but the conformance corpus is specified as though Da
will be chosen, because that is the conservative assumption - see below.

Both options are labelled with a letter suffix, matching every other decision in this document. They
were previously `D1` and `D2`, which collided with the renumbering table above, where `D1` became
`S1` and `D2` became `B`.

| Option | Consequence |
|---|---|
| **Da. Five independent, corpus-enforced** | Genuinely idiomatic libraries in each language. The corpus becomes the entire enforcement mechanism, with no fallback. |
| **Db. Rust core plus a binding layer for Swift and Kotlin; independent TypeScript and Go** | What dogtag actually does, and it works. Go still ends up independent, because UniFFI has no first-class Go backend. |

**What dogtag proves.** It got four-language agreement with **two** implementations, not four.
Rust and TypeScript are independent and mirror each other file for file; Swift and Kotlin call the
Rust crate through UniFFI 0.28. There is no Swift Poseidon and no Kotlin Poseidon in that
repository - the Swift binding is generated (`apps/ios/DogTag/dogtag_standard.swift`). Agreement
between the two real implementations is enforced by a shared vector file with 15 leaf, 5
`bytesToField`, 11 Merkle-root and 110 inclusion vectors, driven from the Rust side by
`crates/dogtag-standard-rs/tests/ffi_parity.rs`.

**What dogtag also proves about the risk of Da.** Its TypeScript `verify` silently diverged from the
Rust one and the divergence is recorded rather than fixed, because it has no production consumer
(`AGENTS.md:357`). An independent implementation not covered by the corpus will drift.

**Why the corpus is specified as though Da were chosen.** Under Db the corpus is a safety net; under
Da it is the only thing standing between five libraries and silent divergence. Building it to the
Da standard costs more now and is correct under either ruling. Building it to the Db standard and
then choosing Da means discovering the gap after divergence has already shipped.

**This is a strategy call, not a technical one.** Both work.

---

## Part 2 - The further decisions

### D3 - Wire format of the envelope. **OPEN**

**Written into the spec:** JSON, with deterministic CBOR explicitly allowed later.

The digest rule is independent of the wire format under this design, which is a property worth
keeping deliberately. If a binary envelope is wanted, serialize the envelope in dCBOR without making
dCBOR the digest rule - see specification section 13.2 for why the latter would reintroduce the FHIR
precision bug from a different direction (dCBOR section 2.5 forces integral floats to integers, so
`2.0` becomes `2`).

### D4 - Salt strategy. **OPEN, and closer than the size saving suggests**

**Written into the spec:** one master salt, HMAC-derived per leaf, with the record identifier folded
into the preimage (specification section 7).

| Option | For | Against |
|---|---|---|
| **D4a. Derived from one master salt** | The issuer holds one 32-byte secret per record instead of 16 bytes per leaf, so it stores, backs up and reissues from about 1.4 KB less on an 87-leaf record and far less on a large FHIR bundle. | Has a sharp failure mode that D4b simply does not have. |
| **D4b. dogtag's stored 16 bytes per leaf** | No shared secret exists, so there is nothing to reuse and no unlinkability failure mode at all. A holder can disclose a leaf without the issuer regenerating a salt. | Issuer-side storage size. |

**The size argument is about issuer storage, not envelope size, and that distinction was sharpened
while closing a review finding.** Specification section 7.3 requires a **full copy to carry the salt
of every leaf** under either option, because a full copy is otherwise unverifiable: the verifier
needs `salt(path)` for each leaf and the record body has none. So a full copy is the same size under
D4a and D4b, and a disclosed copy is small under both because it carries only the salts of the
leaves it reveals.

**The envelope format is deliberately agnostic here, so that this decision stays genuinely open.**
An earlier draft of section 7.3 required a full copy to carry `masterSalt`. That was withdrawn: it
is unimplementable under D4b, where no `masterSalt` exists, so a schema would have foreclosed this
decision by accident. Carrying per-leaf salts works under both - HMAC-derived and written out under
D4a, independently random and written out under D4b - and the envelope bytes are identical either
way. Nothing in `schemas/envelope-1.0.json` should be read as a ruling on D4.

**The sharp failure mode, stated precisely.** Under D4a, reusing `masterSalt` across two records for
the same patient makes every shared path with a shared value produce the *same* leaf hash in both, so
a verifier who sees both disclosures links them. And "derive `masterSalt` deterministically so
reissuance reproduces the same root" is an attractive-sounding way to do exactly that.

**What the dogtag reconciliation changed here.** dogtag binds a per-record identifier into every KDF
preimage precisely to keep two records of one owner mutually unlinkable (`AGENTS.md:1744-1745`).
The specification adopts that, so the ROAX salt preimage includes `recordId`.

**This is defense in depth, not a fix, and the distinction matters for this ruling.** It converts
"one MUST protects everything" into "two independent things must both go wrong". If `recordId` is
content-derived or reused across a reissuance, the linkage returns. D4a remains safe only with the
MUST in specification section 7 and the vector in conformance class 12 both enforced.

**If the project would rather not carry that hazard at all, D4b is defensible and the argument
against it is only size.**

### D5 - Leaf ordering. **OPEN**

**Written into the spec:** by `encodePath` bytes (specification section 9).

| Option | Consequence |
|---|---|
| **D5a. By encoded path** | Tree shape becomes independent of salt values, and absence proofs become possible. Order is deterministic but **not alphabetical** (specification section 5.3). |
| **D5b. By leaf hash** (dogtag's choice, `merkle.rs:24-26`) | Hides a leaf's position among its siblings, a small privacy gain. Tree shape then depends on salts. |
| **D5c. Document order** | Fragile: depends on map iteration order, which is exactly the OpenAttestation trap. Not recommended under any reading. |

### D6 - Absence proofs. **OPEN - flagged, not recommended**

**Written into the spec:** not supported. Section 2.2 lists it as out of scope.

They fall out of D5a nearly free. But "this record asserts no allergy" is a clinical claim with
liability attached, and it needs a product decision rather than a cryptographic one. Deliberately
flagged rather than recommended.

### D7 - Unknown paths not in the type map. **OPEN**

**Written into the spec:** fail closed (specification section 4.2).

| Option | Consequence |
|---|---|
| **D7a. Fail closed** | Two libraries with different type-map versions cannot silently disagree - they refuse instead. |
| **D7b. Default to STRING** | Records always process. Two libraries with different type maps produce different roots **silently**, which is the exact failure this project exists to avoid. |
| **D7c. Default by observed JSON kind** | Same silent-divergence problem as D7b, plus it reintroduces syntactic type inference through the back door. |

**The operational cost of D7a, stated rather than smoothed over.** The PDT base object allows
additional properties, so a legitimate PDT record may carry fields the type map has never seen, and
D7a rejects it at issuance. For that profile the type map has to be maintained as an allowlist that
issuers can extend, and extending it is a versioned change. See
[`profiles/pdt-healthcert.md`](profiles/pdt-healthcert.md) section 5. That cost is real and it lands
hardest on PDT.

### D8 - What goes inside the root. **OPEN**

**Written into the spec:** `canon`, `recordType`, `schemaVersion`, `recordId` and issuer identity
inside as reserved leaves; routing hints outside (specification section 11.2).

**The tension is real in both directions and dogtag hit both ends.**

Put routing metadata **inside** and a deployed record cannot be re-stamped when infrastructure
moves. dogtag hit this with `statusBaseUrl` and deliberately kept it outside, so that stamping it
"neither disturbs an anchored `R` nor lets a forged value make an invalid record verify"
(`crates/dogtag-standard-rs/src/wrap.rs:75-85`).

Put it **outside** and everything there is attacker-controlled. dogtag paid for this: its
`check_integrity` folds only `data` plus `privacy.obfuscated`, so the whole `issuer` block including
`documentStore` - the address every `isValid()` is called against - sits outside the root. "Point
`documentStore` at a contract you control that returns `true` from `isValid`, and integrity AND the
on-chain read both pass" (`AGENTS.md:333`). The fix was a whole extra mandatory issuer-whitelist
pillar that exists only to compensate.

The recommended split puts identity inside and routing outside, and the specification states
normatively that outside-the-root fields are hints and never authority.

### D9 - Big blobs. **OPEN - worth a look**

**Written into the spec:** hashed inline, bound as `STRING` over the base64 text (specification
section 6.3).

`logo` and `attachments[].data` are **60-70% of all hashed bytes** across the three reference
records: 14,314 bytes in the vaccination sample, 17,440 in the endorsed PDT, 2,618 in recovery.

Content-addressing them - hash in the tree, blob out of band - would shrink records dramatically.

**Not urgent for a record issued under `hashAlg: "SHA-256"`, where a 14 KB blob costs about 41
microseconds. Becomes urgent for one issued under Poseidon, where the same blob costs about 14 ms.**

Decision B is ruled, and it rules that both are permanent per-record selections rather than one
project-wide choice, so D9 is no longer downstream of "which hash wins". It is downstream of
**whether any record family will select Poseidon**, and for those families blob handling is a
requirement rather than an optimization.

A `BYTES` binding would additionally require pinning one canonical base64 form, since padding and
line-wrap variants encode the same bytes differently.

### D11 - Detached signature. **OPEN**

**Written into the spec:** no signature field (specification section 2.2).

Under this design the root is anchored and authority is re-derived from the chain, exactly as dogtag
insists - resolve the issuing clone "from the verifier's own `DogTagIssuerFactory.rootIssuer(R)`,
NEVER from `wrappedDoc.issuer.documentStore`" (`AGENTS.md:326`).

If offline verification is wanted, a detached signature is the answer, and it MUST sign the root and
MUST NOT become an alternative to anchoring. Adding it is cheap; adding it in a way that lets a
verifier skip the chain is a regression to the failure mode D8 describes.

### D12 - Unicode normalization. **OPEN - and it resolves a conflict between the research inputs**

**Written into the spec:** NFC, with the Unicode version pinned at 15.1 (specification section 6.1).

**This decision exists because two of the three research inputs disagreed**, and the disagreement is
recorded rather than quietly resolved in favour of one of them.

- The canonicalization research specifies **mandatory NFC**.
- The OpenAttestation audit says a successor should use "either no normalization or an explicitly
  versioned normalization rule", adding that "preserving exact sequence is the least surprising for
  FHIR".

| Option | Consequence |
|---|---|
| **D12a. NFC with a pinned Unicode version** | Two records that render identically hash identically. Satisfies the audit too, since it explicitly admits a versioned normalization rule. Cost: every implementation's NFC tables must match the pinned version, and NFC is version-dependent. |
| **D12b. Preserve the exact scalar sequence** | No Unicode-version dependency at all. Cost: a record that passes through any normalizing form field - which is ordinary web-form behaviour - gets a different root, and the two forms render identically to a human, making the failure invisible. |

dogtag chose to normalize (`crates/dogtag-standard-rs/src/encode.rs:11`) and separately found it
necessary to pin a Unicode version (`encode.rs:6-7`), which is the evidence behind the recommended
answer. That pin is recorded only in dogtag's source and not in its written scar list, so it is
cited at that strength: evidence the pin was needed in practice, not a post-mortem of what went
wrong without it.

### D13 - Clinical validation level. **OPEN**

**Written into the spec:** nothing. The protocol layer commits what it is given.

| Option | Consequence |
|---|---|
| **D13a. Base FHIR only** | Broad interoperability, weak healthcare semantics. |
| **D13b. Base FHIR plus named implementation profiles** | Actually enforces subject, event, cardinality and reference rules. Cost: more work and ongoing profile governance. |

**Why this is on the list at all.** The four profile documents establish that the reference schemas
enforce far less than they appear to. A minimal `{"resourceType":"Bundle"}` satisfies PDT and
recovery; the recovery schema never checks the result is positive; the vaccination schema never
requires any entry. So today a valid ROAX root proves a typed payload was committed by an issuer,
and nothing clinical.

If any product surface says "negative PDT result" or "proof of recovery", that claim needs D13b or
it needs to be derived from the disclosed payload and clearly attributed to the payload rather than
to the protocol.

---

## Part 3 - Settled

These are not open. They are recorded with their reasons so the reasons are auditable later.

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
| **The type map does not exist.** | Established as necessary, tractable and roughly sized. Not built. On the critical path. |
| **Kotlin/JVM literal-preserving JSON is unverified.** | Every other target language has a confirmed mechanism. Kotlin was not tested by any research leg. |
| **The five reference implementations share one author.** | They do not share a JSON parser, number representation, Unicode API, map or sort. They do share one reading of the specification. Hence gate 3 in the corpus. |
| **No character with version-dependent NFC has been identified.** | The Unicode pin is inferred from dogtag having found it necessary in code, not from an exhibited failing character. Conformance class 16 says so explicitly. |
| **The ROAX chain integration is not designed.** | Anchoring registry shape, batching and revocation semantics are a real design space that no research leg covered. |
| **The `Poseidon-BN254` parameterization is not pinned.** | Decision B is ruled: both hash families are first-class and selectable per record. What is not settled is the parameterization - field, rate and capacity, round constants, and the byte-string-to-field-element encoding, which the byte-level preimages of specification sections 7 and 8 do not survive without. `ROAX-CANON/1` defines SHA-256 only and registers Poseidon-BN254 with a MUST NOT against issuing under it. No parameterization has been invented to fill the gap. |
| **Which record families will select Poseidon is unknown.** | This is what D9 now turns on. Blob handling is an optimization for a SHA-256 record and a requirement for a Poseidon one. |
| **The audit's boundary conclusion was reached without consulting dogtag.** | **Closed.** Checked during this work; the conclusion survives, and dogtag's narrower single-profile shape is explained rather than adopted. See specification section 14.1. |
