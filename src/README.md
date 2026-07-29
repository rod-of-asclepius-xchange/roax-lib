# `@roax/canon` - the TypeScript implementation of `ROAX-CANON/1`

Canonical serialization, commitment and selective disclosure for health records.
Written from [`docs/spec/roax-canon-1.md`](../docs/spec/roax-canon-1.md).

**Findings from building it are in
[`docs/typescript-implementation-findings.md`](../docs/typescript-implementation-findings.md), and
that document is worth more than this one.**
It records every place this implementation disagreed with the conformance corpus and every place
the specification admitted two honest readings.

## Why this exists and what it is not

This is the first of the five independent libraries.
It was written from the specification text, and `corpus/tools/roax_ref.py`,
`corpus/tools/roax_ref.mjs` and `corpus/tools/check_corpus.mjs` were deliberately not read while
writing it.
Those two reference implementations exist precisely because they were written independently of each
other, and their agreement is the only evidence the specification says one thing.
An implementation produced by reading one of them is a port wearing the costume of a third opinion,
and the cross-check silently becomes worthless.

The corpus was run only after each module was written.

## The one rule that governs everything here

**A number is never parsed through a float.**

`JSON.parse` destroys `0.010` into `0.01` and `9223372036854775807` into `9223372036854776000`
before any of this code would see the value.
FHIR R4 says of `decimal` that "0.010 is regarded as different to 0.01, and the original precision
should be preserved", and states that implementations **SHALL** preserve it.
In a medical dosage those are different statements about a drug.

So `src/json.ts` is a hand-written scanner.
ES2025's source-text access - the `JSON.parse` reviver's third `context` argument, which
specification section 6.4 records as this language's confirmed mechanism - solves the literal
problem and NOT the duplicate-key problem: by the time a reviver sees an object, duplicate members
are already gone, and specification section 3.2 requires them rejected.
Solving both at once is what forces a scanner.

**Nothing in `src/` calls `JSON.parse`, `parseInt` or `parseFloat`, and no numeric literal OF A
RECORD is ever converted to a machine number.**
A record's numeric literal reaches `encodeValue` as the verbatim source text and is canonicalized
by string and `BigInt` operations over digit sequences, so no float exists anywhere on the path
from input text to hash preimage.

That statement is deliberately narrower than "nothing calls `Number()`", because three calls remain
and a claim that a reader can falsify by grepping for one is worth less than a claim that survives
the grep.
All three are listed here, and each is exact rather than approximate.

| Site | What it converts | Why it is exact |
|---|---|---|
| `numbers.ts`, the decimal exponent | a `BigInt` | Reached only after the digit bound has proved `\|e\| <= 1024`. The exponent LITERAL is read with `BigInt` for the opposite reason: a large one would saturate to `Infinity` and turn a rejection into an unbounded allocation. |
| `bytes.ts`, `u64be` | a `BigInt` masked to one byte | A value in `0..255` is exactly representable. The value arrived as a `bigint` and never stopped being one. |
| `envelope.ts`, `structuralInteger` | a validated integer literal, through `BigInt` | A count, an index, a chain identifier or a type tag - structural rather than a record value. The literal is checked against `^(0\|[1-9][0-9]*)$`, converted with `BigInt`, and range-checked BEFORE it is narrowed, so no rounding can precede the check. **Two of the four are themselves committed** - the tag byte enters the leaf preimage and an INDEX segment enters `encodePath` - so this is not "uncommitted, therefore harmless": the guarantee is that the byte written is the one the literal named. |

`BigInt` appears only where it is exact, and hexadecimal is decoded by table lookup rather than by
`parseInt`, so no text in this package reaches a machine number through a general-purpose numeric
parser.

## Running it

```sh
npm install
npm run build
npm test              # unit tests for rules no corpus vector reaches
npm run conformance   # the corpus
```

Two environment variables change what the conformance run covers, and both default to reporting
rather than hiding:

| Variable | Effect |
|---|---|
| `ROAX_REFERENCE_RECORDS=<dir>` | Runs class 10 against records extracted from a reference checkout outside this repository. Without it the class reports 2 SKIPPED and is never reported green unrun. |
| `ROAX_EMPTY_CONTAINERS=map-authorized` | Applies specification section 3.3's rule that an empty container's tag must be authorized by the map. The committed corpus cannot be passed under it; see finding 2. |

## Layout

| Module | What it owns |
|---|---|
| `errors.ts` | The error taxonomy. Codes are the corpus's own reason strings, emitted verbatim. Every rejection of input is a `RoaxError`; the one caller-precondition violation, an out-of-range leaf index in `tree.ts`, is a `RangeError` and is deliberately outside the taxonomy. |
| `json.ts` | The literal-preserving reader and writer, and the unpaired-surrogate rejection. |
| `numbers.ts` | Canonical integer and decimal (section 6.2), including the 1024-digit bound. |
| `bytes.ts` | `u32be`, `u64be`, UTF-8, NFC, hex, and RFC 4648 section 4 base64. |
| `path.ts` | `encodePath` (section 5) and the display path, which is never hashed. |
| `value.ts` | Type tags and `encodeValue` (section 6.1). |
| `hash.ts` | The algorithm registry and `DOMAIN`. |
| `leaf.ts` | The ONE leaf-preimage builder (section 8). |
| `tree.ts` | RFC 9162 `MTH`, audit paths and the inclusion fold (section 9). |
| `typemap.ts` | The `TypeTagResolver` interface and the corpus's display-pattern map. See finding 1. |
| `flatten.ts` | Flattening and the leaf-set union (section 3.3), ordered by encoded path. |
| `reserved.ts` | The reserved leaves and the reserved-namespace guard (section 11.2). |
| `profiles.ts` | The profile registry and the minimum-disclosure floors, carried as SEGMENTS. |
| `commit.ts` | Salts and root computation (sections 7, 8, 9). |
| `envelope.ts` | Parsing and verification, in the order section 11.3 derives. |
| `issue.ts` | Issuance and selective disclosure. |

## Four traps this language sets, and where each is handled

- **`Buffer.from(s, 'utf8')` and `TextEncoder` substitute U+FFFD for a lone surrogate**, silently.
  A surrogate check placed after encoding is therefore unobservable. `assertNoUnpairedSurrogate`
  runs on the decoded string, before anything encodes it.
- **`String.prototype.normalize` uses the runtime's bundled ICU and exposes no version selector.**
  `ROAX-CANON/1` pins Unicode 15.1; Node v22.21.0 provides 16.0. This implementation DECLARES the
  mismatch on every conformance run rather than claiming the pin. See finding 5.
- **JavaScript's `$` matches only at end of input**, so the trailing-newline bug that Python's `$`
  produces is absent here for free. The number grammars are still anchored explicitly, so the
  property is visible rather than inherited from the dialect.
- **`JSON.parse` keeps the LAST of two duplicate members**, silently. Rejecting duplicates is a
  reason the reader is hand-written.
