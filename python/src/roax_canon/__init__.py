"""`roax-canon`: a Python implementation of ROAX-CANON/1.

Canonicalization, leaf and tree construction, verification and selective disclosure, as
specified by `docs/spec/roax-canon-1.md`.
Nothing else: no network, no chain reads, no key management.

Written from the specification text.
The two implementations under `corpus/tools/` were deliberately not read while this was
built, because their agreement is the only evidence the specification says one thing, and
a third opinion produced by reading one of them would be a port wearing a costume.

High-level API safeguards:

* **A record read through this package never parses a number through a float.**
  :func:`roax_canon.jsonio.loads` carries every numeric literal verbatim as
  :class:`~roax_canon.jsonio.JsonNumber`, and :mod:`roax_canon.numbers` moves the decimal
  point by slicing text.
* **The display path is not a structured-path input.**
  :func:`~roax_canon.path.encode_path` accepts segments, and the package provides no
  parser that reconstructs segments from :func:`~roax_canon.path.display_path` output.
* **The built-in display-pattern matcher fails closed.**
  :class:`~roax_canon.typemap.DisplayPatternTypeMap` raises rather than defaulting.
  Custom :class:`~roax_canon.typemap.TypeResolver` implementations must uphold the same
  contract.
* **Envelope verification recomputes disclosed leaf hashes.**
  :func:`~roax_canon.verify.verify_envelope` accepts leaf fields rather than a
  caller-supplied leaf hash.
  :func:`~roax_canon.tree.verify_inclusion` is a lower-level fold primitive and provides
  no disclosure defence on its own.

Unicode: `ROAX-CANON/1` pins Unicode 15.1.
Check :func:`roax_canon.text.unicode_tables_match_pin` on the interpreter you deploy on;
CPython ships one table version per build and offers no way to select another.
"""

from __future__ import annotations

import sys as _sys

if _sys.version_info < (3, 10):
    raise RuntimeError(
        "roax-canon requires CPython 3.10 or later; this interpreter is "
        f"{_sys.version_info.major}.{_sys.version_info.minor}."
        " The package uses `dataclass(slots=True)` and the runtime `X | Y` union, both of"
        " which are 3.10 features, so the submodule imports below would otherwise fail"
        " with an unrelated TypeError. Rerun the documented commands naming a 3.10+"
        " interpreter, for example `PYTHONPATH=python/src python3.13 -m unittest discover"
        " -s python/tests -t python`. `python/pyproject.toml` declares the same floor as"
        ' `requires-python = ">=3.10"`.'
    )

from .disclose import disclosed_copy, full_copy
from .errors import (
    EnvelopeError,
    ErrorCode,
    GrammarError,
    InputError,
    PathError,
    RoaxError,
    TreeError,
    TypeResolutionError,
)
from .flatten import RESERVED_KEY_PREFIX, check_reserved_namespace, flatten
from .hashes import DEFAULT_HASH_ALG, DEFINED_ALGORITHMS, REGISTERED_ALGORITHMS, get_hash
from .jsonio import JsonNumber, json_kind, load_file, loads
from .leaf import (
    CANON,
    DEFAULT_ORDERING,
    ORDERING_DOMAIN_SUFFIX,
    ORDERING_HASH,
    ORDERING_PATH,
    SALT_BYTES,
    Leaf,
    check_ordering,
    domain_string,
    leaf_hash,
)
from .numbers import DIGIT_BOUND, canonical_decimal, canonical_integer
from .path import Index, Key, MAX_INDEX_EXCLUSIVE, display_path, encode_path
from .profiles import DEFAULT_PROFILES, Profile, ProfileRegistry
from .record import (
    RESERVED_V1,
    RESERVED_V2,
    BuiltRecord,
    MappingSalts,
    PositionalSalts,
    RecordIdentity,
    build_tree,
    draw_salt,
    issue,
    order_leaves,
    reserved_leaves,
)
from .text import PINNED_UNICODE_VERSION, nfc, runtime_unicode_version, unicode_tables_match_pin
from .tree import audit_path, merkle_tree_head, verify_inclusion
from .typemap import DisplayPatternTypeMap, TypeResolver
from .value import (
    BLOB_REF,
    BOOL,
    BYTES,
    DECIMAL,
    EMPTY_ARRAY,
    EMPTY_OBJECT,
    INTEGER,
    NULL,
    STRING,
    BlobRef,
    encode_value,
)
from .verify import VerificationResult, VerifierConfig, verify_envelope

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # Canonicalization
    "CANON",
    "DIGIT_BOUND",
    "canonical_decimal",
    "canonical_integer",
    "encode_value",
    "encode_path",
    "display_path",
    "Key",
    "Index",
    "MAX_INDEX_EXCLUSIVE",
    # Types
    "NULL",
    "BOOL",
    "STRING",
    "INTEGER",
    "DECIMAL",
    "BYTES",
    "EMPTY_ARRAY",
    "EMPTY_OBJECT",
    "BLOB_REF",
    "BlobRef",
    "TypeResolver",
    "DisplayPatternTypeMap",
    # Reading a record
    "JsonNumber",
    "loads",
    "load_file",
    "json_kind",
    "flatten",
    "check_reserved_namespace",
    "RESERVED_KEY_PREFIX",
    # Leaves and trees
    "Leaf",
    "SALT_BYTES",
    "domain_string",
    "leaf_hash",
    "check_ordering",
    "DEFAULT_ORDERING",
    "ORDERING_PATH",
    "ORDERING_HASH",
    "ORDERING_DOMAIN_SUFFIX",
    "merkle_tree_head",
    "audit_path",
    "verify_inclusion",
    # Records
    "RecordIdentity",
    "RESERVED_V1",
    "RESERVED_V2",
    "reserved_leaves",
    "order_leaves",
    "BuiltRecord",
    "build_tree",
    "issue",
    "draw_salt",
    "MappingSalts",
    "PositionalSalts",
    # Envelopes
    "full_copy",
    "disclosed_copy",
    "verify_envelope",
    "VerifierConfig",
    "VerificationResult",
    "Profile",
    "ProfileRegistry",
    "DEFAULT_PROFILES",
    # Algorithms
    "DEFAULT_HASH_ALG",
    "DEFINED_ALGORITHMS",
    "REGISTERED_ALGORITHMS",
    "get_hash",
    # Unicode
    "PINNED_UNICODE_VERSION",
    "runtime_unicode_version",
    "unicode_tables_match_pin",
    "nfc",
    # Errors
    "RoaxError",
    "ErrorCode",
    "InputError",
    "GrammarError",
    "PathError",
    "TypeResolutionError",
    "TreeError",
    "EnvelopeError",
]
