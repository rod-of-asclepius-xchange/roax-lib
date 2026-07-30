"""Tree construction and inclusion proofs (specification section 9, RFC 9162).

RFC 9162 section 2.1.1 defines ``MTH({d[0]}) = HASH(0x00 ‖ d[0])``, applying the
leaf-domain byte to *raw entries*.
In this design that byte is already inside :func:`~roax_canon.leaf.leaf_hash`, so the
tree function here operates on **already-hashed leaves** and MUST NOT apply ``0x00`` a
second time (specification section 9.1)::

    MTH([])      = H("")
    MTH([x])     = x                                     // NOT H(0x00 ‖ x)
    MTH(L), n>1  = H(0x01 ‖ MTH(L[0:k]) ‖ MTH(L[k:n]))   // k = largest 2^i < n

**A caller-supplied leaf hash is never a membership proof.**
:func:`verify_inclusion` implements RFC 9162 section 2.1.3.2 faithfully, which means it
takes ``tree_size`` as an *input* and therefore cannot detect a forged one.
Specification section 11.1 records the measurement: on an 8-leaf tree the internal node
``MTH(L[0:4])`` presented as the leaf at index 0, with a forged tree size of 2, verifies
against the genuine root.
What closes that is specification section 10 step 2, recomputing the leaf hash from the
disclosed path, tag, value and salt, which :mod:`roax_canon.verify` does and which this
module deliberately does not pretend to do on its behalf.
"""

from __future__ import annotations

from typing import Sequence

from .errors import ErrorCode, TreeError
from .hashes import DEFAULT_HASH_ALG, HashAlgorithm, get_hash

__all__ = ["merkle_tree_head", "audit_path", "verify_inclusion", "largest_power_of_two_below"]


def largest_power_of_two_below(n: int) -> int:
    """The largest power of two strictly smaller than ``n``, for ``n > 1``.

    RFC 9162 section 2.1.1's split rule.
    This is where a hand-rolled tree goes wrong, so it is one named function rather than
    an expression repeated at each call site.
    """
    if n <= 1:
        raise TreeError(ErrorCode.TREE_EMPTY, "split rule needs at least two leaves")
    return 1 << ((n - 1).bit_length() - 1)


def _mth(leaves: Sequence[bytes], h: HashAlgorithm) -> bytes:
    n = len(leaves)
    if n == 0:
        # Unreachable in a conforming implementation: the leaf set is the union of
        # specification section 3.3 and always carries the reserved leaves, so its floor
        # is 5 under the envelope 1.0 reserved set and 6 under 2.0. Kept so the function
        # is total, exactly as specification section 9.1 asks.
        return h(b"")
    if n == 1:
        return leaves[0]
    k = largest_power_of_two_below(n)
    return h(b"\x01" + _mth(leaves[:k], h) + _mth(leaves[k:], h))


def merkle_tree_head(
    leaves: Sequence[bytes],
    *,
    hash_alg: str = DEFAULT_HASH_ALG,
    hasher: HashAlgorithm | None = None,
) -> bytes:
    """``MTH`` over already-hashed leaves, in encoded-path order."""
    h = hasher if hasher is not None else get_hash(hash_alg)
    return _mth(list(leaves), h)


def audit_path(
    index: int,
    leaves: Sequence[bytes],
    *,
    hash_alg: str = DEFAULT_HASH_ALG,
    hasher: HashAlgorithm | None = None,
) -> list[bytes]:
    """RFC 9162 section 2.1.3 ``PATH(m, D[n])``, over already-hashed leaves."""
    h = hasher if hasher is not None else get_hash(hash_alg)
    leaves = list(leaves)
    n = len(leaves)
    if n == 0:
        raise TreeError(ErrorCode.TREE_EMPTY, "no leaves")
    if index < 0 or index >= n:
        raise TreeError(ErrorCode.INCLUSION_PROOF_FAILED, f"leaf index {index} outside [0, {n})")

    path: list[bytes] = []
    m = index
    window = leaves
    while len(window) > 1:
        k = largest_power_of_two_below(len(window))
        if m < k:
            path.append(_mth(window[k:], h))
            window = window[:k]
        else:
            path.append(_mth(window[:k], h))
            window = window[k:]
            m -= k
    path.reverse()
    return path


def verify_inclusion(
    leaf_hash_value: bytes,
    index: int,
    tree_size: int,
    path: Sequence[bytes],
    root: bytes,
    *,
    hash_alg: str = DEFAULT_HASH_ALG,
    hasher: HashAlgorithm | None = None,
) -> bool:
    """RFC 9162 section 2.1.3.2, verbatim, over already-hashed leaves.

    Returns ``True`` only when the fold reconstructs ``root`` *and* the audit path had
    exactly the length the shape requires.
    A truncated path leaves ``sn`` non-zero at step 5 and an extended one runs out of
    tree at step 4a, so both are rejections rather than near misses.
    """
    h = hasher if hasher is not None else get_hash(hash_alg)

    if tree_size <= 0 or index < 0 or index >= tree_size:
        return False

    fn = index
    sn = tree_size - 1
    r = bytes(leaf_hash_value)

    for p in path:
        if sn == 0:
            return False
        if (fn & 1) or fn == sn:
            r = h(b"\x01" + bytes(p) + r)
            while (fn & 1) == 0 and fn != 0:
                fn >>= 1
                sn >>= 1
        else:
            r = h(b"\x01" + r + bytes(p))
        fn >>= 1
        sn >>= 1

    return sn == 0 and r == bytes(root)
