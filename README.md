# roax-lib

Open protocol standards and multi-language libraries for **human healthcare records**.

The goal is a language-neutral way to canonically serialize, merklize, anchor and
selectively disclose real health records - FHIR, and Singapore MOH's PDT, recovery
and vaccination healthcerts - integrating with ROAX.

Status: **design phase.** Specifications and schemas are drafted for review.
No library code has been written, deliberately.

## Start here

| Read | For |
|---|---|
| [`docs/decisions.md`](docs/decisions.md) | **The open decisions.** Four are unruled and belong to the project owner. Start here if you are reviewing rather than implementing. |
| [`docs/spec/roax-canon-1.md`](docs/spec/roax-canon-1.md) | The protocol. Precise enough to implement from. Section 2 says what it does not solve; section 14 reconciles it against dogtag. |
| [`docs/profiles/`](docs/profiles/) | One document per record family, because the four families do **not** share one concrete object. |
| [`docs/conformance-corpus.md`](docs/conformance-corpus.md) | What cross-language agreement has to be proven against, and why that is a release gate rather than decoration. |
| [`schemas/`](schemas/) | JSON Schemas for the envelope, the type map and the conformance corpus. |

## Why not OpenAttestation

OpenAttestation derives a document's digest by walking a JSON object in JavaScript
into salted key-value paths. The digest therefore depends on JavaScript's object and
string semantics, which is what makes it awkward to reimplement faithfully in Rust,
Swift, Kotlin or Go. A protocol intended to have first-class libraries in several
languages cannot inherit that constraint.

The precise version of that objection, with the evidence, is
[`docs/decisions.md` part 0](docs/decisions.md#part-0---the-load-bearing-finding): two research
legs established from different directions that the JavaScript number model cannot carry FHIR
decimals. One worked forward from the FHIR R4 specification, which says `0.010` and `0.01`
**SHALL** be treated as different; the other worked backward from the deployed OpenAttestation
source, which makes them identical. That finding is what the whole design rests on.

A fair reading of OpenAttestation is that a byte-compatible verifier for it **is** buildable in
any of these languages. The problem is not that it is impossible - it is that doing so means
emulating a reconstructed JavaScript compatibility profile at a pinned dependency set, rather than
implementing a language-neutral specification. See decision C.

## What is not decided

Four decisions are open and none of them is quietly settled anywhere in these documents:

- **A** - whether roax-lib needs EU recognition, which would mandate SD-JWT VC and ISO mdoc export
  profiles.
- **B** - SHA-256 with a declared algorithm field, versus ZK-ready Poseidon now.
- **C** - what happens to the Singapore healthcerts already issued under OpenAttestation.
- **D** - five independent libraries versus a shared core over a binding layer.

Nine more are recorded alongside them. The specification is written on the *recommended* answer to
each so that it reads as a real specification; that is a drafting choice and not a ruling.

## Repository layout

```
docs/spec/          the protocol specification
docs/profiles/      one document per record family
docs/decisions.md   settled, open, and the reasoning
docs/conformance-corpus.md
schemas/            JSON Schemas
```

Reference material used during design - including third-party schemata - is kept
**outside** this repository by design and is never committed here. It is cited by path.
