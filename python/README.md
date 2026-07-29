# roax-canon for Python

A Python implementation of `ROAX-CANON/1`: canonicalization, leaf and tree construction, verification and selective disclosure.
Nothing beyond that surface.
No network, no chain reads, no key management.

**Standard library only.**
`hashlib`, `unicodedata`, `secrets`, `json` and `re`.
Nothing here needs installing to run, which matters in a repository that deliberately has no package manifest for its corpus tooling.

Requires CPython 3.10 or later for the `X | Y` type syntax; developed and measured on 3.13.5.

## Read this first

[`FINDINGS.md`](FINDINGS.md) is the more valuable half of this deliverable.
It records every place this build disagreed with the conformance corpus or found the specification ambiguous, marked as a divergence, an ambiguity or a confirmation, with the measurement behind each.

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
python3 python/tools/run_corpus.py --empty-containers=authorized    # see FINDINGS item 1
```

This is a third runner and it is standalone.
It does not extend `corpus/tools/run.sh`, which is the existing two-implementation gate; it consumes the vector file, the fixtures and the corpus-side type maps, which is the interface `corpus/README.md` documents for an implementation that is not one of those two.
Nothing under `corpus/` is modified, and the runner writes no files.

Current result, on CPython 3.13.5 with the reference checkout available:

```
class    pass    fail    skip  status
    1      44       0       0  PASS      11      26       0       0  PASS
    2      12       0       0  PASS      12       9       0       0  PASS
    3      24       0       0  PASS      13       4       0       0  PASS
    4      32       0       0  PASS      14      68       0       0  PASS
    5      12       0       0  PASS      15      33       0       0  PASS
    6      59       0       0  PASS      16      20       0       0  PASS
    7      16       0       0  PASS      17      16       0       0  PASS
    8     338       0       0  PASS      18       8       0       0  PASS
    9      11       0       0  PASS      19       2       0       0  PASS
   10       4       0       0  PASS

RESULT: PASS (738 assertions)
```

All 19 classes, no skips.
Class 10 reproduces both roots of the genuine MOH recovery sample, at 69 and 70 leaves.

Without `--references` class 10 reports SKIPPED and contributes no assertions; it never reports green unrun.

## Running the unit tests

```sh
PYTHONPATH=python/src python3 -m unittest discover -s python/tests -t python
```

87 tests, standard library `unittest`.
They cover what the corpus reaches plus the Python-specific traps it cannot see, because a trap closed by accident reopens on the next edit.

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

# 4. Carry it. A full copy carries every salt; a disclosed copy carries only the salts of
#    the leaves it reveals and never a `salts` array.
profile = roax.Profile("org.roax.corpus.synthetic", ((roax.Key("marker"),),))
full = roax.full_copy(record, identity, built)
partial = roax.disclosed_copy(list(profile.floor()), identity, built, profile=profile)
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
| `path` | Segments, `encodePath`, and a display path nothing parses back |
| `value` | Type tags, value encoding, and the pinned RFC 4648 base64 form |
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
   `encode_path` accepts segments only, and there is no display-path parser anywhere in the package.
   A unit test asserts that no function with `parse` in its name exists in `roax_canon.path`, so the specification section 5.2 trap cannot be reintroduced quietly.
3. **Default an unknown path.**
   `TypeResolver` raises; every caller propagates.
4. **Emit a withheld leaf's salt.**
   `disclosed_copy` builds its `leaves` array from the revealed set and never emits a `salts` member, so a withheld salt is unrepresentable rather than merely prohibited.
5. **Accept a caller-supplied leaf hash.**
   `verify_envelope` has no parameter that takes one, which makes the defence of specification section 10 step 2 structural.
   Specification section 11.1's forged-tree-size measurement is reproduced in the test suite to show why that matters.

## What is deliberately not built

The structured-path DFA artifacts in `type-maps/`, content-ID reproduction, issuer extensions and any anchoring registry read.
[`FINDINGS.md`](FINDINGS.md) item 13 states each with its reason.
The short version: no committed corpus vector exercises them, and adding a large unexercised surface to a library whose acceptance criterion is byte-identical agreement on the corpus would be adding untested code, not coverage.
