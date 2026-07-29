"""Unicode handling: the NFC pin, and the surrogate rejection that has to precede it.

`ROAX-CANON/1` pins Unicode 15.1 (specification section 6.1, ruled decision D12a).
An implementation whose NFC tables come from a different Unicode version MAY produce a
different root and MUST NOT claim conformance, so this module exposes the interpreter's
table version rather than hiding it.

Two Python-specific hazards live here, and both are silent rather than loud.

`str` holds an unpaired surrogate happily, and `unicodedata.normalize` passes one
through without complaint.
The failure only surfaces at ``.encode("utf-8")``, which is after the guard in
specification section 11.2 has already run and after the value has been accepted.
Specification section 3.2 requires the rejection at the input boundary, so it is done
explicitly here and never left to the encoder.

`str.isdigit`, `str.isdecimal` and `str.isnumeric` all accept non-ASCII digits, and
`int("１２")` parses fullwidth digits without error.
Nothing in this package uses them; the grammars in `numbers` spell `[0-9]` out.
"""

from __future__ import annotations

import unicodedata

__all__ = [
    "PINNED_UNICODE_VERSION",
    "runtime_unicode_version",
    "unicode_tables_match_pin",
    "check_no_unpaired_surrogates",
    "has_unpaired_surrogate",
    "nfc",
    "utf8",
]

#: The Unicode version `ROAX-CANON/1` pins (specification section 6.1).
#: Carried as the two-part form the specification and the corpus use.
#: Compared against the interpreter's three-part form by major and minor only, because
#: specification section 12.1 makes an externally owned version identifier opaque and
#: `15.1` and `15.1.0` name the same release.
PINNED_UNICODE_VERSION = "15.1"


def runtime_unicode_version() -> str:
    """The Unicode version this interpreter's NFC tables were built against.

    CPython ships one table per interpreter build and offers no way to select another,
    so this is a property of the runtime rather than a setting.
    """
    return unicodedata.unidata_version


def unicode_tables_match_pin() -> bool:
    """Whether this interpreter can claim `ROAX-CANON/1` conformance for strings.

    Compares major and minor only.
    `15.1` is the specification's canonical form for the pin and `15.1.0` is the Unicode
    Standard's own version string for the same release, so a three-part runtime value is
    not a mismatch.
    """
    got = runtime_unicode_version().split(".")
    want = PINNED_UNICODE_VERSION.split(".")
    return got[:2] == want[:2]


def has_unpaired_surrogate(s: str) -> bool:
    """Whether ``s`` contains a code point in the surrogate range U+D800 to U+DFFF.

    A Python `str` is a sequence of code points rather than of UTF-16 code units, so a
    surrogate present here is unpaired by construction: a genuine astral character is one
    code point above U+FFFF and never two surrogates.
    """
    return any(0xD800 <= ord(ch) <= 0xDFFF for ch in s)


def check_no_unpaired_surrogates(s: str, *, where: str = "string") -> None:
    """Reject an unpaired surrogate before normalization (specification section 3.2).

    Ordering matters and is not incidental.
    Specification section 6.1 requires the rejection "before normalization", and
    `unicodedata.normalize` neither rejects nor repairs one.
    """
    from .errors import ErrorCode, InputError

    for i, ch in enumerate(s):
        if 0xD800 <= ord(ch) <= 0xDFFF:
            raise InputError(
                ErrorCode.UNPAIRED_SURROGATE,
                f"{where} carries an unpaired surrogate U+{ord(ch):04X} at index {i}",
            )


def nfc(s: str, *, where: str = "string") -> str:
    """Unicode Normalization Form C, with the section 3.2 rejection applied first.

    Every string and every object key entering a hash preimage passes through here
    (specification section 6.1).
    """
    check_no_unpaired_surrogates(s, where=where)
    return unicodedata.normalize("NFC", s)


def utf8(s: str) -> bytes:
    """UTF-8 bytes of an already-normalized string.

    ``strict`` error handling is the default and is relied on: any surrogate that reached
    here would raise, which is a defect rather than an input condition, because
    :func:`nfc` rejects one first.
    """
    return s.encode("utf-8")
