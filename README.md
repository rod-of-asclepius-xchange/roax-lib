# roax-lib

Open protocol standards and multi-language libraries for **human healthcare records**.

The goal is a language-neutral way to canonically serialize, merklize, anchor and selectively disclose real health records - FHIR, and Singapore MOH's PDT, recovery and vaccination healthcerts - integrating with ROAX.

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

## Start here

| Read | For |
|---|---|
| [`src/README.md`](src/README.md) | The TypeScript library: what it is, how to run it, and the four traps JavaScript sets for this design. |
| [`docs/typescript-implementation-findings.md`](docs/typescript-implementation-findings.md) | **Where that independent build disagreed with the corpus, and where the specification admitted two honest readings.** Worth more than the code. |
| [`docs/decisions.md`](docs/decisions.md) | **The decisions, ruled and open, each with its reasoning.** Two are still open, A and C, and both belong to the project owner. Start here if you are reviewing rather than implementing. |
| [`docs/spec/roax-canon-1.md`](docs/spec/roax-canon-1.md) | The protocol. Precise enough to implement from. Section 2 says what it does not solve; section 14 reconciles it against dogtag. |
| [`docs/profiles/`](docs/profiles/) | One document per record family, because the four families do **not** share one concrete object. |
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
See decision C.

## What is not decided

Two of the four decisions that belong to the project owner are open, and neither is quietly settled anywhere in these documents:

- **A** - whether roax-lib needs EU recognition, which would mandate SD-JWT VC and ISO mdoc export profiles.
- **C** - what happens to the Singapore healthcerts already issued under OpenAttestation.

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
docs/decisions.md   settled, open, and the reasoning
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
