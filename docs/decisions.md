# Decisions: settled, open, and the reasoning

**Status:** every decision marked OPEN is genuinely open. None has been ruled on.

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

## Part 1 - The four decisions the project owner has not ruled on

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

### Decision B - SHA-256 with declared agility, or Poseidon now? **OPEN**

**Written into the spec:** B2. `hashAlg` is a declared field pinned at `SHA-256` for v1, with the
algorithm identifier part of the domain string (specification section 12).

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

**The honest framing.** dogtag needs Poseidon because it proves consent in zero knowledge, and a
SHA-256 Merkle path inside a circuit is prohibitive. If ROAX's disclosure story is "reveal this leaf
plus an inclusion proof", it needs no circuit, and Poseidon buys nothing while costing a 56x
slowdown, a prime-field dependency in five languages, and the loss of native crypto on both mobile
platforms.

**Hash agility is not free.** Two records with identical content and different `hashAlg` have
different roots, and every verifier eventually implements both.

**What flips this decision:** a commitment that zero-knowledge consent proofs are in scope for v1.
If so, B3 is right and several other things move with it, notably D9 - blob handling stops being an
optimization and becomes necessary, since blobs are 60-70% of hashed bytes.

**The v2 path if ZK arrives later:** keep the structure of the specification exactly - path
encoding, type tags, value encoding, leaf composition, tree shape - and swap only the hash, giving
`ROAX-CANON/2` with `hashAlg: "Poseidon-BN254"`. Because the structure is unchanged, the schema
binding, the conformance corpus and every library's flatten logic survive untouched.

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

**Written into the spec:** nothing directly, but the conformance corpus is specified as though D1
will be chosen, because that is the conservative assumption - see below.

| Option | Consequence |
|---|---|
| **D1. Five independent, corpus-enforced** | Genuinely idiomatic libraries in each language. The corpus becomes the entire enforcement mechanism, with no fallback. |
| **D2. Rust core plus a binding layer for Swift and Kotlin; independent TypeScript and Go** | What dogtag actually does, and it works. Go still ends up independent, because UniFFI has no first-class Go backend. |

**What dogtag proves.** It got four-language agreement with **two** implementations, not four.
Rust and TypeScript are independent and mirror each other file for file; Swift and Kotlin call the
Rust crate through UniFFI 0.28. There is no Swift Poseidon and no Kotlin Poseidon in that
repository - the Swift binding is generated (`apps/ios/DogTag/dogtag_standard.swift`). Agreement
between the two real implementations is enforced by a shared vector file with 15 leaf, 5
`bytesToField`, 11 Merkle-root and 110 inclusion vectors, driven from the Rust side by
`crates/dogtag-standard-rs/tests/ffi_parity.rs`.

**What dogtag also proves about the risk of D1.** Its TypeScript `verify` silently diverged from the
Rust one and the divergence is recorded rather than fixed, because it has no production consumer
(`AGENTS.md:357`). An independent implementation not covered by the corpus will drift.

**Why the corpus is specified as though D1 were chosen.** Under D2 the corpus is a safety net; under
D1 it is the only thing standing between five libraries and silent divergence. Building it to the
D1 standard costs more now and is correct under either ruling. Building it to the D2 standard and
then choosing D1 means discovering the gap after divergence has already shipped.

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
| **D4a. Derived from one master salt** | Saves about 1.4 KB on an 87-leaf record and far more on a large FHIR bundle. One 32-byte secret instead of 16 bytes per leaf. | Has a sharp failure mode that D4b simply does not have. |
| **D4b. dogtag's stored 16 bytes per leaf** | No shared secret exists, so there is nothing to reuse and no unlinkability failure mode at all. A holder can disclose a leaf without the issuer regenerating a salt. | Size. |

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

**Not urgent under B2 (SHA-256), where a 14 KB blob costs about 41 microseconds.
Becomes urgent under B3 (Poseidon), where the same blob costs about 14 ms.** So D9 is partly
downstream of decision B and should be revisited if B moves.

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
| **S8** | Reserved namespaces are guarded by **prefix, not exact match** | dogtag changed to a prefix guard deliberately, recording that exact-match left both a bare-namespace blob leaf and an adjacent-name squat reachable (`profile_tree.rs:54-66`). |
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
| **Whether ZK is coming is unknown.** | Decision B's recommendation is conditional on it not being a near-term requirement. If it is, B flips and D9 moves with it. |
| **The audit's boundary conclusion was reached without consulting dogtag.** | **Closed.** Checked during this work; the conclusion survives, and dogtag's narrower single-profile shape is explained rather than adopted. See specification section 14.1. |
