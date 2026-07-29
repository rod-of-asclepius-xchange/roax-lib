"""The hash-algorithm axis (specification sections 7.4 and 12).

`ROAX-CANON/1` **defines** the construction for `SHA-256` only.
`Poseidon-BN254` is **registered** because both hash families are first-class and
selectable per record (ruled decision B), and its parameterization is not pinned by the
specification: the field, the rate and capacity, the round constants, and the encoding
from a length-prefixed byte string to field elements are all open.

> **Normative:** a record MUST NOT be issued with ``hashAlg: "Poseidon-BN254"`` until a
> revision pins that parameterization (specification section 7.4).

So it appears in :data:`REGISTERED_ALGORITHMS` and raises if selected.
That is deliberately the same treatment tag 8 `BLOB_REF` gets in :mod:`roax_canon.value`.

**Authority for which algorithm to run does not come from this module and does not come
from the envelope.**
Specification section 7.4 H2 requires a verifier to take ``hashAlg`` from the anchoring
registry, and H3 requires it to reject any algorithm absent from its own configured
allow-list.
:class:`~roax_canon.verify.VerifierConfig` carries both; this module only says which
constructions exist.
"""

from __future__ import annotations

import hashlib
from typing import Callable

from .errors import ErrorCode, RoaxError

__all__ = [
    "REGISTERED_ALGORITHMS",
    "DEFINED_ALGORITHMS",
    "DEFAULT_HASH_ALG",
    "HashAlgorithm",
    "get_hash",
]

#: Every identifier the envelope schema admits.
REGISTERED_ALGORITHMS = ("SHA-256", "Poseidon-BN254")

#: Every identifier `ROAX-CANON/1` gives a construction for.
DEFINED_ALGORITHMS = ("SHA-256",)

DEFAULT_HASH_ALG = "SHA-256"


class HashAlgorithm:
    """One algorithm's construction: a name, a digest function and a digest size."""

    __slots__ = ("name", "_digest", "digest_size")

    def __init__(self, name: str, digest: Callable[[bytes], bytes], digest_size: int) -> None:
        self.name = name
        self._digest = digest
        self.digest_size = digest_size

    def __call__(self, data: bytes) -> bytes:
        return self._digest(data)


_SHA256 = HashAlgorithm("SHA-256", lambda data: hashlib.sha256(data).digest(), 32)


def get_hash(name: str) -> HashAlgorithm:
    """Resolve an algorithm identifier to its construction.

    An unregistered identifier and a registered-but-undefined one are different
    rejections, because a verifier's report should distinguish "this is not an algorithm"
    from "this is an algorithm whose parameterization nobody has pinned yet".
    """
    if name == "SHA-256":
        return _SHA256
    if name in REGISTERED_ALGORITHMS:
        raise RoaxError(
            ErrorCode.HASH_ALG_UNDEFINED,
            f"{name} is registered and its construction is not defined by ROAX-CANON/1 "
            f"(specification section 7.4)",
        )
    raise RoaxError(ErrorCode.HASH_ALG_NOT_ALLOWED, f"unknown hash algorithm {name!r}")
