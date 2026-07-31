"""ROAX-CANON/1 reference implementation A, in Python.

This is corpus tooling, not roax-lib. It exists to produce and to check the vectors in
`corpus/conformance-corpus-1.0.json`, and it is deliberately small enough to read against
`docs/spec/roax-canon-1.md` line by line. It is not a library: no streaming, no error taxonomy
beyond stable reason codes, no performance work.

Written from the specification text. Implementation B lives in `roax_ref.mjs` and was written
from the same text rather than ported from this file; `crosscheck.py` asserts the two produce
byte-identical corpora.

Section references below are to `docs/spec/roax-canon-1.md`.
"""

from __future__ import annotations

import base64
import hashlib
import re
import unicodedata

CANON = "ROAX-CANON/1"

# Section 6.1 type tags.
TAG_NULL = 0
TAG_BOOL = 1
TAG_STRING = 2
TAG_INTEGER = 3
TAG_DECIMAL = 4
TAG_BYTES = 5
TAG_EMPTY_ARRAY = 6
TAG_EMPTY_OBJECT = 7

TAG_NAMES = {
    TAG_NULL: "NULL",
    TAG_BOOL: "BOOL",
    TAG_STRING: "STRING",
    TAG_INTEGER: "INTEGER",
    TAG_DECIMAL: "DECIMAL",
    TAG_BYTES: "BYTES",
    TAG_EMPTY_ARRAY: "EMPTY_ARRAY",
    TAG_EMPTY_OBJECT: "EMPTY_OBJECT",
}

# Section 6.2, "Bound on expansion". A fixed constant of ROAX-CANON/1, never implementation-chosen.
MAX_EXPANDED_DIGITS = 1024

# Section 5. An index must be representable in 32 bits.
MAX_INDEX = 2**32 - 1

# Section 11.2. Each reserved path is a SINGLE KEY segment carrying the literal dotted name.
RESERVED_PREFIX = "roax."
RESERVED_RECORD_TYPE = "roax.recordType"
RESERVED_SCHEMA_VERSION = "roax.schemaVersion"
RESERVED_TYPE_MAP_ID = "roax.typeMap.id"
RESERVED_RECORD_ID = "roax.recordId"
RESERVED_ISSUER_ID = "roax.issuer.id"
RESERVED_ISSUER_KEY_ID = "roax.issuer.keyId"

# Section 10.2. The four reserved paths every profile's disclosure floor must contain.
# roax.issuer.keyId is deliberately NOT here: it is committed but OPTIONAL to disclose.
#
# roax.typeMap.id IS mandatory to disclose (section 11.2) and is also deliberately not here. This
# tuple is the floor every profile carries UNCONDITIONALLY, and the 54 committed envelope-1.0
# fixtures predate the type-map binding: listing it would demand a leaf they never committed and
# fail 34 vectors that are correct. The binding in envelope.py is conditional instead - it fires
# when EITHER side names a type map - and adds this path to the floor as a CONSEQUENCE of that
# binding rather than as a standing member of it.
RESERVED_DISCLOSURE_FLOOR = (
    RESERVED_RECORD_TYPE,
    RESERVED_SCHEMA_VERSION,
    RESERVED_RECORD_ID,
    RESERVED_ISSUER_ID,
)

# `\Z` and not `$`. Python's `$` also matches immediately before a trailing newline, so `$` here
# would accept "1.0\n" while JavaScript's `$` - which matches only at end of input - rejects it.
# That is a two-implementation divergence hiding inside a regex dialect, and
# `reject-decimal-trailing-newline` in the corpus pins it.
INTEGER_GRAMMAR = re.compile(r"\A-?(0|[1-9][0-9]*)\Z")
DECIMAL_INPUT_GRAMMAR = re.compile(
    r"\A(?P<sign>-?)(?P<int>0|[1-9][0-9]*)(?:\.(?P<frac>[0-9]+))?(?:[eE](?P<exp>[+-]?[0-9]+))?\Z"
)
DECIMAL_OUTPUT_GRAMMAR = re.compile(r"\A-?(0|[1-9][0-9]*)(\.[0-9]+)?\Z")
HEX_BYTES = re.compile(r"\A([0-9a-f]{2})*\Z")
# Section 6.3: RFC 4648 section 4, standard alphabet, required padding, no line wrapping. The
# grammar admits at most one padded final quantum and nothing outside the alphabet, so the
# URL-safe alphabet of RFC 4648 section 5, any line break and absent or excess padding are all
# refused by the pattern alone. Non-zero unused pad bits are a separate check below, because no
# regular expression can express them.
BASE64_CANONICAL = re.compile(r"\A(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?\Z")
BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


class RoaxError(Exception):
    """A conformance rejection. `code` is stable and is what the corpus records."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# --------------------------------------------------------------------------------------------
# Hash agility (sections 7.4, 8, 9)
# --------------------------------------------------------------------------------------------


def domain(hash_alg: str) -> bytes:
    """Section 7: DOMAIN is ASCII "ROAX-CANON/1/" followed by hashAlg. Algorithm-qualified."""
    if hash_alg != "SHA-256":
        # Poseidon-BN254 is registered in the envelope schema but ROAX-CANON/1 defines no
        # construction for it: the field, rate and capacity, round constants and the
        # byte-string-to-field-element encoding are all unpinned (section 7.4).
        raise RoaxError("hash-alg-not-defined", hash_alg)
    return (CANON + "/" + hash_alg).encode("ascii")


def H(hash_alg: str, data: bytes) -> bytes:
    """The hash named by hashAlg. ROAX-CANON/1 defines H for SHA-256 only (section 7.4)."""
    if hash_alg != "SHA-256":
        raise RoaxError("hash-alg-not-defined", hash_alg)
    return hashlib.sha256(data).digest()


def u32be(n: int) -> bytes:
    if n < 0 or n > 0xFFFFFFFF:
        raise RoaxError("u32-out-of-range", str(n))
    return n.to_bytes(4, "big")


def u64be(n: int) -> bytes:
    if n < 0 or n > 0xFFFFFFFFFFFFFFFF:
        raise RoaxError("u64-out-of-range", str(n))
    return n.to_bytes(8, "big")


# --------------------------------------------------------------------------------------------
# Strings (sections 3.2, 6.1)
# --------------------------------------------------------------------------------------------


def reject_unpaired_surrogates(s: str) -> None:
    """Section 3.2 and 6.1: unpaired surrogates MUST be rejected, before normalization.

    Python `str` can hold lone surrogates exactly as a JavaScript string can, so the rejection
    has to be explicit here for the same reason dogtag's TypeScript SDK makes it explicit.
    """
    for ch in s:
        if 0xD800 <= ord(ch) <= 0xDFFF:
            raise RoaxError("unpaired-surrogate", f"U+{ord(ch):04X}")


def nfc(s: str) -> str:
    """Section 6.1. Rejection of unpaired surrogates happens BEFORE normalization."""
    reject_unpaired_surrogates(s)
    return unicodedata.normalize("NFC", s)


def decode_canonical_base64(text: str) -> bytes:
    """Section 6.3. Decode base64 in the ONE form `ROAX-CANON/1` pins, or reject.

    RFC 4648 section 4: the standard alphabet, with padding, and no line wrapping. Four things
    are refused, and the fourth is the one an implementation reaches for a library for and gets
    wrong: the URL-safe alphabet of RFC 4648 section 5, absent or excess padding, any character
    outside the alphabet including a line break, and a final quantum whose UNUSED BITS ARE
    NON-ZERO. RFC 4648 section 3.5 names that last case, and it matters because two different
    strings otherwise decode to the same bytes, so two implementations can disagree about
    whether the record is admissible at all.

    Python's `base64.b64decode(validate=True)` closes the alphabet and the padding length but
    does NOT check the pad bits, so the check below is explicit rather than delegated.
    """
    if not isinstance(text, str):
        raise RoaxError("base64-not-canonical", repr(text))
    if BASE64_CANONICAL.match(text) is None:
        raise RoaxError("base64-not-canonical", text)
    padding = len(text) - len(text.rstrip("="))
    if padding:
        # Each character carries 6 bits. With one `=` the final quantum keeps 16 of its 18 bits,
        # so the last alphabet character's low 2 bits are unused; with two `=` it keeps 8 of 12
        # and the low 4 are unused. Every unused bit MUST be zero.
        unused_bits = 2 if padding == 1 else 4
        last = BASE64_ALPHABET.index(text[-padding - 1])
        if last & ((1 << unused_bits) - 1):
            raise RoaxError("base64-not-canonical", text)
    return base64.b64decode(text, validate=True)


# --------------------------------------------------------------------------------------------
# Path encoding (section 5)
# --------------------------------------------------------------------------------------------


def encode_path(segments) -> bytes:
    """Section 5. Length-prefixed, no reserved characters and no escaping.

    A segment is {"key": str} or {"index": int}, matching the corpus and envelope schemas.
    """
    out = [u32be(len(segments))]
    for seg in segments:
        if "key" in seg:
            key = nfc(seg["key"])
            kb = key.encode("utf-8")
            out.append(b"\x01" + u32be(len(kb)) + kb)
        elif "index" in seg:
            idx = seg["index"]
            if not isinstance(idx, int) or isinstance(idx, bool):
                raise RoaxError("index-not-integer", repr(idx))
            if idx < 0:
                raise RoaxError("index-negative", str(idx))
            if idx > MAX_INDEX:
                # Section 5: MUST error rather than truncate.
                raise RoaxError("index-out-of-32-bit-range", str(idx))
            out.append(b"\x02" + u32be(idx))
        else:
            raise RoaxError("segment-malformed", repr(seg))
    return b"".join(out)


def display_path(segments) -> str:
    """Section 5.2. Display only. Never hashed, never parsed back into segments."""
    parts = []
    for seg in segments:
        if "key" in seg:
            parts.append(("." if parts else "") + seg["key"])
        else:
            parts.append("[%d]" % seg["index"])
    return "".join(parts)


# --------------------------------------------------------------------------------------------
# Numbers (section 6.2)
# --------------------------------------------------------------------------------------------


def canonical_integer(text: str) -> str:
    """Section 6.2 canonical integer. Arbitrary precision, never parsed into a machine integer."""
    if not isinstance(text, str):
        raise RoaxError("integer-not-carried-as-string", repr(text))
    if not INTEGER_GRAMMAR.match(text):
        raise RoaxError("integer-grammar", text)
    digits = text[1:] if text.startswith("-") else text
    if len(digits) > MAX_EXPANDED_DIGITS:
        # See docs: the 1024-digit bound is stated in the decimal subsection but its own
        # justification paragraph counts class 2's 40-digit INTEGER against it, so it is applied
        # to both here. No corpus vector discriminates between the two readings.
        raise RoaxError("digit-bound-exceeded", str(len(digits)))
    if text == "-0":
        return "0"
    return text


def canonical_decimal(text: str) -> str:
    """Section 6.2 canonical decimal. Arbitrary precision, never parsed into a float.

    Canonicalization does only two things: expand exponent notation into positional notation,
    and drop the sign of a zero-valued magnitude.
    """
    if not isinstance(text, str):
        raise RoaxError("decimal-not-carried-as-string", repr(text))
    m = DECIMAL_INPUT_GRAMMAR.match(text)
    if not m:
        raise RoaxError("decimal-grammar", text)

    sign = m.group("sign")
    int_digits = m.group("int")
    frac_digits = m.group("frac") or ""
    exp = int(m.group("exp")) if m.group("exp") is not None else 0

    digits = int_digits + frac_digits
    # Shift the decimal point right by `exp` places. `point` counts digits from the left.
    point = len(int_digits) + exp

    # Section 6.2: the bound is on the EXPANDED POSITIONAL FORM, before the output-grammar
    # normalization below. Counted arithmetically and rejected BEFORE the padding is built: the
    # input grammar admits any exponent, so materializing the padding first turns `1e999999999`
    # into a gigabyte allocation and a large enough exponent into a MemoryError instead of the
    # stable digit-bound-exceeded the reject vectors are built on.
    expanded = max(point, len(digits)) + max(0, -point)
    if expanded > MAX_EXPANDED_DIGITS:
        raise RoaxError("digit-bound-exceeded", str(expanded))

    if point >= len(digits):
        int_part = digits + "0" * (point - len(digits))
        frac_part = ""
    elif point <= 0:
        int_part = ""
        frac_part = "0" * (-point) + digits
    else:
        int_part = digits[:point]
        frac_part = digits[point:]

    int_part = int_part.lstrip("0")
    if int_part == "":
        int_part = "0"
    # "a fraction of zero digits is dropped along with its `.`" - a fraction with no digits.
    # A fraction whose digits are all zero is KEPT: -0.00 -> 0.00 keeps its precision.
    out = int_part + ("." + frac_part if frac_part != "" else "")

    if sign == "-" and set(digits) == {"0"}:
        # A zero-valued magnitude loses its sign and keeps its fraction digits.
        pass
    elif sign == "-":
        out = "-" + out

    if not DECIMAL_OUTPUT_GRAMMAR.match(out):  # pragma: no cover - defensive
        raise RoaxError("decimal-output-grammar", out)
    return out


# --------------------------------------------------------------------------------------------
# Value encoding (section 6)
# --------------------------------------------------------------------------------------------


def encode_value(tag: int, value=None) -> bytes:
    """Section 6.1. `value` arrives in the corpus carrier form for its tag."""
    if tag == TAG_NULL:
        _require_absent(tag, value)
        return b""
    if tag == TAG_BOOL:
        if not isinstance(value, bool):
            raise RoaxError("bool-carrier", repr(value))
        return b"\x01" if value else b"\x00"
    if tag == TAG_STRING:
        if not isinstance(value, str):
            raise RoaxError("string-carrier", repr(value))
        return nfc(value).encode("utf-8")
    if tag == TAG_INTEGER:
        return canonical_integer(value).encode("ascii")
    if tag == TAG_DECIMAL:
        return canonical_decimal(value).encode("ascii")
    if tag == TAG_BYTES:
        if not isinstance(value, str) or not HEX_BYTES.match(value):
            raise RoaxError("bytes-carrier", repr(value))
        return bytes.fromhex(value)
    if tag == TAG_EMPTY_ARRAY or tag == TAG_EMPTY_OBJECT:
        _require_absent(tag, value)
        return b""
    raise RoaxError("tag-unknown", repr(tag))


def _require_absent(tag: int, value) -> None:
    if value is not None:
        raise RoaxError("value-must-be-absent", f"tag {TAG_NAMES[tag]}")


# --------------------------------------------------------------------------------------------
# Salts (section 7)
# --------------------------------------------------------------------------------------------
#
# Decision D4 is ruled D4b, so there is NOTHING TO DERIVE HERE. Every salt is 16 bytes drawn
# independently from a CSPRNG at issuance, with at least 128 bits of entropy, and no key
# derivation function, master secret or salt preimage exists in this design (spec section 7).
#
# A salt is therefore an INPUT to this implementation rather than something it computes. That is
# what makes a fixed vector file possible at all: the corpus build draws each salt once and
# commits it, and both implementations read the committed set. An earlier version of this file
# derived salts by HMAC-SHA-256 over a master salt and a preimage carrying the record identifier,
# which is the D4a construction the ruling deleted.

SALT_BYTES = 16


class SaltSet:
    """The committed salt of every leaf of one record, addressed by its structured path.

    This is the `salts` array schemas/envelope-1.0.json defines, in memory. Pairing is by
    ENCODED PATH rather than by position, deliberately: a positional array would make
    salt-to-leaf pairing depend on reproducing the section 9 sort before the salts can even be
    read, which is the cross-implementation divergence the corpus exists to prevent
    (spec section 7.2).
    """

    def __init__(self, entries):
        self._by_path = {}
        for entry in entries:
            segments = entry["segments"]
            salt = bytes.fromhex(entry["salt"])
            if len(salt) != SALT_BYTES:
                raise RoaxError("salt-length", str(len(salt)))
            key = encode_path(segments)
            if key in self._by_path:
                raise RoaxError("duplicate-salt-path", "")
            self._by_path[key] = salt

    def for_leaf(self, segments) -> bytes:
        """Fail closed on a missing salt, rather than drawing one.

        A drawn-on-demand salt would make this implementation produce a root that no other
        implementation could reproduce, which is exactly the silent divergence the corpus is
        the enforcement mechanism against.
        """
        key = encode_path(segments)
        if key not in self._by_path:
            raise RoaxError("salt-missing", display_path(segments))
        return self._by_path[key]

    def __len__(self):
        return len(self._by_path)


def salt_set_from_document(doc, ordered) -> "SaltSet":
    """Load a committed corpus salt set, in either of the two carriers class 10 needs.

    `pairing: "path"` is the shape schemas/envelope-1.0.json defines and everything else uses:
    explicit segments per entry, self-describing.

    `pairing: "positional"` is a bare array in encodePath order, and it is a CORPUS-ONLY
    carrier that MUST NEVER become an envelope shape. Specification section 7.2 rejects it for
    an envelope because it makes pairing depend on reproducing the section 9 sort before the
    salts can be read at all; in a corpus vector reproducing that sort is the thing under test,
    so a mispairing fails the vector instead of yielding a silently wrong root. It exists
    because the class-10 records are third-party reference samples at 69 and 70 leaves, and a
    path-keyed set would enumerate every path of one into a public repository, which the
    references policy forbids. A positional array discloses only the leaf count, which the
    vector already publishes as leafCount. See docs/conformance-corpus.md class 10.
    """
    pairing = doc.get("pairing")
    salts = doc.get("salts")
    if pairing == "path":
        return SaltSet(salts)
    if pairing == "positional":
        if len(salts) != len(ordered):
            raise RoaxError("salt-count-mismatch", f"{len(salts)} salts for {len(ordered)} leaves")
        return SaltSet(
            [{"segments": leaf.segments, "salt": s} for leaf, s in zip(ordered, salts)]
        )
    raise RoaxError("salt-pairing-unknown", repr(pairing))


# --------------------------------------------------------------------------------------------
# Leaf construction (section 8)
# --------------------------------------------------------------------------------------------


def leaf_hash(hash_alg: str, segments, tag: int, value, salt: bytes) -> bytes:
    """Section 8."""
    if len(salt) != 16:
        raise RoaxError("salt-length", str(len(salt)))
    dom = domain(hash_alg)
    p = encode_path(segments)
    v = encode_value(tag, value)
    preimage = (
        b"\x00"
        + u32be(len(dom))
        + dom
        + u32be(len(p))
        + p
        + bytes([tag])
        + u32be(len(salt))
        + salt
        + u64be(len(v))
        + v
    )
    return H(hash_alg, preimage)


# --------------------------------------------------------------------------------------------
# Tree construction (section 9), RFC 9162 section 2.1.1 over already-hashed leaves
# --------------------------------------------------------------------------------------------


def _largest_power_of_two_below(n: int) -> int:
    """The largest power of two STRICTLY smaller than n. n > 1."""
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def mth(hash_alg: str, leaves) -> bytes:
    """Section 9.1. The 0x00 leaf-domain byte is already inside leafHash and is NOT reapplied."""
    n = len(leaves)
    if n == 0:
        # Total function only. Unreachable in a conforming implementation: the leaf set is a
        # union that always carries the reserved leaves, so the floor is 5 (section 9.1).
        return H(hash_alg, b"")
    if n == 1:
        return leaves[0]
    k = _largest_power_of_two_below(n)
    return H(hash_alg, b"\x01" + mth(hash_alg, leaves[:k]) + mth(hash_alg, leaves[k:]))


def inclusion_path(hash_alg: str, index: int, leaves):
    """RFC 9162 section 2.1.3 PATH(m, D[n]). Ordered leaf-ward first, root-ward last."""
    n = len(leaves)
    if index < 0 or index >= n:
        raise RoaxError("leaf-index-out-of-range", f"{index} of {n}")
    if n == 1:
        return []
    k = _largest_power_of_two_below(n)
    if index < k:
        return inclusion_path(hash_alg, index, leaves[:k]) + [mth(hash_alg, leaves[k:])]
    return inclusion_path(hash_alg, index - k, leaves[k:]) + [mth(hash_alg, leaves[:k])]


def verify_inclusion(hash_alg: str, leaf: bytes, index: int, tree_size: int, path, root: bytes) -> bool:
    """RFC 9162 section 2.1.3.2, unchanged, over already-hashed leaves."""
    if tree_size <= 0 or index < 0 or index >= tree_size:
        return False
    fn = index
    sn = tree_size - 1
    r = leaf
    for p in path:
        if len(p) != len(leaf):
            return False
        if sn == 0:
            return False
        if (fn & 1) == 1 or fn == sn:
            r = H(hash_alg, b"\x01" + p + r)
            while (fn & 1) == 0 and fn != 0:
                fn >>= 1
                sn >>= 1
        else:
            r = H(hash_alg, b"\x01" + r + p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == root


# --------------------------------------------------------------------------------------------
# Flattening and the reserved leaf set (sections 3.3, 11.2)
# --------------------------------------------------------------------------------------------


class Leaf:
    __slots__ = ("segments", "tag", "value")

    def __init__(self, segments, tag, value=None):
        self.segments = segments
        self.tag = tag
        self.value = value

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Leaf({display_path(self.segments)!r}, {TAG_NAMES[self.tag]}, {self.value!r})"


def check_reserved_namespace(segments) -> None:
    """Section 11.2 reserved-namespace guard.

    Three ways to get this wrong, all avoided here:
      - it is not a test against a rendered display path (section 5.2);
      - it applies to the FIRST segment only, because every reserved path is a single segment;
      - it compares the NFC-normalized key, not the bytes as received.
    """
    if not segments:
        return
    first = segments[0]
    if "key" not in first:
        return
    if nfc(first["key"]).startswith(RESERVED_PREFIX):
        raise RoaxError("reserved-namespace", first["key"])


def flatten(node, type_map, segments=None):
    """Section 3.3. A leaf for every scalar and for every EMPTY container.

    `type_map` supplies the tag for every scalar. The tag MUST come from the schema and never
    from the JSON literal's syntax (section 4), so there is no syntactic fallback here: an
    uncovered path raises, which is the fail-closed rule of section 4.2.
    """
    segments = segments or []
    check_reserved_namespace(segments)

    if isinstance(node, RecordMap):
        if not node.items:
            return [Leaf(segments, TAG_EMPTY_OBJECT)]
        out = []
        seen = set()
        for k, v in node.items:
            if k in seen:
                raise RoaxError("duplicate-key", k)
            seen.add(k)
            out.extend(flatten(v, type_map, segments + [{"key": k}]))
        return out
    if isinstance(node, list):
        if not node:
            return [Leaf(segments, TAG_EMPTY_ARRAY)]
        out = []
        for i, v in enumerate(node):
            out.extend(flatten(v, type_map, segments + [{"index": i}]))
        return out

    tag = type_map.resolve(segments, json_kind(node))
    return [Leaf(segments, tag, carrier(tag, node))]


class RecordMap:
    """An ordered map that preserves duplicate keys so the flattener can reject them.

    A plain dict would silently drop a duplicate, which is exactly the OpenAttestation failure
    section 3.2 requires an implementation to reject rather than inherit.
    """

    __slots__ = ("items",)

    def __init__(self, items):
        self.items = list(items)


class NumberLiteral:
    """A JSON number captured as its verbatim source text (section 6.4).

    Never parsed through a float. This type is how a record carries a number from the parser to
    the canonicalizer without any numeric type touching it.
    """

    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"NumberLiteral({self.text!r})"


def json_kind(node) -> str:
    if node is None:
        return "null"
    if isinstance(node, bool):
        return "boolean"
    if isinstance(node, NumberLiteral):
        return "number"
    if isinstance(node, str):
        return "string"
    if isinstance(node, list):
        return "array"
    if isinstance(node, RecordMap):
        return "object"
    raise RoaxError("value-kind-unknown", repr(node))


def carrier(tag: int, node):
    """Convert a parsed record node into the carrier form `encode_value` expects."""
    if tag in (TAG_NULL, TAG_EMPTY_ARRAY, TAG_EMPTY_OBJECT):
        if node is not None:
            raise RoaxError("tag-value-mismatch", f"{TAG_NAMES[tag]} at a non-null value")
        return None
    if tag == TAG_BOOL:
        if not isinstance(node, bool):
            raise RoaxError("tag-value-mismatch", "BOOL")
        return node
    if tag == TAG_STRING:
        if isinstance(node, NumberLiteral):
            # A schema-declared string carrying a JSON number literal. Fail closed rather than
            # coerce: coercion is syntactic inference arriving through the back door.
            raise RoaxError("tag-value-mismatch", "STRING at a JSON number")
        if not isinstance(node, str):
            raise RoaxError("tag-value-mismatch", "STRING")
        return node
    if tag in (TAG_INTEGER, TAG_DECIMAL):
        if isinstance(node, NumberLiteral):
            return node.text
        if isinstance(node, str):
            # A schema-declared numeric element carrying a JSON string. FHIR does this nowhere,
            # so fail closed rather than guess which the issuer meant.
            raise RoaxError("tag-value-mismatch", f"{TAG_NAMES[tag]} at a JSON string")
        raise RoaxError("tag-value-mismatch", TAG_NAMES[tag])
    if tag == TAG_BYTES:
        # Section 6.3, and ruled 2026-07-30 for FHIR `base64Binary`: BYTES commits the DECODED
        # OCTETS, and the canonical RFC 4648 section 4 spelling is an INPUT-ADMISSIBILITY
        # condition rather than the committed value. So the decode happens here, once, at the
        # record boundary, and the carrier `encode_value` receives is already the octets in hex.
        #
        # A record embedding base64 that a profile binds STRING is a different thing and is
        # unchanged: that field commits its base64 TEXT under NFC and no base64 rule enters its
        # digest.
        if isinstance(node, NumberLiteral):
            raise RoaxError("tag-value-mismatch", "BYTES at a JSON number")
        if not isinstance(node, str):
            raise RoaxError("tag-value-mismatch", "BYTES")
        return decode_canonical_base64(node).hex()
    raise RoaxError("tag-unknown", repr(tag))


def reserved_leaves(record_type: str, schema_version: str, record_id: str, issuer_id: str,
                    issuer_key_id=None, type_map_id=None):
    """Section 11.2. Four always, plus roax.issuer.keyId only when issuer.keyId is present.

    An absent issuer.keyId emits NO leaf. It MUST NOT become a NULL leaf or an empty string:
    those are three different roots and only one of them can be right.

    roax.typeMap.id is emitted when, and only when, the issuance names a type map. Section 11.2
    marks it ALWAYS emitted, which is the envelope-2.0 reading; this corpus is envelope-1.0
    throughout and most of its envelope fixtures were issued without a type map, so the leaf is
    conditional here for the same reason schemas/envelope-1.0.json leaves the `typeMap` member
    optional - requiring it would invalidate every envelope already issued under that schema.
    """
    out = [
        Leaf([{"key": RESERVED_RECORD_TYPE}], TAG_STRING, record_type),
        Leaf([{"key": RESERVED_SCHEMA_VERSION}], TAG_STRING, schema_version),
        Leaf([{"key": RESERVED_RECORD_ID}], TAG_STRING, record_id),
        Leaf([{"key": RESERVED_ISSUER_ID}], TAG_STRING, issuer_id),
    ]
    if type_map_id is not None:
        out.append(Leaf([{"key": RESERVED_TYPE_MAP_ID}], TAG_STRING, type_map_id))
    if issuer_key_id is not None:
        out.append(Leaf([{"key": RESERVED_ISSUER_KEY_ID}], TAG_STRING, issuer_key_id))
    return out


def ordered_leaves(record, type_map, record_type: str, schema_version: str, record_id: str,
                   issuer_id: str, issuer_key_id=None, type_map_id=None):
    """Sections 3.3 and 9. The leaf set, in encodePath order, WITHOUT any salt.

    Split out from build_tree when decision D4 was ruled D4b. Leaf order is a function of the
    path set alone (spec section 9), so it is computable before a salt exists - which is what
    lets a caller draw a salt set for a record, and what lets the envelope verifier recover leaf
    order without inventing salt values to get it.

    The union of the reserved leaves and the record's own is formed BEFORE the sort, so the two
    are indistinguishable to the tree function.
    """
    record_leaves = flatten(record, type_map)
    if not record_leaves:
        # Section 3.3: a record contributing zero leaves of its own MUST be rejected at
        # issuance rather than anchored. The union is never empty, so this is a check on the
        # record's own contribution and not on the tree.
        raise RoaxError("record-contributes-no-leaves", "")

    leaves = reserved_leaves(
        record_type, schema_version, record_id, issuer_id, issuer_key_id, type_map_id
    ) + record_leaves

    encoded = [(encode_path(leaf.segments), leaf) for leaf in leaves]
    paths = [e for e, _ in encoded]
    if len(set(paths)) != len(paths):
        raise RoaxError("duplicate-path", "")
    encoded.sort(key=lambda pair: pair[0])
    return [leaf for _, leaf in encoded]


def build_tree(hash_alg: str, record, type_map, salts: "SaltSet", record_type: str,
               schema_version: str, record_id: str, issuer_id: str, issuer_key_id=None,
               type_map_id=None):
    """Sections 3.3, 7, 8 and 9. Returns (root, ordered leaves, salts, leaf hashes).

    `salts` is a SaltSet and is an INPUT: under decision D4b nothing here derives a salt
    (spec section 7). A leaf with no committed salt is an error rather than a fresh draw.
    """
    ordered = ordered_leaves(
        record, type_map, record_type, schema_version, record_id, issuer_id, issuer_key_id,
        type_map_id
    )
    leaf_salts = [salts.for_leaf(leaf.segments) for leaf in ordered]
    hashes = [
        leaf_hash(hash_alg, leaf.segments, leaf.tag, leaf.value, salt)
        for leaf, salt in zip(ordered, leaf_salts)
    ]
    return mth(hash_alg, hashes), ordered, leaf_salts, hashes


# --------------------------------------------------------------------------------------------
# Type map (section 4)
# --------------------------------------------------------------------------------------------


class TypeMap:
    """Section 4. Keyed by (path pattern, observed JSON kind); first matching entry wins.

    Unknown paths fail closed (section 4.2). There is deliberately no default tag and no
    fallback to the observed JSON kind: either would let two libraries carrying different maps
    produce different roots silently.

    **The lookup matches over NFC-normalized keys on BOTH sides** (section 4.2, decision D14
    ruled D14a on 2026-07-30). `parse_pattern` normalizes each pattern token and `_match_from`
    normalizes each segment key, so a key written decomposed resolves to the same binding as its
    composed twin. Section 11.2's rule is "check the bytes you commit", and a STRING leaf commits
    its NFC form, so matching raw would check bytes the record never commits.
    """

    def __init__(self, doc):
        self.doc = doc
        self.record_type = doc["recordType"]
        self.schema_version = doc["schemaVersion"]
        self.version = doc["typeMapVersion"]
        self.entries = [(parse_pattern(e["pattern"]), e) for e in doc["entries"]]

    def resolve(self, segments, kind: str) -> int:
        for pattern, entry in self.entries:
            if "jsonKind" in entry and entry["jsonKind"] != kind:
                continue
            if match_pattern(pattern, segments):
                return entry["tag"]
        raise RoaxError("type-map-uncovered-path", display_path(segments))


def parse_pattern(pattern: str):
    """Parse a display-notation pattern into segment matchers.

    `*` matches any single array index; `**` matches any run of segments.

    A key token is NFC-normalized here, under ruled decision D14a: the lookup compares
    normalized keys on both sides, so a pattern authored in either spelling denotes the same
    path language.

    LIMIT, reported rather than papered over: because the pattern is written in display
    notation, it cannot address a key containing `.`, `[` or `]`, while section 5 deliberately
    admits such keys. Those are rejected here rather than silently mis-parsed.
    """
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        if pattern[i] == "[":
            j = pattern.index("]", i)
            body = pattern[i + 1:j]
            if body == "*":
                out.append(("index", None))
            elif body.isdigit():
                out.append(("index", int(body)))
            else:
                raise RoaxError("type-map-pattern", pattern)
            i = j + 1
            if i < n and pattern[i] == ".":
                i += 1
            continue
        j = i
        while j < n and pattern[j] not in ".[":
            j += 1
        token = pattern[i:j]
        if token == "**":
            out.append(("any", None))
        elif token == "":
            raise RoaxError("type-map-pattern", pattern)
        else:
            if "]" in token:
                raise RoaxError("type-map-pattern", pattern)
            out.append(("key", nfc(token)))
        i = j
        if i < n and pattern[i] == ".":
            i += 1
    return out


def match_pattern(pattern, segments) -> bool:
    return _match_from(pattern, 0, segments, 0)


def _match_from(pattern, pi: int, segments, si: int) -> bool:
    while pi < len(pattern):
        kind, arg = pattern[pi]
        if kind == "any":
            for skip in range(si, len(segments) + 1):
                if _match_from(pattern, pi + 1, segments, skip):
                    return True
            return False
        if si >= len(segments):
            return False
        seg = segments[si]
        if kind == "key":
            # Ruled decision D14a: compare the NFC-normalized key, which is the key the leaf
            # actually commits (section 11.2), rather than the bytes as received.
            if "key" not in seg or nfc(seg["key"]) != arg:
                return False
        else:
            if "index" not in seg:
                return False
            if arg is not None and seg["index"] != arg:
                return False
        pi += 1
        si += 1
    return si == len(segments)
