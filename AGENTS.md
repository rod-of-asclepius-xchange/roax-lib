# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

## What this repository is right now

Specification, schemas, the conformance corpus, and five independent libraries: Rust under `rust/`, TypeScript under `src/`, Python under `python/`, Swift under `swift/` and Kotlin under `kotlin/`.
Decision D was ruled to five independent, corpus-enforced libraries on 2026-07-29 (`docs/decisions.md`, decision D).
The specifications came first so the design could be reviewed before the language implementations existed to be re-litigated, and that ordering held.
`rust/README.md` owns that crate's protocol boundaries, its build, test and lint commands, and what ruled decisions D13a and D14a mean for its surface.
`python/README.md` owns that package's surface, its standalone corpus runner, its test commands and its per-class figures, and `python/FINDINGS.md` records what that build found.
`swift/README.md` owns that package's targets, its corpus runner and its reference-record naming contract, and `swift/FINDINGS.md` records what that build found.
`kotlin/README.md` owns that module's surface, its Gradle commands, its Android packaging and the reference-record contract its corpus runner uses, and `kotlin/FINDINGS.md` records what that build found.

Do not add the Go library without an explicit instruction to do so.

**This is an INTERNATIONAL protocol carrying per-jurisdiction profiles, and the prose used to read as a Singapore one.**
That was corrected on 2026-08-02 as a positioning fix, and nothing in the architecture moved, because the neutrality was already real and only the framing was wrong.
Three facts were verified against the code and are what the framing may claim; do not restate them from memory, and do not widen them:

- **Nothing hard-codes a jurisdiction.**
  `docs/spec/roax-canon-1.md` names Singapore in three places and all three are non-normative: the glossary, one envelope example at `recordType`, and the read-only reference-schema citation.
  `recordType` is constrained by lowercase reverse-DNS FORM and never by an enum, in both `schemas/envelope-1.0.json` and `schemas/envelope-2.0.json`, and section 12.2 makes `docs/profiles/` the extension point normatively.
- **Adding a jurisdiction is a profile document plus a type-map artifact plus a registry row, and no library source edit.**
  The profile registry is caller-supplied in all five: Rust ships NO `impl Profile` at all so even the Singapore profiles are caller-side, and the other four ship an overridable default (`src/envelope.ts` `knownProfiles`/`floorFor`, Python `ProfileRegistry.with_profile`, Swift `ProfileRegistry(profiles:)`, Kotlin `ProfileRegistry.with`).
  **No library embeds or loads a published `type-maps/` artifact** - every `type-maps/` string in library source is a doc comment, and the resolver is caller-supplied.
- **The honest limit that must travel with the claim:** GENERATING a type-map artifact from a JSON Schema does not work today, because `tools/build-type-maps.mjs` fails closed on the merged object states.
  Cite that figure as a LOWER BOUND of at least 34 and never as a count, for the reason the type-map section below already gives.
  Authoring and validating one is unaffected and `node tools/check-type-maps.mjs` passes on the committed tree, with no reference checkout - it does need Ajv 8 and `ajv-formats` installed outside the tree and named by `ROAX_AJV`, and `--skip-schema-validation` runs the dependency-free subset.
  Stating extensibility without that caveat is the overstatement this repository keeps catching.

**Do not conflate jurisdiction-neutral with language-neutral.**
They are two separate claims: the first is about the profile registry, the second is why section 13 rejects JCS and dCBOR.
And do not let a reframing read as dropping Singapore support - the three MOH healthcerts are the only national jurisdiction worked end to end, and `hl7.fhir.bundle` is the international standard beside them rather than the general case they specialize.
Scope that support as `README.md` does rather than as "fully implemented": recovery and vaccination commit and class 10 is 2 of 3 records, while PDT's endorsed sample stays uncommittable on the 20 `(pattern, kind)` pairs its open root leaves undeclared, pending a versioned composition profile nobody has ruled (`docs/type-maps.md` section 1.2).

**The ruling's figure and the language set do not agree, and that is a real open point rather than a typo.**
Decision D was ruled to "five independent, corpus-enforced libraries", and its rejected option Db names those five as Rust, TypeScript, Swift, Kotlin and Go.
Python was built afterwards, so the language set is six while the ruled figure stays five.
Five libraries exist today and they are not Db's five, because Python is among them and Go is not, so the matching count is a coincidence rather than the question closing.
`README.md` therefore states the counts by enumeration and restates no total; do not "fix" either number without a ruling, because whichever one you change decides the question.

**That ruling carries an obligation on HOW each one is written, and it is the reason the option was worth choosing.**
An implementation is written from `docs/spec/roax-canon-1.md`, and its author does not read another implementation while writing it.
The two reference implementations under `corpus/tools/` exist precisely because they were written independently of each other, and their agreement is the only evidence the specification says one thing.
A library produced by reading an existing one passes the corpus while destroying what a pass means.
Validate against the corpus AFTER writing a thing, never while writing it.

`corpus/tools/` holds two small reference implementations, in Python and in plain `.mjs`.
**They are corpus tooling and they are not roax-lib.**
They exist to generate and check the vectors and they are deliberately parser-only, error-code-only and unoptimized.
Do not promote them into a library, do not import them from one, and do not fold them into `src/`.
If you need a further implementation for cross-checking, add another single-file one.

### The TypeScript library

`src/` is the library, `conformance/` is its corpus runner, `test/` is its unit tests.
See [`src/README.md`](src/README.md).

**`package.json` and `tsconfig.json` now exist, and an earlier version of this file gave their absence as a rule.**
That rule was "a TypeScript package here would read as the beginning of a library", and it is superseded because the library is now deliberate rather than accidental.
It is superseded **only for the five libraries that exist**, whose manifests are `rust/Cargo.toml`, the root `package.json`, `python/pyproject.toml`, `swift/Package.swift` and `kotlin/settings.gradle.kts`: adding a `go.mod` is still the thing not to do without an instruction.
The package is zero-dependency at runtime - `node:crypto` supplies SHA-256 and the CSPRNG - and TypeScript plus `@types/node` are the only devDependencies.
Ajv is still installed OUTSIDE the tree and named by `ROAX_AJV`, as the schema-validation section below describes; do not add it here.

**The five builds are independent BY METHOD and identical BY REQUIREMENT.**
Write each from `docs/spec/roax-canon-1.md`.
Do not read `corpus/tools/roax_ref.py`, `corpus/tools/roax_ref.mjs` or `corpus/tools/check_corpus.mjs` while implementing one - `check_corpus.mjs` imports a reference implementation, so reading it is reading that implementation.
Their agreement is the only evidence the specification says one thing, and an implementation written by reading one is a port wearing the costume of a third opinion.
Validate against the corpus **after** writing a module, never while.
The bar is byte-identical results on every vector, and a difference is a finding to escalate rather than a variance to tolerate.

**Findings from that build are in [`docs/typescript-implementation-findings.md`](docs/typescript-implementation-findings.md), and three of them are things a future implementer will hit in any language.**

- **The corpus can only be passed through a type-map format this repository forbids for resolution.**
  Every vector needing a map resolves against `corpus/type-maps/<recordType>.json`, which is the display-pattern format `schemas/type-map-1.0.json` calls superseded and says MUST NOT be used to resolve.
  There is no published artifact for `org.roax.corpus.synthetic` at all, so no structured-path DFA can resolve a single corpus record.
  Under specification section 1.1 that is a release-blocking corpus defect.
  Build the resolver behind an interface and say so; do not quietly treat the display-pattern format as operative.
- **Specification section 3.3's empty-container rule is unsatisfiable against the committed corpus,** measured at exactly 2 vectors of class 5.
  `a.b` carries an empty array and an empty object in those fixtures, and the synthetic map declares `a.b` for `jsonKind: "null"` alone, so under the specification's rule both records fail closed and have no root.
  Expose both readings rather than picking one silently.
- **Section 10 step 1 cannot be discharged for `hl7.fhir.bundle`**, because `corpus/type-maps/` carries no map for it while eight of the nine class-14 `hl7.fhir.bundle` fixtures disclose a `resourceType` record leaf, across both the `floor-` and the `typemap-floor-` families.
  **That count is hand-maintained in four places** - here, `docs/typescript-implementation-findings.md` finding 3, `src/envelope.ts` and `conformance/run.ts` - and all four went stale together the moment the `typemap-floor-*` family was added, which is the defect underneath the figure rather than the figure itself.
  The follow-up is to give it ONE source, derived from the fixtures at runtime or stated once and cited from the other three; do not close the gap by adding a fifth copy.

Run it with `npm run conformance`.
`ROAX_REFERENCE_RECORDS=<dir>` runs class 10 against records extracted from a reference checkout with `corpus/tools/extract_reference_record.py`, which is a data-extraction utility rather than a reference implementation and is therefore safe to read while building one.
Without it every class-10 assertion reports NOT RUN with its reason, and is never counted as passed.
**The filename inside that directory must be `<authority>.<profile>.json`**, for example `sg.gov.moh.recovery-healthcert.json`: the vector names only the path inside the reference checkout and the extraction utility writes wherever `--out` says, so the name is the runner's contract and a mismatch is reported as NOT RUN naming the exact path probed.
**Class 10 now needs TWO records**, recovery and `sg.gov.moh.vaccination-healthcert.json`, since the vaccination bindings were ruled.
Rust's corpus test reads the same directory but names each file by its EXPORT instead - `sampleDocument.json` and `sampleVaccineHealthCert.json` - through `ROAX_EXTRACTED_RECORDS`; the two conventions are separate and a directory can satisfy both.
Swift follows the `<recordType>.json` convention, through `ROAX_REFERENCE_RECORDS` for `swift test` and `--references` for `swift run roax-conformance`.
Kotlin's runner probes BOTH names under `ROAX_REFERENCE_RECORDS`, so one directory now satisfies all four runners.

### The Swift library

`swift/` is a SwiftPM package: `Sources/ROAXCanon` is the library, `Sources/ROAXCanonCorpus` is the corpus runner, `Sources/roax-conformance` is its command-line front end and `Tests/ROAXCanonTests` is the suite.
See [`swift/README.md`](swift/README.md) and [`swift/FINDINGS.md`](swift/FINDINGS.md).
Build and gate it with `swift build --package-path swift`, `swift test --package-path swift` and `swift run --package-path swift roax-conformance`.
It passes 504 of 504 vectors with a reference checkout and reports exactly the four class-10 vectors NOT RUN without one, exiting 2 rather than 0 so a bare run does not read as a pass.

**The runner is a LIBRARY target rather than only an executable, and that is deliberate**: it makes `swift test` a real gate over the committed corpus instead of a second suite that could pass while the corpus failed.

**`EmptyContainerPolicy` defaults to the SPECIFICATION reading and the runner opts out of it explicitly.**
Specification section 3.3 requires the map to authorize EMPTY_ARRAY and EMPTY_OBJECT; the committed corpus does not implement that, so the runner selects `.assignedWithoutMapAuthorization`, prints which reading it used, and a test pins the cost at exactly the 2 class-5 vectors `python/FINDINGS.md` item 1 already measured.
Do not flip the default to make something green.

**SHA-256 has two implementations in that package on purpose**: CryptoKit where it exists, and `ReferenceSHA256` otherwise, with a test asserting they agree across every block boundary.
That pair is an asset rather than drift only because the test exists, so do not delete it when touching either.

**The `roax.typeMap.id` binding is triggered by the COMMITTED leaf, never by the outer `typeMap` member, and that direction is the whole point.**
Gating it on the outer member put the trigger in the hands of the party the check constrains, so a holder could delete the member, withhold the leaf and have the binding never run - and the same optional drove the minimum-disclosure floor, so nothing asked for it either.
`EnvelopeVerifier` now binds whenever either side names a type map and sources the floor from the leaf; do not reintroduce a presenter-controlled gate.
The residual case - a copy dropping BOTH, which is byte-indistinguishable from a legitimate envelope-1.0 copy because `leafCount` is not authenticated in a disclosed copy - is `TypeMapBindingPolicy`, defaulting to `.boundWhenPresent` so the 1.0 corpus still passes.
`.required` is enforced on BOTH copy kinds, because a knob whose documented meaning holds on one path only is a false promise in the API surface, and its refusal carries its own reason code `type-map-not-named` rather than `outer-identity-mismatch`: with neither side naming a type map the two agree, so nothing is mismatched.
Keep those two codes apart when you touch either.
`swift/README.md` enumerates which envelope-2.0 checks that package does and does not implement, and `swift/FINDINGS.md` finding 11 owns the measurement; this is NOT envelope-2.0 support and must not be described as such.

### The Kotlin library

`kotlin/` is a two-module Gradle build: `roax-canon` is the library and its tests, and `roax-canon-android` packages the same `src/main` as an AAR without a second copy of the code.
See [`kotlin/README.md`](kotlin/README.md), and [`kotlin/FINDINGS.md`](kotlin/FINDINGS.md) for what the build found.
Run it with `gradle -p kotlin :roax-canon:test`, which runs the corpus and every other test; it passes 504 of 504 vectors with zero NOT RUN once `ROAX_REFERENCE_RECORDS` is set.

**Three things about this module are easy to get wrong.**

- **`java.math.BigDecimal` must not be used for canonical numbers, and it is the trap because it looks correct.**
  It is arbitrary-precision, so it reads as the right tool, but its `toString` emits scientific notation the section 6.2 output grammar does not admit (`1e2` renders `1E+2`), its parser accepts `+1`, `007`, `.5` and `5.` which the ROAX grammars reject, its `equals` compares scale, and `1.4e+9999` has to be materialized before it can be measured against the 1024-digit bound.
  `toPlainString()` reproduces all seven worked examples in section 6.2, which is exactly what makes it dangerous.
  `JvmPlatformTrapTest` pins every one of those as an assertion about the JDK.
- **The Unicode version is a property of the runtime and cannot be pinned from inside the library.**
  Section 6.1 pins 15.1; JDK 17 ships Unicode 13.0 and JDK 25 ships 16.0, and no installed JDK has 15.1.
  `Nfc` is therefore injectable and declares its version, and the corpus runner prints the comparison every run.
  Measured: all 504 vectors pass under both JDKs, and the digest over the NFC forms of every string in the corpus is byte-identical on both, pinned as a live guard by `PlatformNfcTablesTest`; `kotlin/FINDINGS.md` section 2 owns the counts.
  **That digest is over the corpus's strings, so it moves whenever the corpus grows.**
  Re-derive it by running the test on BOTH JDKs and re-pinning only if they agree - re-pinning from one runtime silently retires the cross-version comparison, which is the whole point of the constant.
  Re-run the other one with `-Proax.testJdk=25`.
- **The Android module is optional by design and is gated on an SDK actually being present.**
  This repository has no CI, so a contributor touching only canonicalization must not need an Android SDK; `-Proax.skipAndroid=true` forces the JVM-only configuration.
  The Android claim is checked WITHOUT an SDK by `AndroidApiSurfaceTest`, which reads the compiled constant pools and asserts every referenced JDK type exists on Android API 21+.
  That is what keeps `java.util.Base64` (API 26+) and `java.util.HexFormat` (absent on Android) out, which is why the library hand-rolls both.

## The corpus gates the PRODUCING side too, since class 20

**Every class except 20 runs an implementation's VERIFIER against bytes `corpus/tools/build_corpus.py` wrote.**
Nothing asked a library to PRODUCE an envelope, so a library could issue a disclosed copy its own verifier refused and pass every vector - and one did, for `disclosed-leaf-named-without-value`, which is itself a committed vector.
Class 20 issues from a record and a committed salt set, discloses a named path set from the same commitment, compares BOTH produced envelopes against committed copies, and verifies them through the producing implementation's own verifier.
`docs/conformance-corpus.md` class 20 owns the definition and `corpus/README.md` owns the measurement.

**Three things about it are easy to get wrong.**

- **The comparison is SEMANTIC, never byte-for-byte.**
  JSON member order, whether `displayPath` is emitted, and the order of the `disclosure.leaves` array are not fixed by the specification, so asserting them fails a conforming implementation for something nothing requires.
  What must survive is every number's SOURCE TEXT: implementation B's own class-20 runner failed its own full copy with `root-mismatch` the first time, because it rebuilt the envelope with `JSON.parse` and turned `0.010` into `0.01`.
  Section 7.3 says the section 6.4 parser requirement applies to the ENVELOPE and not only to a bare record, and that is exactly this.
- **Every class-20 vector commits `roax.typeMap.id`, and that is forced rather than chosen.**
  Section 11.2 marks the leaf emitted ALWAYS, so an issuance without one is not something the current specification permits; `schemas/envelope-1.0.json` keeps the member optional for envelopes ALREADY issued under it, which is what the other 65 envelope fixtures are.
  A vector without one would ask an implementation to produce an envelope the specification forbids.
- **EMPTY_ARRAY and EMPTY_OBJECT are deliberately absent from the round-trip record.**
  NULL already covers the no-value carrier, and adding an empty container would raise the "exactly 2 class-5 vectors" figure that `python/FINDINGS.md` item 1, `swift/FINDINGS.md` finding 8 and `docs/typescript-implementation-findings.md` all state.

**A vector GROUP a runner does not read is worse than a class with no vectors, and every runner now fails on one.**
An unknown group reads as zero vectors and reports the same green as before it existed, and the per-class report cannot see it either.
`corpus/tools/check_corpus.mjs` and the TypeScript, Python, Swift and Kotlin runners each hold an explicit consumed-group list; `rust/tests/conformance_corpus.rs` uses serde `deny_unknown_fields`, whose default of IGNORING an unknown member is precisely the quiet skip.
Add a group to the corpus file and every runner goes red until it is consumed - which is the intended order, and is why the guard was added before class 20 rather than with it.

**`build_corpus.py --draw-missing-salts` is the flag to use when ADDING fixtures.**
`--draw-salts` redraws EVERY committed set, which changes every root in the corpus and buries an additive change in a corpus-wide diff.
`TREE_LEAF_DOMAIN_VERSION` is pinned at `1.0.0` and deliberately decoupled from `CORPUS_VERSION` for the same reason: it used to interpolate the corpus version, so any addition rewrote all 173 tree, 165 inclusion and 11 negative-proof vectors.
Do not re-couple them.

## Leaf ordering is SELECTABLE per record, and `path` is the default

**Specification section 9 defines two orderings and the amended decision D5 rules both first-class**, mirroring decision B's shape for hash algorithms: `path` sorts leaves by ascending `encodePath` bytes, `hash` by ascending `leafHash` bytes.
The trade is a genuine one and neither dominates: `path` admits absence proofs and leaks gap counts, `hash` leaks nothing about position and **forecloses absence proofs permanently** for records issued under it.
Decision D6 is amended to say so - the capability is preserved for `path`-ordered records and is impossible rather than undefined for `hash`-ordered ones.

**The whole change is ADDITIVE to the committed corpus, and the reason is worth keeping.**
`path` contributes the EMPTY domain suffix, so a path-ordered record's `DOMAIN` is byte-identical to what `ROAX-CANON/1` computed before the axis existed, and `roax.ordering` is emitted only for a non-default ordering.
Not one committed expected value moved: 501 vectors to 504, with 174 existing vectors gaining a declared `ordering` field.
**Do not "fix" that asymmetry into symmetry.**
Giving `path` a non-empty suffix, or emitting the leaf always, changes every leaf hash of every record already issued under `ROAX-CANON/1`, which is a version-2 change wearing a version-1 label.
It is also infeasible in this tree: the four class-10 vectors cannot be recomputed without the gitignored reference checkout, so a build that moved them would delete them.

**Four things about the implementation are easy to get wrong.**

- **Salts are assigned in `encodePath` order under BOTH orderings**, and only tree PLACEMENT differs.
  A leaf hash is computed over its salt, so assigning salts in tree order is circular under `hash`.
  Kotlin's `commitWithSaltsByPath` learns the order from a placeholder-salt pass and then consumes real salts positionally; once `commit` returned tree order that pass gave a hash order over placeholder salts, and every salt would have paired with the wrong leaf and produced a plausible wrong root rather than an error.
  Under `path` the fix is the identity, which is why nothing could see it before.
- **Equal leaf hashes are REJECTED under `hash` ordering, never tie-broken.**
  Paths are already unique and every variable component of the section 8 preimage is length-prefixed, so two equal hashes are a collision; tie-breaking by path would absorb evidence of a broken hash into a well-defined tree and hand back a root.
- **`roax.ordering` is a reserved leaf and is NOT AUTHORITY, and both halves must be stated together.**
  It departs from section 7.4's rejection of a `roax.hashAlg` leaf deliberately, and section 11.2 argues the departure: 7.4's leaf was dangerous because weak hash algorithms exist and it enabled a downgrade, whereas both orderings are equally strong, so this one is redundant rather than dangerous and what it buys is committed issuer intent.
  A verifier MUST take the ordering from the anchoring registry (section 9.5, H2), never from the leaf or the envelope member.
  Rust models this properly: the envelope's `ordering` member is accepted for shape and never read, and `VerificationPolicy::anchored_ordering` is the only source.
- **Where the ordering is needed is narrower than it looks, and section 9.6 owns it.**
  A DISCLOSED copy carries each leaf's index and the tree is never rebuilt, so the ordering is needed for the **leaf preimage** only - exactly as `hashAlg` already is - and for nothing structural.
  That is what makes `hash` ordering's position privacy real: a disclosed index is a position in leaf-hash order and reveals nothing about record shape.
  Do not describe H1 as buying more than it does: a leaf is bound to exactly one ordering, so the same leaf set cannot be reassembled into the other tree, and that is real and narrow.

**Class 21 is the enforcement.**
Three vectors, each one record under BOTH orderings, asserting two roots that differ AND two **disjoint** leaf-hash sets.
Disjointness is the stronger assertion and is what H1 buys; a runner checking only the roots would pass an implementation that permuted one leaf set into the other tree.
One salt set serves both sides, drawn over the hash-ordered superset, because two sets would make the roots differ for a reason unrelated to ordering.

**Adding a group went red in every runner before it went green, which is the intended order.**
Rust's `deny_unknown_fields`, and the explicit consumed-group lists in the other four plus `check_corpus.mjs`, all failed until each consumed `ordering`.
**The per-vector `ordering` FIELD needed a separate guard**, because a field inside a group a runner already reads is invisible to the group check: every runner now ASSERTS the declaration and refuses a vector that omits it.

## The type-map binding is triggered by what is COMMITTED, in all five libraries

**The governing rule, and it generalizes:**

> **A check whose execution is controlled by the party it constrains is not a check.**
> The trigger must come from what is COMMITTED, never from what was PRESENTED.

`roax.typeMap.id` is mandatory to disclose BY ARITHMETIC (section 11.2), because it selects and authenticates the exact map.
The outer `typeMap` member is optional under `schemas/envelope-1.0.json`, which makes "bind when the member is present" the obvious reading and the wrong one: a holder deletes the member, withholds the leaf, and the binding never runs while every inclusion proof stays genuine.
Every library now binds when EITHER side names a type map, and absence on one side is the same `outer-identity-mismatch` as disagreement.

**The residual case is a copy that drops BOTH, and it is unreachable rather than unhandled.**
It is byte-indistinguishable from a legitimate envelope-1.0 copy, because the only signal that a further reserved leaf was committed is `leafCount`, which section 11.1 measured is NOT authenticated in a disclosed copy.
The 34 committed floor fixtures ARE that shape, so a library that hard-rejects it fails class 14; what closes it is `schemas/envelope-2.0.json` requiring the member, and each library exposes a verifier-side opt-in for a deployment that accepts 2.0 only.

**What extending the corpus found in the three libraries that shipped before any of this was known.**
Report these as findings rather than as history: each is the same defect shape, and each was invisible to 488 vectors.

- **Python had no binding at all** and accepted all four attacks.
  Its blanket `RESERVED_V2` refusal was also too wide - an issuer supplies the content ID and reproduces nothing - and narrowing it is what let it issue at all.
- **Kotlin bound only when its verifier was configured to**, and separately emitted AND read the tag-5 BYTES disclosure carrier as base64 rather than lowercase hex.
  No committed disclosed fixture carries a BYTES leaf, so only class 20 could see the second.
- **Rust was not exploitable but refused for the wrong reason**: its runner chose the envelope generation from the presenter-supplied member, so the stripped-member copy tripped the reserved-namespace guard instead of the binding.
  `reserved_leaf_set_for` now selects from committed evidence.

**And the finding that is worth more than any of them.**
The TypeScript library refused to ISSUE an envelope without `roax.typeMap.id`; the Python library refused to issue one WITH it.
Two shipped libraries held mutually exclusive issuance rules and both passed all 488 vectors, because no vector had ever asked either to produce anything.
Section 11.2 settles it - the leaf is emitted ALWAYS - so TypeScript was right.

**`hashAlg` is carried twice wherever a verifier has an anchoring registry, and a disagreement is a REJECTION.**
Rust, TypeScript and Python already rejected it; Kotlin read `config.anchorHashAlg ?: env["hashAlg"]` and silently preferred the registry, so an envelope declaring `Poseidon-BN254` verified under SHA-256 - an issuance section 7.4 forbids, accepted without a word.
Swift's is a different pair, because its verifier is generic over the hash type: the declared name and the computing function are independent carriers there and `envelope.hashAlg == H.identifier` is what holds them together.
The corpus cannot reach any of this - class 18's registry rows are the named gap section 2.2 blocks - so `kotlin/SpecificationGapTest` carries it.

**No emitter may GUESS a `typeMap` version, and the three that write one refuse rather than substitute.**
`schemas/envelope-1.0.json` requires the member to carry `id` and `version` together, and the version is metadata the issuer holds rather than anything a library can derive, so an issuance naming the artifact without its version has nothing valid to write.
TypeScript substituted `1.0.0`, Kotlin coerced an absent version to the empty string, and Python emitted the identifier alone; all three now fail closed on their envelope-shape code, with the same reason at the same point as their existing refusal of an issuance naming no artifact at all.
Rust cannot express the case, because `TypeMapDescriptor` carries both fields as non-optional, and Swift emits no JSON at all, so it holds whatever a caller supplies.
No vector can see any of this - every class-20 vector supplies a version - so the three refusals are pinned by each library's own tests.

**A KNOWN envelope member present with the WRONG JSON TYPE must never read as ABSENT.**
`"salts": {}` beside a `disclosure` parses to nothing in a naive reader, so the salt-leak guard never fires and the copy verifies while carrying it: a guard that turns itself off on malformed input is worse than no guard.
`salt-leak-disclosed-copy-with-wrong-typed-salts` is the vector, and all five libraries reject it - TypeScript as `envelope-malformed` and Swift as `malformed-json`, both one layer earlier than the references, each with a declared PER-VECTOR equivalence rather than a code-wide one, because `disclosed-copy-carries-salts` is correct for the sibling vector.

## This repository is PUBLIC

Consequences that have already bitten once during authoring:

- No task identifiers, no internal team vocabulary, no absolute paths into anyone's home directory or into internal working trees.
- The reference schemata at `references/` are **third-party and must never be committed.**
  `.gitignore` excludes `references/` and `schemata/`.
  Cite them by relative path plus the upstream commit; never copy a schema in, not even a fragment.
- dogtag is an internal repository.
  Cite it as `dogtag-mono-repo` with file and line, and do not link it.

## Sharp edges in the design itself

These are the things a future agent is most likely to get wrong.

- **Four base type maps are published in `type-maps/`.**
  They were generated from the pinned reference checkout by `tools/build-type-maps.mjs`, which loads schemas by file path rather than `$id`.
  Neither regeneration nor `--check` runs today - both fail closed on the object-branch disagreements described below - so the committed bytes are authoritative and `tools/check-type-maps.mjs` is what verifies them.
  Their exact coverage and unresolved paths are in `docs/type-maps.md`.
  Do not infer a tag syntactically for any unbound path - decision D7 requires it to fail closed.

- **The operative type-map matcher is a structured-path DFA, not a display-pattern table.**
  Resolve NFC-normalized KEY and INDEX segments, then select one output by observed JSON kind.
  A missing transition or output fails closed.
  The map must authorize a path before the flattener emits EMPTY_ARRAY or EMPTY_OBJECT, or an unknown empty extension bypasses D7.
  **The committed corpus does not implement that authorization rule**, so an implementation that follows the specification here fails two class-5 vectors that assert a root the rule refuses.
  The narrow fix is a corpus edit rather than an implementation default, and it is measured in `python/FINDINGS.md` item 1.

- **The exact effective type map is committed per record.**
  The envelope's `typeMap.id` selects immutable artifact bytes and is itself committed at the single-segment reserved path `KEY("roax.typeMap.id")`.
  The semver is exact metadata, not a latest-version selector.
  Issuer extensions are materialized, single-parent, issuer-scoped and additive; they never override an inherited transition or output.
  See specification section 4 and `docs/type-maps.md` sections 3 through 5.

- **Issuer extensions need executable validation, not only a carrier schema.**
  Run `tools/check-type-map-extension.mjs` against the exact parent and child.
  It checks logical DFA additivity, exact parent identity, issuer scope, extension-point containment, canonical reachability and provenance-reference linkage.
  Every selector must cite an immutable supplemental source, and its materialized binding must cite every evidence source by `sourceId`.
  Publication review still retrieves each source and verifies its commit or content digest.
  Its `--self-test` mode covers those rejections without any external artifact.

- **The artifact schema's URI format and the executable checker do not accept exactly the same strings.**
  Ajv accepts `https://` under the schema's `format: "uri"`, while the checker rejects it through WHATWG `new URL` (`schemas/type-map-artifact-1.0.json:171-174` and `:203-206`; `tools/check-type-map-extension.mjs:321-328`).
  The Rust artifact loader follows the executable checker for that demonstrated edge (`rust/src/type_map.rs:1200-1202`; `rust/tests/published_type_maps.rs:518-532`).

- **Issuer-scope membership does not state a Unicode comparison rule.**
  The specification requires the disclosed issuer identity to be a member of `scope.issuerIds`, while the executable extension checker compares inherited scope strings byte-for-byte and neither source says whether to NFC-normalize the membership check (`docs/spec/roax-canon-1.md:912-913`; `tools/check-type-map-extension.mjs:890-900`).
  The Rust loader rejects every issuer child artifact until it has exact parent/additivity inputs, so this ambiguity cannot silently select an issuer in the current API.

- **An extension point does not open the whole subtree beneath it.**
  A `prefix` admits only two selector shapes: a segment the base map does not declare at that prefix state, and then anything below that untyped subtree; or a direct child of the prefix, exactly one segment deeper, that has no binding for the observed kind **and carries an explicit `unresolved` row naming that kind**, such as vaccination `dose`.
  So the PDT and recovery empty root prefixes reach undeclared root properties, not the shared lite FHIR Bundle, and no issuer can privately bind `base64Binary` or `Narrative.div`.
  Rebinding a declared path is a base-map revision.
  See `docs/type-maps.md` section 5.

- **`unresolved` rows are operative for the extension lifecycle, not just audit prose.**
  They gate shape 2 above, so silence is not eligibility: PDT `type` has no `array` binding and no row, and is therefore not extensible.
  A child must carry every inherited row unchanged except for kinds it resolves with a binding - it may not invent a row, restate one with its own evidence, or drop one it did not resolve.
  Do not describe them as purely non-operative anywhere.

- **`tools/check-type-maps.mjs` is the only TYPE-MAP checker that runs against the committed tree.**
  `build-type-maps.mjs --check` needs the gitignored reference checkout and still fails closed on the 34 object-branch disagreements once it has one; this one needs neither and passes.
  It was the only checker of any kind that ran against the committed tree until `tools/reflow-markdown.mjs` was added, which also needs nothing outside the tree and also passes on it; the qualifier is there so the two do not read as a contradiction.
  It recomputes the content IDs, validates the four artifacts and the registry against their JSON Schemas, exercises both branches of the artifact schema's `parentTypeMapId` conditional in both directions, reuses `validateArtifact` from the extension checker rather than re-encoding the carrier rules, and pins a set of operative and fail-closed bindings.
  It needs Ajv 8 and `ajv-formats` installed outside the tree and named by `ROAX_AJV`; `--skip-schema-validation` runs the dependency-free subset.
  See `docs/type-maps.md` section 6.

- **The FHIR schemata use object keywords without declaring object type.**
  The full schema has 659 reached object-applicator source nodes with no `type: "object"`, and the Bundle-reachable lite scope has 65.
  The maps retain KEY traversal, mark the affected states as non-operative audit gaps, and never infer a scalar, array or null tag from an inapplicable object keyword.
  See `docs/type-maps.md` section 1.5.

- **The generator rejects schema intersections and mixed empty-container permission, for objects and arrays alike.**
  Its DFA closure can safely union the pinned `anyOf` and `oneOf` path languages only because complete profile validation runs first.
  An `allOf` needs intersection-aware compilation, and container branches that disagree on whether empty is admitted need combinator-aware evaluation, so `tools/build-type-maps.mjs` fails instead of publishing a guessed EMPTY_OBJECT or omitting a valid EMPTY_ARRAY.
  EMPTY_ARRAY and EMPTY_OBJECT are distinct leaves, so a permissive union is silent widening.
  **Both comparisons select a branch by container-ness, which is the declared type OR the applicator keyword**: `type: "object"` or `properties` on the object side, `type: "array"` or `items` on the array side, which are the same keywords `classifyNode` already treats as container markers when it declines to tag a node.
  Selecting on the declared type alone drops `{"items": {...}, "minItems": 1}` out of the comparison, and selecting on the applicator alone drops `{"type": "object", "required": ["x"]}`; either way the surviving permissive branch publishes an empty-container leaf unopposed, which is the widening itself.
  **The admission predicates must cover every keyword of the pinned dialect that can forbid the empty container, or the comparison compares the wrong answer.**
  For objects that is a non-empty `required` and `minProperties`; `dependencies` and `propertyNames` pass vacuously on `{}`.
  For arrays it is `minItems` **and `contains`**, because draft-06 section 6.14 and draft-07 section 6.4.6 both require at least one matching element and `[]` has none.
  A node whose only container keyword is `contains` needs no selector clause: `classifyNode` leaves it unresolved for every kind, and an unresolved kind suppresses that kind's binding, so the state already fails closed.
  **The three sets are not the same set, and the object and array sides differ.**
  The COMPARISON is the widened container-ness set on both.
  TRAVERSAL is narrow on both: `keyGroups` skips a selected branch declaring no `properties`, and `anyIndex` comes only from the `items` of `type: "array"` branches.
  EVIDENCE differs - an EMPTY_ARRAY binding cites only `type: "array"` branches, because an `items` keyword on an untyped node constrains arrays without asserting the instance is one and inferring a tag from an inapplicable keyword is what section 1.5 of `docs/type-maps.md` forbids, whereas an EMPTY_OBJECT binding cites the widened set, so a bare `{"type": "object"}` is cited.
  That is not the same defect: a declared `type: "object"` does assert object-ness, so the tag still comes from declared schema evidence.
  `expectNoTag` pins the array half.
  `--self-test` proves both rejections against constructed schemas and needs no reference checkout, and on each side one case drops the applicator from a branch and another drops the declared type, so both halves of both disjunctions are pinned rather than assumed.

- **The object rejection above means the four published artifacts can currently be neither regenerated nor `--check`ed, and that is the ruled trade.**
  `--check` compiles before it compares, so it fails on the same states.
  Measured on the pinned checkout, it fires on 34 states: 30 full FHIR, 2 PDT, 2 recovery, 0 vaccination.
  **That count is now a LOWER BOUND**: it was measured under the earlier declared-type-only and `properties`-only branch selections, and widening both to container-ness can only add branches to a state's comparison, never remove one.
  The array comparison was widened after that measurement too, so the bound now covers array states as well.
  It has not been re-measured because `references/` is gitignored, and regeneration is blocked either way.
  The first merges `ImplementationGuide_Definition`, which requires `resource`, with `Reference`, which admits `{}`.
  Do not "fix" this by restoring the permissive union - that ruling was raised with this measurement and reaffirmed.
  The committed artifacts and their content IDs stay authoritative and `tools/check-type-maps.mjs` still passes on them; what is open is how to evaluate those 34 merged states combinator-aware so regeneration works again.
  Note the detected condition is broader than the strictly `oneOf`-unsound one: with one permitting and one requiring branch, `{}` is valid under both combinators, whereas two or more branches all permitting `{}` is the case `oneOf` actually rejects.

- **Numbers are never parsed through a float.**
  Anywhere.
  This is the whole point of the design; see `docs/decisions.md` part 0.
  In test vectors and JSON Schemas, INTEGER and DECIMAL values are carried as **strings**, because a JSON number in a vector file would be destroyed by the very parser under test.
  Every value carrier in `schemas/conformance-corpus-1.0.json` now `$ref`s `carrierValue`, which makes a JSON number **unrepresentable at any depth** rather than merely discouraged in a description.
  The one deliberate exception is the envelope's `record` property: a full copy carries the record in its original JSON form, numbers included, so constraining it would be wrong and the spec section 6.4 parser requirement is what protects those literals.

- **Trailing zeros in decimals are significant.**
  `0.010` is not `0.01`.
  FHIR R4 says SHALL.
  dogtag strips them (`crates/dogtag-standard-rs/src/encode.rs:51-59`) and ROAX deliberately does not.
  If you port anything from dogtag's `encode.rs`, this is the line to change.

- **The display path is never hashed.**
  `a.b[0].c` is for humans.
  Hashing uses the length-prefixed structured encoding (spec section 5).
  Never reconstruct a path by parsing a display string.

- **The specification does not say whether NFC-colliding sibling keys must be rejected when their descendant leaf paths remain distinct.**
  It requires raw map keys to be unique and normalizes each encoded KEY segment, so `{"é":{"a":1},"é":{"b":2}}` has no duplicate raw key and no duplicate complete encoded leaf path (`docs/spec/roax-canon-1.md` sections 3.2, 3.3 and 5).
  The Rust implementation rejects duplicate complete encoded leaf paths but accepts this disjoint-descendant shape, and no committed vector distinguishes that reading (`rust/src/commitment.rs:611-619`; `corpus/README.md`, specification ambiguity 6).

- **The leaf set is a union, not the record.**
  Reserved `roax.*` leaves join the record's leaves before the sort (spec sections 3.3 and 11.2).
  A flattener that walks the record only produces a different root.
  Each reserved path is a **single `KEY` segment carrying the literal dotted name**, so `roax.recordType` is one segment `KEY("roax.recordType")` and *not* two.
  There are five mandatory reserved leaves, including `roax.typeMap.id`, plus `roax.issuer.keyId`, which is the one conditional leaf: absent means no leaf, not a NULL leaf.
  The tree floor is therefore 6.

- **The reserved-namespace guard tests the NFC-normalized key of the FIRST segment** for the ASCII prefix `roax.` (spec section 11.2).
  Three ways to get it wrong: reconstructing a display path to run it (the section 5.2 trap), applying it to every segment rather than the first, and checking raw bytes before NFC.
  A key named `roax` or `roaxX`, with no dot, is **accepted** - it collides with nothing.

- **`DOMAIN` is algorithm-qualified:** `"ROAX-CANON/1/" + hashAlg`, not a bare `"ROAX-CANON/1"` (spec sections 7, 7.4, 8).
  But `hashAlg` is **not** a leaf and must never become one: a leaf is hashed under the algorithm it names, so it cannot bind it.
  Authority comes from the anchoring registry and the verifier's allow-list.
  Only SHA-256 has a defined construction; Poseidon-BN254 is registered but unparameterized and MUST NOT be issued against.

- **Version identifiers defined elsewhere are opaque** and carry no shape constraint: `schemaVersion` and `unicodeVersion` are matched for equality, never parsed or ordered (spec section 12.1).
  No dotted-numeric pattern accepts even FHIR's own 22 `fhirVersion` values.
  ROAX's own artifacts, `corpusVersion` and `typeMapVersion`, keep semver.
  Do not harmonize the two groups.

- **An unresolved path is bound by a ruling, not by a resolver improvement, and five were RULED on 2026-07-30.**
  Each ruling carries an EVIDENCE GRADE and the grades are load-bearing: keep them when you cite one, because a Moderate ruling and a Decisive one must not read alike.
  `dose` INTEGER (Strong) plus a positive-integer profile narrowing; `expiryDateTime` STRING (Moderate, resting on a profile declaration and NOT on the schema); FHIR `base64Binary` BYTES over the decoded octets (Strong); FHIR `Narrative.div` STRING over the escaped XHTML text, unparsed (Decisive); FHIR primitive-array null placeholders getting NO NULL binding and the record REJECTED (Decisive).
  Full evidence in `docs/type-maps.md` sections 1.1 and 1.3.
  **The two vaccination rulings are operative in the CORPUS-SIDE map class 10 resolves against, and that is what unblocked its sample**, so class 10 is 2 of 3 records.
  **NOT ONE of the four ruled BINDINGS is in the published `type-maps/` artifacts yet, and all four of those artifacts lag**, because regeneration is blocked on the 34 merged object states below and `tools/build-type-maps.mjs` has no ruling table at all.
  The fifth ruling is the null-placeholder one, which is expressed as an absence and is therefore already in force.
  `docs/type-maps.md` section 1.6 states why hand-editing a generated artifact is the wrong fix and what the next change must do.
  Do not "finish" them by editing artifact bytes.
  **PDT is still uncommittable**, on the 20 endorsed-sample `(pattern, kind)` pairs its open root leaves undeclared (`docs/type-maps.md` section 1.2).
  Those need a versioned composition profile rather than 20 authored bindings, and nobody has ruled one.
  A ruling lands in `docs/decisions.md` or a profile document and the type map together.
  Do NOT quietly bind an unruled path to make class 10 green: `docs/conformance-corpus.md` section 1.2 exists because that kind of fix decides an open question from inside a data file.
  `corpus/tools/build_type_maps.py` holds its rulings apart from the schema walk and refuses to build if one names a path the walk did not independently report unbound, or collides with a binding the schema determines.
  Keep that guard.
  Note the tool split when citing any of this: `corpus/tools/build_type_maps.py` is corpus-side and writes the vectors' maps, while the published `type-maps/` artifacts come from `tools/build-type-maps.mjs`.

- **A value-domain rule is NOT a type map and NOT in the canonicalization layer, and that is ruled.**
  The `dose` ruling narrows the field to a positive integer, which no tag can express.
  Specification section 4.2 orders profile validation BEFORE map resolution, and decision D13a keeps value-domain validation in "a separate, independently versioned conformance layer".
  So the rule is declared by `docs/profiles/vaccination-healthcert.md` section 6, executable in `corpus/tools/profile_rules.py` and `profile_rules.mjs`, self-tested by `run.sh` step 5, and demonstrated through Rust's `SchemaValidator` seam.
  Do not move it into a type map, into `roax_ref.*`, or into any of the five libraries: that merges two layers a ruling separated.
  The discriminating values are `0` and the negatives, because a fractional value is already refused by the section 6.2 INTEGER grammar.

- **The corpus may not require what the design has not decided.**
  A required corpus field that presumes one side of an open decision silently rules it (`docs/conformance-corpus.md` section 1.2).
  This happened twice with `masterSalt` before decision D4 was ruled.
  The rule still binds, but no longer on a lettered decision: every decision in `docs/decisions.md` is ruled as of 2026-08-02.
  It binds on what is unsettled beneath the rulings, and the three that reach the corpus are the `Poseidon-BN254` parameterization under B, PDT's 20 endorsed-sample pairs, and the undesigned anchoring registry that keeps class 18's registry rows unbuildable.
  D14 is the case that shows it working end to end: the class-19 key vector was withheld while D14 was open and built under the ruling on 2026-07-30, so no implementation ever inherited an unruled answer from a data file.

- **There is no master salt and no KDF.
  Every salt is an independent CSPRNG draw of 16 bytes** (spec section 7, decision D4 ruled D4b on 2026-07-28).
  Do not reintroduce derivation, and do not put the record identifier into any preimage - it was in the salt preimage of an earlier draft and is not any more.
  The 128-bit entropy floor is normative: it is the only thing standing between a withheld low-entropy leaf and a dictionary search.

- **An envelope carries per-leaf salts and nothing a salt could be derived from.**
  A full copy carries the salt of *every* leaf in a `salts` array; a disclosed copy carries the salt of *only the leaves it reveals* (spec section 7.3).
  Both are load-bearing.
  Dropping the first makes a full copy unverifiable; breaking the second leaks every withheld low-entropy field to a dictionary search in an envelope that still verifies correctly.
  Rule 3 of that section forbids any seed field, which is vacuous today and binds any revision that brings derivation back.

- **`roax.recordId` is mandatory to disclose by policy, not by arithmetic.**
  `roax.recordType`, `roax.schemaVersion` and `roax.typeMap.id` are arithmetic because they select and authenticate the exact map.
  This changed with the D4b and type-map binding work, and several documents said otherwise before it.
  A verifier that never receives `roax.recordId` can still verify every leaf it did receive.

- **`leafCount` is NOT authenticated in a disclosed copy**, and the specification claimed otherwise until this was measured.
  RFC 9162 section 2.1.3.2 takes the tree size as an *input*, so an attacker supplying both a leaf hash and a tree size can walk an internal node to the genuine root: on an 8-leaf tree, `MTH(L[0:4])` at index 0 with a forged size of 2 verifies.
  What actually defends is spec section 10 step 2 - recompute the leaf hash from the disclosed fields, never accept one - plus the `0x00` leaf-domain byte.
  Never add a check that leans on `leafCount` in a disclosed copy.
  Spec section 11.1 owns the full measurement and correction.

- **Type tag 8 `BLOB_REF` is defined and selected by nothing.**
  The schemas accept it so the carrier form is pinned once; an implementation MUST reject any record or type map that uses it until a profile declares the binding (spec section 6.5).
  Same treatment as `Poseidon-BN254`: registered, forbidden in issuance.
  Base64 is pinned to RFC 4648 section 4 with padding and no line wrapping, and that governs `BYTES` and `BLOB_REF` rather than the explicitly typed healthcert fields bound as STRING.
  **FHIR `base64Binary` is RULED BYTES over the decoded octets** (grade Strong, 2026-07-30), which makes the pinned base64 form an INPUT-ADMISSIBILITY condition rather than the committed value: the octets are hashed, and a spelling outside the pinned form is rejected before it is decoded.
  Both reference implementations decode at the record boundary now, each by a different mechanism, and `roax_ref.mjs` deliberately does NOT use `Buffer.from(text, "base64")`, which is permissive and accepts all four forms section 6.3 requires rejecting.

- **The vaccination healthcert's `fhirBundle.entry[]` is flattened pseudo-FHIR**, not a real FHIR Bundle.
  Normalizing it to the genuine `entry[i].resource` shape changes every path and therefore every root, which silently breaks existing commitments.
  See `docs/profiles/vaccination-healthcert.md` section 2.1.

- **Do not resolve the reference schemas by `$id`.**
  Two of them carry copy-pasted `$id` values: recovery points at PDT's path, and vaccination points at a PDT interim path.
  A validator that registers both by `$id` silently applies the wrong rules.
  Load by file path.

- **A minimum-disclosure floor is SEGMENTS, never display notation.**
  This is the section 5.2 display-path trap one layer above hashing, and it has already been made once here.
  The `docs/profiles/` tables print non-redactable paths for humans, so `notarisationMetadata.reference` reads as one token and is **two** segments.
  A floor holding the dotted string as a single `KEY` asks for a leaf no record has, so it matches nothing and the floor is *silently unenforced* while every fixture built the same way agrees with it.
  Reserved paths are the one genuine single-dotted-key case (spec section 11.2).
  Carry a floor as segments so the mistake cannot be written.

- **The envelope's outer identity is not authority and must be bound to the reserved leaves.**
  Section 11.3 says fields outside the root are hints; section 11.2 commits `recordType`, `schemaVersion`, `typeMap.id`, `recordId` and `issuer.id` as leaves so a disclosed copy can be checked against them.
  The outer `recordType` is what SELECTS the profile floor, and PDT's floor is a strict subset of recovery's, so an unbound one lets a holder relabel a recovery copy as PDT, withhold `validUntil`, and still have every inclusion proof verify against the genuine root.
  Compare under NFC on both sides: a STRING leaf commits its normalized form.
  `roax.issuer.keyId` MUST NOT be bound - it is the conditional leaf.

- **A selective disclosure derives its context from the sealed commitment.**
  Accepting a second caller-supplied context lets safe values from two issuances be mixed into an envelope that its own verifier rejects at outer-identity binding.
  The Rust `Commitment` therefore retains its exact issuance context and `disclose` accepts no replacement (`rust/src/commitment.rs:236-288`; `rust/src/envelope.rs:408-423`; specification sections 10 and 11.3).

- **The binding runs BEFORE the minimum-disclosure floor, and the floor is selected from the COMMITTED `roax.recordType` leaf.**
  Derived from section 11.3, not chosen: authority has to be established before an outer field selects anything, and floor-then-bind is trust-then-verify.
  The consequence is load-bearing and is pinned by 16 vectors of the committed corpus - because absence of a reserved leaf now trips the binding, the reserved half of the floor is unreachable and every `floor-<profile>-omits-roax-*` vector asserts `outer-identity-mismatch` rather than `minimum-disclosure-floor`.
  Do not "simplify" by enforcing the floor first; do not trim the reserved paths out of the floor table either, since class 14 defines the floor as the reserved paths plus the profile's.
  Those 16 are four reserved paths across four profiles because those fixtures predate `roax.typeMap.id`, while class 14 defines five reserved paths.
  **That difference is closed ADDITIVELY rather than by a rebuild**: a parallel `typemap-floor-<profile>-*` family carries the outer `typeMap` member and commits the leaf, one accept and one omit per profile, so the fifth path is asserted without touching the roots of the 34 fixtures that were issued without it.
  `profile-unknown` stays ahead of both: it is the verifier's own allow-list, not a policy choice.
  See `corpus/README.md`.

- **Swift's `String` comparison is CANONICAL EQUIVALENCE, so the idiomatic duplicate-key check silently rules an open ambiguity.**
  `"é" == "e\u{0301}"` is `true` in Swift and `Hashable` agrees, so a `Set<String>` implementing specification section 3.2's duplicate-key rejection refuses a record whose two member names are distinct raw keys agreeing only under NFC.
  That is `corpus/README.md` ambiguity 6, which is unruled and which the Rust implementation ACCEPTS, so the language feature decides it in the opposite direction with nothing in the diff to review.
  `swift/Sources/ROAXCanon/JSONValue.swift` therefore keys its duplicate set on `Array(key.utf8)`, and the same feature is deliberately kept for `PathSegment`, where canonical equivalence coincides exactly with encoded-path equality because `encodePath` commits `NFC(key)`.
  Both readings are pinned by tests; an edit that harmonizes them breaks one.
  Swift appears to be the only named target language that sets this trap - Rust and Go compare bytes, JavaScript and Kotlin/JVM UTF-16 code units, Python code points - which is why three libraries preceded it without finding it.
  Full measurement in `swift/FINDINGS.md` finding 7.

- **No Apple API reports the Unicode version behind `precomposedStringWithCanonicalMapping`, so the section 6.1 pin is a declaration there.**
  `dlsym` for `u_getUnicodeVersion_<major>` across ICU 55 to 90 in `libicucore.dylib` finds nothing, and the Swift standard library's own tables answer for characters assigned in Unicode 16.0, so they are demonstrably not the pinned 15.1.
  This is the same position `corpus/README.md` records for reference implementation B under Node's 16.0 tables and the limit class 16 states about itself; it is not a new risk, and the Swift library agrees on all 27 class-4, 20 class-16 and both class-19 vectors anyway.
  Do not add a "check the Unicode version" call on Apple platforms - there is nothing to call.

- **Three Foundation APIs are forbidden inside the Swift library and appear only in tests that assert what they do wrong.**
  `JSONSerialization` mangles `0.010` to `0.01` and `2.0` to `2` while PRESERVING `1234567890123456789.1`, which is the inconsistency specification section 6.4 warns about, and it also cannot raise `duplicate-key` at all.
  `Decimal` carries 38 significant digits, so class 1's 40-digit-by-40-digit vector is unrepresentable and a 50-digit integer is silently corrupted rather than rejected.
  `Data(base64Encoded:)` rejects the unpadded, URL-safe and line-wrapped spellings but ACCEPTS `aGl=`, whose final quantum carries non-zero unused bits, which specification section 6.3 requires rejecting by name and which the corpus carries as one vector.
  Getting three of four right is what makes the fourth easy to miss.

## The conformance corpus

`corpus/` holds it.
`corpus/README.md` is the operative document: coverage per class, the runner, the ambiguities found and what was actually measured.
Read it before touching a vector.

```sh
corpus/tools/run.sh --references /path/to/schemata --modules /path/to/node_modules
```

Both flags are optional and their absence is reported, never hidden: a missing dependency leaves the affected check NOT RUN and exits **2**, which is neither a pass nor a failure, so a bare run does not mean the gate failed.
`corpus/README.md` owns that status table.
Things to know:

- **A vector is never hand-written.**
  `corpus/tools/corpus_plan.py` carries INPUTS only; every expected hash, root, audit path, resolved tag and accept/reject verdict is computed.
  A value typed in by hand would be agreed on by both implementations without either having computed it, which is the whole failure mode the corpus exists to prevent.
- **The two implementations must stay independent.**
  `roax_ref.py` and `roax_ref.mjs` were written from the specification separately, and they use deliberately different mechanisms - stdlib JSON hooks against a hand-written scanner, `bytes` against `Buffer`, Unicode 15.1 tables against 16.0.
  Porting one to the other would make `run.sh` step 3 pass while proving nothing.
- **Python's `$` also matches before a trailing newline; JavaScript's does not.**
  Anchor every grammar in section 6.2 with `\A`/`\Z`.
  The first draft of implementation A accepted `"1.0\n"` and canonicalized it.
  `reject-decimal-trailing-newline` pins it.
- **Four classes are deliberately short, and each is short for a reason recorded in `corpus/README.md`: 10, 11, 13 and 18.**
  Class 10 is 2 of 3 records - PDT stays uncommittable on its 20 endorsed-sample pairs, which need a versioned composition profile nobody has ruled - and class 13 is half.
  Class 11 lacks the two FHIR fail-closed rows its stated minimum names, and they are inexpressible for the same reason section 10 step 1 is undischargeable above: `corpus/type-maps/` carries no `hl7.fhir.bundle` map for such a vector to fail closed against.
  Class 18 carries the four identity rows and the two type-map binding rows, and not the registry rows, which need an anchoring registry that specification section 2.2 leaves undesigned.
  Do not fill any of them in without reading why it is short - building the unbuilt half of 18 decides an open question from inside a data file, which `docs/conformance-corpus.md` section 1.2 forbids, and authoring the class-11 rows would need an invented FHIR map that does the same thing.
  **Class 19 is complete now.**
  It carried the value site alone while D14 was open, and its key site was built under ruled D14a on 2026-07-30; `build_corpus.py` fails if either site is missing.
- **Class 9 is stale against its corrected requirement.**
  The committed `negativeProof` rows use the honest tree size and carry only a supplied leaf hash, so they cannot exercise the forged-size internal-node attack through full disclosed-copy verification as `docs/conformance-corpus.md` class 9 now requires.
  `corpus/README.md` records the exact missing row and carrier gap.
  A library-local regression is useful evidence but does not complete the corpus release gate.
- **`org.roax.corpus.synthetic` is a corpus-only `recordType`.**
  It is not in the `docs/profiles/` registry and must never be issued against.
  It exists so structural vectors do not borrow a real health authority's identifier and so authored type-map bindings never mix into a map that claims schema provenance.

## Documentation conventions in force here

- No em dashes.
  Use a plain hyphen.
- In long Markdown, put each full sentence on its own line.
  It keeps diffs readable when a single sentence changes.
  **Every Markdown file in the tree now holds to this**, measured at zero prose lines carrying more than one sentence, against 934 before the tree was reflowed; code blocks, tables and headings are excluded from that measure because a line of code and a table row are not sentences.
  That count comes from the same sentence splitter that made the split, so it demonstrates internal consistency and idempotence rather than independent correctness.
  The independent evidence is `node tools/reflow-markdown.mjs --verify-render`, which compares the rendered HTML before and after each reflow, so reproducing the measurement means running it over the pre-reflow baseline rather than over the conforming tree, where every file is compared with itself.
  An earlier version of this section described the convention as a target that the repository did not yet meet, and it was true when written.
  `tools/reflow-markdown.mjs` is the executable form of the rule rather than a description of it, so what gets applied is readable rather than reconstructed from a diff.
  Run `node tools/reflow-markdown.mjs` to check and `--write` to apply, `--self-test` for the sentence-splitter cases, and `--verify-render` to additionally compare rendered HTML before and after.
  It is zero-dependency except for `--verify-render`, which takes markdown-it 14 from `ROAX_MARKDOWN_IT` outside the tree exactly as the schema tooling takes Ajv 8 from `ROAX_AJV`, and reports NOT RUN with exit 2 when it is absent.
  A usage error exits 64 rather than 2, so a caller that continues past NOT RUN does not also continue past a mistyped flag.
  The reflow was verified against markdown-it 14.3.0, so name the major version when you re-run it: a later one could move the comparison baseline without saying so.
  It fails closed on any construct it does not model rather than guessing at one, and a second run is a no-op, so it does not churn future diffs.
  **One line is exempt from the join half of the rule: a metadata field, whose content opens with a bold label ending in a colon, as `**Status:**` does.**
  A field carries no sentence punctuation, so sentence splitting alone merges a whole field list into one 300-character line, which defeats the readable-diff purpose the convention exists for; the document headers of `docs/spec/roax-canon-1.md` and the four `docs/profiles/` profiles are the sites this governs.
  The colon has to sit immediately inside the closing delimiter, which is what keeps the `**A bold thesis sentence.** Then the rest` paragraph opening these documents use 257 times out of the exemption.
  The tool's exclusion set is empty and every Markdown file in the tree is checked, including `docs/type-maps.md`, which was excluded only while a parallel change owned that file and has conformed since that change landed.
  Hold new and substantially rewritten prose to the convention, and reach for the tool rather than rewrapping by hand.
  Do not reflow a file wholesale as a side effect of an unrelated change, because the cosmetic diff buries the real one.
  That should not arise now that the tree conforms, since a change that edits one sentence rewrites one line.
- **Every normative claim carries a citation:** specification name, version and section for standards; file and line for code.
  Where something is inferred rather than confirmed, the text says so in the sentence.
  Keep this - the documents are written to be checkable rather than trusted, and a reader who spot-checks one uncited claim loses confidence in all of them.

## Every decision is ruled, and what is left is narrower than a decision

`docs/decisions.md` holds four decisions belonging to the project owner (A, B, C, D), plus the ten engineering ones, plus D14 in part 2a.

**All of them are ruled as of 2026-08-02, and this section heading used to say the opposite.**
Do not restate "one decision is open" from memory, and do not treat "no open decisions" as "nothing left to decide": what remains is the `Poseidon-BN254` parameterization under B, the remap mechanics under C, and the Part 4 gaps, of which the anchoring registry and PDT's 20 endorsed-sample pairs are the ones other documents cite.

**C was ruled on 2026-08-02**: healthcerts already issued under OpenAttestation are **remapped into this protocol** - re-submitted and re-derived under ROAX canonicalization - rather than bridged, mirrored or read natively, and this project builds and maintains NO OpenAttestation verifier.
A translation method is deferred rather than refused.
It is C2 in its stricter form; C1 was rejected on its indefinite two-roots-two-verifiers cost and C3 on the reasoning the document already carried, that a bridge reimplements the exact canonicalization this project exists to escape.
**Three consequences travel with the ruling and a summary that drops them is an overstatement**: a remap produces a NEW root and does not preserve the anchored OpenAttestation one, so a proof against the old root stays a proof of the old bytes; the three unportable states do NOT behave alike, which is the next bullet; and the OpenAttestation redaction bug is only HALF sidestepped, which is where that bullet ends.

**Do not write "ROAX rejects all three unportable states".**
It is the sentence a summary of the C ruling naturally reaches for and it is wrong on the third.
Specification section 3.2 lists duplicate keys, unpaired surrogates, and `undefined` plus sparse-array holes.
The first two are visible in wire text and genuinely fail closed (section 3.2, and section 6.1 for surrogates specifically).
**That two-of-three split holds only if the remap reads the SERIALIZED document**, which is inferred rather than fixed since no remap tool is specified: reading a language-parsed object instead collapses duplicate names to last-wins before the boundary, making it one of three.
Do not reach for section 6.4 here: it is the float-parsing hazard and says nothing about either state, and section 4.2's near-identical sentence governs TYPE-MAP ARTIFACT bytes rather than the record.
The third **cannot fire on a remap's input at all**, for the reason section 3.2 attaches to that very entry - "which have no JSON representation" - so by the time serialized bytes exist the hole is already `null` and the `undefined` member is already absent.
So a remap commits what the predecessor serializer wrote, and under section 3.3 plus settled point S5 a serialized redaction hole becomes a distinct NULL leaf the issuer never intended.
That is the OpenAttestation redaction bug surviving as faithfully committed data rather than as a verification failure - which is better behaviour and is NOT a recovery, so do not describe remapping as sidestepping that bug without the second half.
`docs/decisions.md` Part 4 carries it as a gap.

**A was ruled on 2026-08-02**: no EU credential format is adopted and no export codec is built, material issued under another regime is re-submitted to this standard rather than translated, and a translation method is deferred rather than refused.
That last clause is what costs something, so the ruling carries a **standing design constraint**: a disclosure unit MUST remain a single leaf, independently verifiable against the root from its own audit path alone.
Bundling leaves into an indivisible unit, subtree-only disclosure, or a leaf whose verification needs a sibling beyond its own audit path each break it and each need the ruling revisited rather than settled as a design detail.
Nothing violates it today - specification section 10 already discloses per leaf with a per-leaf salt and a per-leaf proof - which is exactly why it is written down: it is invisible until it is expensive.
Do NOT author a claim-name mapping or an export profile on the strength of it; the constraint is granularity only.
B was ruled earlier - both hash families are first-class and selectable per record - and what stays open under it is the `Poseidon-BN254` parameterization.
D was ruled on 2026-07-29 to five independent, corpus-enforced libraries.
**The ten engineering decisions D3 through D13 were ruled on 2026-07-28** and the specification is written on those rulings rather than on a recommendation; see specification section 15 for the table of where each lands.
Eight confirmed what the specification already said.
Two changed it: D4 to independent per-leaf salts, and D9 gaining the `BLOB_REF` binding.

**D14 asked whether the type-map LOOKUP matches over an NFC-normalized key or over the bytes as received, and it was RULED D14a, NORMALIZE, on 2026-07-30** (`docs/decisions.md` part 2a, specification section 4.2, `docs/type-maps.md` section 3.1).
An earlier version of this file told you not to add an `nfc()` call to a matcher.
**That instruction is superseded and the opposite is now true:** every matcher in this tree normalizes both the pattern token and the segment key, and removing one of those calls unrules a decision.
The sites are `corpus/tools/roax_ref.py`, `corpus/tools/roax_ref.mjs`, `src/typemap.ts`, `python/src/roax_canon/typemap.py`, `rust/src/type_map.rs`, `swift/Sources/ROAXCanon/TypeMap.swift`, both resolvers in `kotlin/roax-canon/src/main/kotlin/io/roax/canon/TypeMap.kt` and the legacy adapter in `rust/tests/conformance_corpus.rs`.
The Kelvin workaround in the synthetic map is gone, and two committed vectors now fail closed under raw matching, so the corpus catches a regression rather than tolerating it.
Rust's `LookupKeyMode`, `TypeResolver::ensure_lookup_decision_independent` and `Error::LookupNormalizationUndecided` were deleted with the ruling; do not reintroduce a mode enum.

**A ruling updates `docs/decisions.md` in the same change rather than only the specification**, and if a decision is ever reopened or a new one raised, the same rule binds.
A decision that looks settled in the spec but is still marked OPEN in the decisions document is worse than either.
**A and C are the worked examples**: each moved `docs/decisions.md`, `README.md`, `docs/spec/roax-canon-1.md` section 15, `docs/conformance-corpus.md` and this file in one change, because those documents each stated the open count and any one left behind would have contradicted the rest.
C moved `docs/profiles/vaccination-healthcert.md` as well, since that profile had folded a question into C and had to be told the answer - which is that the ruling settles the DIRECTION and does not choose between preserving and normalizing the flattened `fhirBundle.entry[]` layout.
**A and C were ruled on the same date and neither decided the other**, and that distinction is now easier to lose rather than harder.
A's re-submission answer covers material issued under another regime and was explicitly not extended by inference to the already-issued Singapore healthcerts; C reaches a compatible answer from the OpenAttestation audit evidence instead.
They share a principle - conform to this standard now, keep translation possible later - and collapsing them into one ruling discards why each was made.
Part 1's owner sections are the owner's and are not edited by ruling work elsewhere in the document; the C ruling corrected exactly one sentence inside A's section, the one saying C stays open, and left the rest of that section alone.

## Validating the schemas

There is no CI, and the `package.json` at the root is the TypeScript library's rather than a place to add schema tooling: Ajv stays outside the tree.
The JSON Schemas were checked with Ajv 8 in **strict mode** plus `ajv-formats`, and all seven compile clean.
Re-check after any edit: install `ajv` and `ajv-formats` outside the tree, then `new Ajv2020({strict: true}).compile()` each of the seven files, using the `ajv/dist/2020.js` entry point because they are draft 2020-12.
Compiling is not enough on its own for a conditional - validate instances both ways, since an `if`/`then` that never fires compiles perfectly and asserts nothing.

**The envelope and the corpus vector file each have two live schema versions, and the pair is not a leftover.**
`schemas/envelope-2.0.json` and `schemas/conformance-corpus-2.0.json` carry the type-map binding and the six-leaf floor, and are what the specification and `docs/type-maps.md` describe.
`schemas/envelope-1.0.json` and `schemas/conformance-corpus-1.0.json` govern the corpus artifact and the 69 envelope fixtures as committed, which `corpus/tools/validate_schemas.mjs` measures.
That file also validates the two envelopes each class-20 vector names, which no envelope vector points at: leaving them out would make the one class whose fixtures an implementation must REPRODUCE the only class whose fixtures nothing schema-checked.

**The two files differ in what stayed behind, and the difference is deliberate.**
`schemas/envelope-1.0.json` is unchanged in meaning BY THE RULING: D4b altered no envelope bytes, so what it took from D4b was description changes alone, and its floor stays at five reserved leaves where the successor's is six.
It did gain one structural conditional separately, so read that sentence as scoped to the ruling rather than as "nothing structural changed": an `issuer.keyId` now raises `leafCount` and `salts.minItems` from 5 to 6 together, since that case emits the fifth reserved leaf, and every committed fixture already satisfies it.
That rule was structural in the corpus schema and prose-only here until it was noticed.
`schemas/conformance-corpus-1.0.json` was **migrated in place** instead, because the D4b ruling did change the vector shapes: `saltVector`, `unlinkabilitySide` and `recordVector.masterSaltHex` are deleted, `saltsFile` and `normalizationVector` are added, and the committed corpus was rebuilt in the same change.
The same-change rule in specification section 1.1 and `docs/conformance-corpus.md` section 1.1 is why: a canonicalization change lands with the vectors that assert it, and leaving the deleted derivation expressible in the file that governs the artifact would have left the corpus implementing a construction the specification no longer has.
So what still makes the corpus successor a MAJOR bump is the type-map binding alone: it requires the exact artifact identity on the type-map and record vectors, which the committed corpus does not carry.
Do not tighten the 1.0 files any further without rebuilding what they govern in the same change.
Both corpus schemas gained `rejectVector.recordType` on 2026-07-30, and that is a WIDENING rather than a tightening: a reject vector carrying it is a whole-record rejection flattened through that profile's committed map, which is the only shape that can reach the rulings stated as rejections rather than as tags.
The input-shape constraint is stated structurally, and `corpus/README.md` says why a permissive stand-in map would make those vectors unfalsifiable.
The schema version is not the canonicalization version - both envelope schemas pin `canon` to `ROAX-CANON/1`.

Five things to know if you touch them:

- Ajv's `strictRequired` rejects `required` inside a `not`/`anyOf` subschema unless the same subschema also lists those properties.
  The schemas carry no-op `"properties": {"x": true}` annotations for exactly this reason.
  They are not redundant - removing them breaks strict compilation.
- Union types (`"type": ["string","boolean"]`) trip `strictTypes`.
  The envelope pins each value type per tag in its `allOf` conditionals instead, which is more precise anyway.
- **`strictTypes` rejects any type-specific keyword inside an `if`, `then` or `else` branch unless that branch declares the `type` itself**, because a branch cannot see the `type` on the same property in `properties`.
  It applies to `minimum`, to `minItems` and to `required` alike, and at every nesting depth: `recordVector`'s `then` writes `{"type": "integer", "minimum": 6}`, and the envelope's `issuer.keyId` conditional writes `{"type": "object", "required": ["keyId"], ...}` on a property one level down.
  Every one of those repetitions is required, not redundant.
- **A property is FORBIDDEN inside a branch with the false schema, `"properties": {"x": false}`.**
  That idiom is used in `recordVector`'s two-branch `oneOf` and in `envelopeVector`'s `else`, and it compiles clean under strict mode.
  It is shorter than `"not": {"required": ["x"], "properties": {"x": true}}` and needs no `strictRequired` annotation, because it carries no `required`.
- **A conditional keyed on a vector's `class` needs an instance test on BOTH sides.**
  `envelopeVector` PERMITS `verifierConfig` at class 18 and forbids it everywhere else.
  It is not required there, and a revision that required it was reverted for rejecting the committed corpus: the six class-18 vectors are the identity and type-map binding rows, which the envelope alone determines, so a config on them would be inert.
  The else-branch is the half a compile check cannot see.
  `corpus/tools/validate_schemas.mjs` carries those probes rather than leaving them to a reader: a class-18 instance without the block (MUST pass), one carrying a complete block (MUST pass), one carrying an empty or a partial block (MUST fail, since the block's own `required` names four members), and a class-14 instance carrying one (MUST fail).
  It probes `recordVector`'s two-branch `oneOf` and the deleted D4a carriers the same way, and every probe mutates a clone of the whole committed corpus rather than a `$defs` subschema: compiling proves the `$ref` resolves, and only a root-level instance proves the branch is reached by the path a runner takes.
  It also probes `rejectVector`'s `recordType` conditional in both directions: the committed record-shaped vector (MUST pass), one whose `input` is not `$jsonText` and ones carrying `tag` or `segments` (MUST fail), and vectors with NO `recordType` keeping their `tag` or their `segments` (MUST pass), which is the half that separates this conditional from one forbidding `tag` on every reject vector.
  Add a probe there when you add a conditional, because `run.sh` step 4 is the only thing that runs them.
  The completeness rule that block exists for - a vector whose outcome turns on the verifier's configuration must carry one - is still not mechanically enforced by any of this, and the schema says so rather than naming an enforcer.
