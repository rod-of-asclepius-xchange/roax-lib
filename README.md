# roax-lib

Open protocol standards and multi-language libraries for **human healthcare records**.

The goal is a language-neutral way to canonically serialize, merklize, anchor and selectively disclose real health records, integrating with ROAX.
**It is an international protocol that carries per-jurisdiction profiles, rather than one jurisdiction's format.**
A record family is named in lowercase reverse-DNS form and joins by a registry entry, so `hl7.fhir.bundle` and `sg.gov.moh.vaccination-healthcert` sit side by side as profiles of one protocol.
Of the four profiles registered today, `hl7.fhir.bundle` is HL7 FHIR 4.0.1, an international standard rather than a national one; Singapore MOH's PDT, recovery and vaccination healthcerts are the **first national jurisdiction worked end to end**, and all three are registered profiles with published type maps.
One measured gap remains there and it is a profile question rather than a support one: PDT's endorsed sample is not yet committable in the conformance corpus, pending a versioned composition profile nobody has ruled ([`docs/type-maps.md`](docs/type-maps.md) section 1.2).
No library embeds or implements those artifacts: each takes its type-map resolver from the caller, which the section below measures in all five.

Status: **implementation phase.**
The specifications and schemas were drafted and reviewed before any library existed, deliberately, so that the design could be settled before the implementations existed to re-litigate it.

**The independent libraries that exist today**, each written from [`docs/spec/roax-canon-1.md`](docs/spec/roax-canon-1.md) without reading another, are Rust under [`rust/`](rust/), TypeScript under [`src/`](src/), Python under [`python/`](python/), Swift under [`swift/`](swift/) and Kotlin under [`kotlin/`](kotlin/).
**One named language has not been added, Go**, and it should not be without an explicit instruction.

**The headline figure and the named set have never agreed, and an earlier version of this section asserted both at once.**
It said five implementations, then that three of the five existed, then that Go, Swift and Kotlin had not been added, which is six.
Decision D was ruled Da on 2026-07-29 to "five independent, corpus-enforced libraries", and its rejected option Db names those five as Rust, TypeScript, Swift, Kotlin and Go.
Python was built afterwards as a further independent library, which makes the language set six while the ruling's figure stays five.
The list above happens to hold as many entries as that figure and is not the same set, since Python is in it and Go is not, so the agreement of the two numbers is a coincidence rather than the question closing.
The counts above are therefore stated by enumeration and no total is restated here: [`docs/decisions.md`](docs/decisions.md) decision D owns that figure, and reconciling it with the language set is a ruling rather than a documentation edit.

## One protocol, per-jurisdiction profiles

**The protocol layer is jurisdiction-neutral by construction, and that is checkable rather than asserted.**
It commits a typed payload tree, the reserved `roax.*` leaves and an RFC 9162 root, and none of those names a country.
`recordType` is constrained by *form* - lowercase reverse-DNS - and never by an enumerated list, in both [`schemas/envelope-1.0.json`](schemas/envelope-1.0.json) and [`schemas/envelope-2.0.json`](schemas/envelope-2.0.json), whose own description says the pattern "constrains the FORM only" because the registry "is not a closed universe".
Specification section 12.2 states the rule normatively: "New profiles and new versions arrive by a registry entry, never by editing this specification."
That registry is [`docs/profiles/`](docs/profiles/), one document per `recordType`.

**Adding a jurisdiction takes three things, and none of them is a protocol change or a library source edit.**

1. **A profile document** under `docs/profiles/`, declaring at minimum its `schemaVersion`, its type-map scope and its non-redactable path set ([`docs/profiles/README.md`](docs/profiles/README.md); specification section 10.2).
   This is not a formality: a syntactically valid `recordType` with no profile document is not a valid record, and the non-redactable floor is decided here.
2. **A type-map artifact** in the format of [`schemas/type-map-artifact-1.0.json`](schemas/type-map-artifact-1.0.json), plus its row in [`type-maps/registry-1.0.0.json`](type-maps/registry-1.0.0.json).
   `node tools/check-type-maps.mjs` validates the artifacts and the registry against the committed tree, with no reference checkout and no dependency on the generator.
   It takes Ajv 8 and `ajv-formats` from a directory outside the tree named by `ROAX_AJV`, and `--skip-schema-validation` runs the dependency-free subset without them ([`docs/type-maps.md`](docs/type-maps.md) section 6).
3. **Registering that profile with a verifier**, which every library takes as *configuration* rather than as a source edit.
   Rust ships no profile implementation at all - `Profile` is a trait the caller implements ([`rust/src/envelope.rs:17`](rust/src/envelope.rs)), so even the Singapore profiles are caller-side there.
   The other four ship the registry as an overridable default: TypeScript's `knownProfiles` and `floorFor` config ([`src/envelope.ts:616`](src/envelope.ts) and `:971`), Python's `ProfileRegistry.with_profile`, Swift's public `ProfileRegistry(profiles:)` beside its `versionOne` default, and Kotlin's `ProfileRegistry.with` beside `ProfileRegistry.DEFAULT`.
   No library embeds or loads a published type-map artifact; the resolver is supplied by the caller in all five.

**One honest limit, because an unqualified claim of extensibility is exactly the defect this repository keeps catching.**
*Generating* a type-map artifact from a JSON Schema does not work today: `tools/build-type-maps.mjs` fails closed on merged object states that need combinator-aware evaluation, so neither regeneration nor `--check` runs ([`docs/type-maps.md`](docs/type-maps.md) sections 1.6 and 6).
At least 34 such states were measured on the pinned reference checkout, and that figure is a lower bound rather than a count: it predates a widening of the branch selection and has not been re-measured, because the checkout is outside this repository.
Authoring and validating an artifact is unaffected, and the committed artifacts stay authoritative, but a new family whose map would be derived from a schema meets that block.

**Jurisdiction-neutral and language-neutral are two separate claims here, and only the first is about profiles.**
The second is why [`docs/spec/roax-canon-1.md`](docs/spec/roax-canon-1.md) section 13 rejects JCS and dCBOR: their number models are artifacts of a particular language runtime.
The protocol is built on RFC 9162, RFC 4648, BCP 14 and Unicode NFC, listed in specification section 16.
The Unicode version is pinned at 15.1 by specification section 6.1.

## Start here

| Read | For |
|---|---|
| [`src/README.md`](src/README.md) | The TypeScript library: what it is, how to run it, and the four traps JavaScript sets for this design. |
| [`docs/typescript-implementation-findings.md`](docs/typescript-implementation-findings.md) | **Where that independent build disagreed with the corpus, and where the specification admitted two honest readings.** Worth more than the code. |
| [`docs/decisions.md`](docs/decisions.md) | **Every decision, each with its reasoning and the options it was chosen from.** All four owner decisions are ruled; what remains unsettled is narrower than a decision and is named there. Start here if you are reviewing rather than implementing. |
| [`docs/spec/roax-canon-1.md`](docs/spec/roax-canon-1.md) | The protocol. Precise enough to implement from. Section 2 says what it does not solve; section 14 reconciles it against dogtag. |
| [`docs/profiles/`](docs/profiles/) | The `recordType` registry, one document per record family, because the four families registered today do **not** share one concrete object. |
| [`docs/type-maps.md`](docs/type-maps.md) | The published type-map artifacts, exact coverage, unresolved schema gaps and issuer extension lifecycle. |
| [`docs/conformance-corpus.md`](docs/conformance-corpus.md) | What cross-language agreement has to be proven against, and why that is a release gate rather than decoration. |
| [`schemas/`](schemas/) | JSON Schemas for the envelope, the type map and the conformance corpus. |
| [`rust/`](rust/) | The independent Rust implementation, its protocol boundaries and validation commands. |
| [`python/`](python/) | The independent Python implementation, standard library only. [`python/FINDINGS.md`](python/FINDINGS.md) records what that build found. |
| [`swift/`](swift/) | The independent Swift implementation, a SwiftPM package for macOS and iOS. [`swift/FINDINGS.md`](swift/FINDINGS.md) records what that build found, including a `String` comparison rule that silently answers an open specification ambiguity. |
| [`kotlin/`](kotlin/) | The independent Kotlin implementation, zero runtime dependencies, packaged for the JVM and for Android. [`kotlin/FINDINGS.md`](kotlin/FINDINGS.md) records what that build found, including the JVM number and Unicode traps it had to be written around. |

## Why not OpenAttestation

OpenAttestation derives a document's digest by walking a JSON object in JavaScript into salted key-value paths.
The digest therefore depends on JavaScript's object and string semantics, which is what makes it awkward to reimplement faithfully in Rust, Swift, Kotlin or Go.
A protocol intended to have first-class libraries in several languages cannot inherit that constraint.

The precise version of that objection, with the evidence, is [`docs/decisions.md` part 0](docs/decisions.md#part-0---the-load-bearing-finding): two research legs established from different directions that the JavaScript number model cannot carry FHIR decimals.
One worked forward from the FHIR R4 specification, which says `0.010` and `0.01` **SHALL** be treated as different; the other worked backward from the deployed OpenAttestation source, which makes them identical.
That finding is what the whole design rests on.

A fair reading of OpenAttestation is that a byte-compatible verifier for it **is** buildable in any of these languages.
The problem is not that it is impossible - it is that doing so means emulating a reconstructed JavaScript compatibility profile at a pinned dependency set, rather than implementing a language-neutral specification.
**Decision C ruled on 2026-08-02 that this project will not build one**, and that already-issued documents are remapped into this protocol instead.
The feasibility finding stands: the bridge is buildable, and building it is what the ruling declines.

## What is decided, and what is left beneath the rulings

**All four decisions that belong to the project owner are now ruled**, and what is still unanswered is narrower than a decision rather than a fork between tabled options.
`docs/decisions.md` names each remaining gap; the two that other documents cite are the `Poseidon-BN254` parameterization under B and the remap mechanics under C.

**C was ruled on 2026-08-02: remap into this protocol, translation deferred.**
Healthcerts already issued under OpenAttestation are **remapped into ROAX** - re-submitted to this standard and re-derived under ROAX canonicalization - rather than bridged.
This project builds and maintains no OpenAttestation verifier.
A translation method is **deferred rather than refused**, exactly as under A.
**The consequence a reader relying on an existing document must be told:** a remap produces a **new root**, and the anchored OpenAttestation root is not preserved, so a proof against the old root stays a proof of the old bytes.
Two of the three states the audit called unportable are rejected at the input boundary by specification section 3.2 - duplicate member names and unpaired surrogate escapes - so a remap fails closed on them rather than dropping them quietly.
The third, `undefined` and sparse-array holes, has **no answer today**: section 3.2 lists it, but the state has no JSON representation, so it is already gone by the time a remap reads serialized bytes.
`docs/decisions.md` decision C carries that gap in full, including why a serialized redaction hole becomes a committed `NULL` leaf.

**A was ruled on 2026-08-02: not now, and deliberately kept possible.**
roax-lib adopts no EU credential format and builds no export codec; material issued under another regime is **re-submitted to this standard** rather than translated.
A translation method is **deferred rather than refused**, and that is what makes the ruling more than a "no": it carries a standing constraint that a disclosure unit stays a single leaf, independently verifiable from its own audit path, so a future SD-JWT mapping remains buildable instead of needing a retrofit.
A and C were ruled on the same date and share that principle - conform to this standard now, keep translation possible later - but **neither decided the other**, and `docs/decisions.md` keeps them apart deliberately.

**D was ruled on 2026-07-29.**
ROAX uses five independent, corpus-enforced libraries rather than a shared core, as recorded in `docs/decisions.md` decision D.

**B - the hash function - has been ruled.**
ZK-friendly and non-ZK hashes are both first-class and selectable per record, permanently, which is why the algorithm identifier is folded into the domain string that enters every leaf preimage rather than merely declared in the envelope.
It is deliberately *not* a leaf: a leaf is hashed under the algorithm it names, so it cannot bind it, and authority comes from the anchoring registry instead.
What remains open under B is the `Poseidon-BN254` parameterization, which is not pinned and which no record may be issued against until it is.

**The ten further decisions were ruled on 2026-07-28** and the specification is written on those rulings.
Eight confirmed what it already recommended.
Two changed it: salts are now one independent CSPRNG draw per leaf with no master salt and no derivation, and a content-addressed blob binding is defined without being selected by any version-1 profile.
Specification section 15 tables where each ruling lands, and `docs/decisions.md` part 2 gives every one of them with its reasoning, so any of them can be overturned on the reasoning rather than on authority.

**One further question was identified after those rulings and was ruled on 2026-07-30: D14** - whether the type-map lookup matches over an NFC-normalized key or over the bytes as received.
It is ruled D14a, normalize, because section 11.2's rule is "check the bytes you commit" and a raw comparison would let two records that render identically diverge, with one refused outright.
It is in `docs/decisions.md` part 2a.

**The five undetermined type bindings were ruled in the same change**, each with an evidence grade: vaccination `dose` INTEGER plus a positive-integer profile narrowing, `expiryDateTime` STRING, FHIR `base64Binary` BYTES over the decoded octets, FHIR `Narrative.div` STRING over the escaped XHTML text, and FHIR primitive-array null placeholders rejected rather than bound.
`docs/type-maps.md` section 1 holds the evidence and states which rulings are operative where.

## Repository layout

```
docs/spec/          the protocol specification
docs/profiles/      one document per record family
docs/decisions.md   every decision, what is left beneath the rulings, and why
docs/type-maps.md   type-map coverage, gaps and issuer extensions
docs/conformance-corpus.md
schemas/            JSON Schemas
type-maps/          immutable generated base maps and their registry
tools/              type-map reproduction and integrity checks, and the Markdown reflow check
corpus/             the conformance corpus, its fixtures and its two reference implementations
rust/               independent Rust implementation of ROAX-CANON/1
src/                independent TypeScript implementation of ROAX-CANON/1
python/             independent Python implementation of ROAX-CANON/1
swift/              independent Swift implementation of ROAX-CANON/1
kotlin/             independent Kotlin implementation of ROAX-CANON/1, JVM and Android
```

Reference material used during design - including third-party schemata - is kept **outside** this repository by design and is never committed here.
It is cited by path.
