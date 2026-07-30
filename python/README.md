# roax-canon for Python

A Python implementation of `ROAX-CANON/1`: canonicalization, leaf and tree construction, verification and selective disclosure.
Nothing beyond that surface.
No network, no chain reads, no key management.

**Standard library only.**
`hashlib`, `unicodedata`, `secrets`, `json` and `re`.
Nothing here needs installing to run.
`pyproject.toml` declares no runtime dependencies and the tests add none, so a bare CPython checkout runs both the unit suite and the corpus runner.

Requires CPython 3.10 or later for the `X | Y` type syntax; developed and measured on 3.13.5.

## Read this first

[`FINDINGS.md`](FINDINGS.md) is the more valuable half of this deliverable.
It records the divergences, ambiguities, confirmations and Python-specific hazards documented
during this build, with the measurement behind each.

## Why it is written from the specification

The project owner ruled five independent builds rather than a shared core.
This was written from [`docs/spec/roax-canon-1.md`](../docs/spec/roax-canon-1.md) alone; `corpus/tools/roax_ref.py` and `corpus/tools/roax_ref.mjs` were not read while it was built.

That is the whole method.
Those two exist because they were written independently of each other, and their agreement is the only evidence the specification says one thing.
An implementation produced by reading one of them is a port wearing the costume of a third opinion, and the cross-check silently becomes worthless.
The corpus was run only after each piece was written.

## Running the conformance corpus

```sh
python3 python/tools/run_corpus.py
python3 python/tools/run_corpus.py --references /path/to/schemata   # class 10 needs it
ROAX_REFERENCES=/path/to/schemata python3 python/tools/run_corpus.py
python3 python/tools/run_corpus.py --references /path/to/schemata \
    --empty-containers=authorized                                  # see FINDINGS item 1
```

This is a third runner and it is standalone.
It does not extend `corpus/tools/run.sh`, which is the existing two-implementation gate; it consumes the vector file, the fixtures and the corpus-side type maps, which is the interface `corpus/README.md` documents for an implementation that is not one of those two.
The runner does not deliberately write files or modify `corpus/`; the interpreter's normal
`__pycache__` writes may still occur.

Measured on CPython 3.13.5:
Pass and fail are assertion counts; not-run entries are vectors or required classes.

| Mode | Pass | Fail | Not run | Classes passed | Result | Exit |
|---|---:|---:|---:|---:|---|---:|
| structural, references available | 738 | 0 | 0 | 19/19 | `PASS` | 0 |
| structural, references unavailable | 734 | 0 | 2 | 18/19 | `INCOMPLETE / NOT RUN` | 2 |
| authorized, references available | 734 | 2 | 0 | 18/19 | `FAIL` | 1 |

The first row is the only conforming PASS.
Class 10 reproduces both roots of the MOH recovery sample at
`references/schemata/src/sg/gov/moh/recovery-healthcert/2.0/sample-data.ts`, upstream commit
`09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`, at 69 and 70 leaves.

`--references` defaults first to `ROAX_REFERENCES`, then to `references/` at the repository root.
The checkout is third-party, `.gitignore` excludes it, and it is never committed.
Without it, class 10 reports its two vectors as NOT RUN with the attempted path and
`--references /path/to/schemata` remedy, the terminal result is `INCOMPLETE / NOT RUN`, and
the process exits 2.
It never reports PASS for those 734 assertions.
The whole difference is class 10's two vectors and the 4 assertions they carry, whose records resolve out of that checkout through the `recordFile` strings committed at `corpus/conformance-corpus-1.0.json:5900` and `:5914`.
The authorized-mode 734 is a different measurement: the checkout is present, the two
class-5 empty-container records fail closed, and the process exits 1
([`FINDINGS.md`](FINDINGS.md), item 1).
An unsupported reject-vector shape, an unsupported record-vector envelope carrier, a missing
committed type map, or a present reference module that cannot be extracted is a failure and
also exits 1.

## Running the unit tests

```sh
PYTHONPATH=python/src python3 -m unittest discover -s python/tests -t python
```

144 tests, standard library `unittest`.
They cover what the corpus reaches plus the Python-specific traps it cannot see, because a trap closed by accident reopens on the next edit.
`tests/test_ts_sample.py` covers `tools/ts_sample.py` for the same reason: its only consumer is the class-10 record path, so a run without the reference checkout exercises none of it.

## Unicode

`ROAX-CANON/1` pins Unicode 15.1 (specification section 6.1, ruled decision D12a).

CPython 3.13.5 ships `unicodedata.unidata_version == "15.1.0"`, which is exactly that pin.
CPython ships one table version per build and offers no way to select another, so this is a property of the interpreter you deploy on rather than a setting.

```python
import roax_canon
roax_canon.runtime_unicode_version()   # '15.1.0'
roax_canon.unicode_tables_match_pin()  # True
```

An implementation whose tables come from a different Unicode version MAY produce a different root and MUST NOT claim conformance.
`unicode_tables_match_pin()` is what a conformance report should read.
Note also what a passing run does and does not show: this build is not running across the 15.1-to-16.0 boundary at all, so its agreement with the corpus on classes 4 and 16 says nothing about version sensitivity in either direction.

## Using it

Runnable as written, from the repository root, with `PYTHONPATH=python/src`.

### Full-copy serialization warning

Plain `json.dumps(full_copy(...))` is not a supported wire serializer.
`JsonNumber` subclasses `str`, so `json.dumps` quotes record numbers and changes their observed
JSON kind from `number` to `string` when the envelope is read again.
Specification section 7.3 requires a full copy's record body to preserve the original JSON
number form.
This package ships no serializer, so callers writing a full copy to the wire must emit those
original numeric tokens unquoted ([`FINDINGS.md`](FINDINGS.md), item 12).

The example below uses `org.roax.corpus.synthetic` only because its authored type map covers
the example record.
That profile is corpus-only and must never be issued against
([`corpus/README.md`](../corpus/README.md), "The synthetic profile").

```python
import roax_canon as roax

# 1. Read the record. NEVER with the stdlib json module directly: its defaults turn
#    0.010 into 0.01, 1e999 into inf, and {"a":1,"a":2} into {"a":2}.
record = roax.loads('{"marker": "x", "counts": {"decimal": 0.010}}')

# 2. Bind types from the schema, never from the literal's syntax. An unknown path fails
#    closed; it is never defaulted. (This map is corpus tooling and its profile must never
#    be issued against; it is used here because it is the one map in the tree that covers
#    an authored record.)
type_map = roax.DisplayPatternTypeMap.from_file(
    "corpus/type-maps/org.roax.corpus.synthetic.json"
)

# 3. Commit. One independent CSPRNG salt per leaf; there is no derivation and no master
#    secret (ruled decision D4b).
identity = roax.RecordIdentity(
    record_type="org.roax.corpus.synthetic",
    schema_version="1.0",
    record_id="urn:uuid:11111111-1111-4111-8111-111111111111",
    issuer_id="did:web:example.gov",
)
built = roax.issue(record, identity, type_map)
built.root.hex()          # 2 record leaves + 4 reserved leaves
built.leaf_count          # 6

# 4. Carry it. The commitment retains the exact identity, algorithm, reserved set and an
#    isolated snapshot of the original record, so neither emitter accepts replacement
#    issuance context. A full copy carries every salt; a disclosed copy carries only the
#    salts of the leaves it reveals and never a `salts` array.
profile = roax.Profile("org.roax.corpus.synthetic", ((roax.Key("marker"),),))
full = roax.full_copy(built)
partial = roax.disclosed_copy(list(profile.floor()), built, profile=profile)
"salts" in partial        # False, and unrepresentable rather than merely absent

# 5. Verify. Authority comes from the verifier's configuration, never from the document.
config = roax.VerifierConfig(
    profiles=roax.DEFAULT_PROFILES.with_profile(profile),
    resolvers={"org.roax.corpus.synthetic": type_map},
    hash_alg_allow_list=("SHA-256",),
    anchored_root=built.root,
    anchored_hash_alg="SHA-256",
)
roax.verify_envelope(full, config).reason        # 'ok'
roax.verify_envelope(partial, config).reason     # 'ok'
```

## What the modules are

| Module | What it owns |
|---|---|
| `errors` | The rejection codes, which are the corpus's `reason` strings |
| `text` | The Unicode pin, NFC, and the surrogate rejection that precedes it |
| `numbers` | Canonical INTEGER and DECIMAL, over strings, never through a float |
| `path` | Segments, `encodePath`, and a display rendering not accepted as structured input |
| `value` | Type tags, value encoding, and the pinned RFC 4648 base64 form |
| `leaf` | The algorithm-qualified leaf preimage and leaf hash |
| `jsonio` | The literal-preserving JSON reader and the section 3.2 rejections |
| `typemap` | The display-pattern resolver; fails closed, never defaults |
| `flatten` | Flattening and the reserved-namespace guard |
| `record` | Reserved leaves, the union, the ordering, salts and the root |
| `tree` | RFC 9162 `MTH`, audit paths and inclusion verification |
| `hashes` | The algorithm registry; SHA-256 defined, Poseidon-BN254 registered and unusable |
| `profiles` | The profile allow-list and the minimum-disclosure floor, as segments |
| `disclose` | Building the two envelope shapes |
| `verify` | Envelope verification, in the order specification section 11.3 requires |

## Five things this package will not let you do

1. **Parse a record number through a float.**
   `roax.loads` carries every numeric literal verbatim as `JsonNumber`, a distinct `str` subclass so that a JSON number is never confused with a JSON string.
   The type map is keyed on observed kind, so that second distinction is load-bearing too.
2. **Hash a display path.**
   `encode_path` accepts segments only, and the package exposes no parser that reconstructs segments from `display_path` output.
   A unit test asserts that no function with `parse` in its name exists in `roax_canon.path`, holding that API boundary against the specification section 5.2 trap.
3. **Default an unknown path.**
   The built-in `DisplayPatternTypeMap` raises.
   Build APIs bind that built-in map's declared `recordType` and `schemaVersion` to the issuance identity.
   They also accept custom `TypeResolver` implementations, which must preserve the fail-closed contract and whose trusted caller must bind resolver provenance and scope because the protocol itself carries no metadata.
4. **Emit a withheld leaf's salt.**
   `disclosed_copy` builds its `leaves` array from the revealed set and never emits a `salts` member, so a withheld salt is unrepresentable rather than merely prohibited.
5. **Accept a caller-supplied leaf hash.**
   `verify_envelope` has no parameter that takes one, which makes the defence of specification section 10 step 2 structural.
   Specification section 11.1's forged-tree-size measurement is reproduced in the test suite to show why that matters.

## What is deliberately not built

The structured-path DFA artifacts in `type-maps/`, content-ID reproduction, issuer extensions and any anchoring registry read.
[`FINDINGS.md`](FINDINGS.md) item 13 states each with its reason.
The short version: no committed corpus vector exercises them, and adding a large unexercised surface to a library whose acceptance criterion is byte-identical agreement on the corpus would be adding untested code, not coverage.
Consequently `RESERVED_V2` is structural only: `reserved_leaves` can model the extra committed selector leaf, while issuance, envelope emission and verification reject with `type-map-rejected` until an artifact-aware resolver can reproduce and select the exact content ID (`src/roax_canon/record.py:53-63` and `:242-252`; `src/roax_canon/disclose.py:47-56`; `src/roax_canon/verify.py:404-410`; specification section 4.2).
