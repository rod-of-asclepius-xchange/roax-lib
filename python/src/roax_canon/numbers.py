"""Canonical INTEGER and DECIMAL, over strings, never through a float.

This module is the reason the project exists (`docs/decisions.md` part 0, specification
section 6.4).
No value here is ever passed to :class:`float`, :class:`int` or :class:`decimal.Decimal`.
Digits are manipulated as text and the decimal point is moved by slicing, so a
forty-digit fraction and a nineteen-digit integer survive unchanged.

Three Python-specific traps are closed here rather than discovered later.

`$` in a Python regular expression also matches immediately before a trailing newline,
where JavaScript's matches only at end of input.
That divergence is already recorded in this repository: it made one reference
implementation accept ``"1.0\\n"`` and canonicalize it while the other rejected it
(`corpus/README.md`, "The divergence the two implementations caught").
Both grammars below are anchored ``\\A`` and ``\\Z``, which have no such behaviour.

`\\d` in a Python regular expression matches non-ASCII decimal digits by default, so
``١٢٣`` would satisfy a ``\\d+`` grammar and then fail or, worse, succeed at
``int()``, which also accepts fullwidth digits.
The grammars spell ``[0-9]`` out, exactly as specification section 6.2 writes them.

CPython 3.11 and later cap :func:`int` to :func:`str` conversion at 4300 digits by
default, so an exponent alone can raise :class:`ValueError` before any of this
specification's own bounds apply.
:func:`_exponent_value` refuses an absurd exponent by digit count before parsing it, so
the specification's 1024-digit bound is what rejects the input rather than an
interpreter setting.
"""

from __future__ import annotations

import re

from .errors import ErrorCode, GrammarError

__all__ = [
    "DIGIT_BOUND",
    "INTEGER_GRAMMAR",
    "DECIMAL_INPUT_GRAMMAR",
    "DECIMAL_OUTPUT_GRAMMAR",
    "canonical_integer",
    "canonical_decimal",
    "expanded_digit_count",
]

#: Specification section 6.2: a fixed constant of `ROAX-CANON/1`, not implementation
#: chosen.
#: Changing it changes which records canonicalize and is therefore a `canon` bump.
DIGIT_BOUND = 1024

#: Specification section 6.2, "Canonical integer".
INTEGER_GRAMMAR = re.compile(r"\A-?(0|[1-9][0-9]*)\Z")

#: Specification section 6.2, "Canonical decimal", input form.
#: This is exactly the FHIR R4 `decimal` pattern as shipped in the reference
#: `fhir/4.0.1/schema.json`, cited by path only.
DECIMAL_INPUT_GRAMMAR = re.compile(
    r"\A(?P<sign>-?)(?P<int>0|[1-9][0-9]*)(?:\.(?P<frac>[0-9]+))?"
    r"(?:[eE](?P<exp>[+-]?[0-9]+))?\Z"
)

#: Specification section 6.2, output form.
#: The same grammar `schemas/envelope-2.0.json` pins for a DECIMAL value.
DECIMAL_OUTPUT_GRAMMAR = re.compile(r"\A-?(0|[1-9][0-9]*)(\.[0-9]+)?\Z")

# An exponent with more decimal digits than this cannot bring the expanded form inside
# DIGIT_BOUND under any mantissa this grammar admits, so it is rejected without being
# parsed. 10 ** 7 already exceeds the bound by four orders of magnitude, in both
# directions: a positive exponent pads the integer part and a negative one pads the
# fraction.
_MAX_EXPONENT_DIGITS = 7


def _exponent_value(exp: str | None) -> int:
    """Parse the exponent, refusing one large enough to be a resource hazard.

    Returns 0 for an absent exponent, which is what specification section 6.2 means by
    "an absent exponent means ``e = 0``".
    """
    if exp is None:
        return 0
    sign = -1 if exp.startswith("-") else 1
    digits = exp.lstrip("+-").lstrip("0")
    if len(digits) > _MAX_EXPONENT_DIGITS:
        raise GrammarError(
            ErrorCode.DIGIT_BOUND_EXCEEDED,
            f"exponent of {len(digits)} digits expands past the {DIGIT_BOUND}-digit bound",
        )
    if not digits:
        return 0
    return sign * int(digits)


def expanded_digit_count(int_digits: str, frac_digits: str, exponent: int) -> int:
    """Digits the expanded positional form carries, computed without materializing it.

    Counts integer digits and fraction digits together, per specification section 6.2.

    **Two readings exist and this takes the literal one**, which is also the memory-safe
    one and the one both reference implementations took (`corpus/README.md`, ambiguity 2):
    the count is of the *padded* form, before the output-grammar normalization strips
    leading zeros.
    Under the other reading ``0e99999`` canonicalizes to ``0``; under this one it is
    rejected.
    No committed vector discriminates, and ``0e99999`` is not in the corpus.
    """
    total = len(int_digits) + len(frac_digits)
    point = len(int_digits) + exponent
    return max(point, 0) + max(total - point, 0)


def canonical_integer(text: str) -> str:
    """Canonical INTEGER form (tag 3), per specification section 6.2.

    Leading zeros are rejected, ``-0`` normalizes to ``0``, and anything else is an error.

    **The 1024-digit bound is applied here as well as to DECIMAL**, and that is a reading
    rather than a quotation.
    Specification section 6.2 states the bound under *Canonical decimal*, while its own
    justification paragraph counts "class 2's 40-digit integer" against it, which only
    makes sense if it governs INTEGER too (`corpus/README.md`, ambiguity 1).
    Both reference implementations read it the same way and no vector discriminates.
    """
    if not isinstance(text, str):
        raise GrammarError(
            ErrorCode.INTEGER_GRAMMAR,
            f"INTEGER value must be carried as a string, got {type(text).__name__}",
        )
    if INTEGER_GRAMMAR.match(text) is None:
        raise GrammarError(ErrorCode.INTEGER_GRAMMAR, f"not a canonical integer literal: {text!r}")
    digits = text[1:] if text.startswith("-") else text
    if len(digits) > DIGIT_BOUND:
        raise GrammarError(
            ErrorCode.DIGIT_BOUND_EXCEEDED,
            f"{len(digits)} digits exceeds the {DIGIT_BOUND}-digit bound",
        )
    if text == "-0":
        return "0"
    return text


def canonical_decimal(text: str) -> str:
    """Canonical DECIMAL form (tag 4), per specification section 6.2.

    Canonicalization does exactly two things: it expands exponent notation into
    positional notation, and it drops the sign of a zero-valued magnitude.
    The digit sequence is never rounded, extended or truncated.

    **Trailing zeros of the fraction are significant and survive.**
    ``0.010`` is not ``0.01``; FHIR R4 says SHALL.
    Trailing zeros of the integer part carry no precision in this grammar, so ``1e2``,
    ``1.0e2`` and ``100`` all encode to ``100`` and are the same leaf, while ``100.0`` is
    a different leaf.
    """
    if not isinstance(text, str):
        raise GrammarError(
            ErrorCode.DECIMAL_GRAMMAR,
            f"DECIMAL value must be carried as a string, got {type(text).__name__}",
        )
    m = DECIMAL_INPUT_GRAMMAR.match(text)
    if m is None:
        raise GrammarError(ErrorCode.DECIMAL_GRAMMAR, f"not a canonical decimal literal: {text!r}")

    sign = m.group("sign")
    int_digits = m.group("int")
    frac_digits = m.group("frac") or ""
    exponent = _exponent_value(m.group("exp"))

    if expanded_digit_count(int_digits, frac_digits, exponent) > DIGIT_BOUND:
        raise GrammarError(
            ErrorCode.DIGIT_BOUND_EXCEEDED,
            f"expanded positional form exceeds the {DIGIT_BOUND}-digit bound: {text!r}",
        )

    # Shift the decimal point right by `exponent` places over the concatenated digits,
    # padding with zeros wherever the point runs past the digits that are present.
    all_digits = int_digits + frac_digits
    point = len(int_digits) + exponent
    if point <= 0:
        int_part = ""
        frac_part = "0" * (-point) + all_digits
    elif point >= len(all_digits):
        int_part = all_digits + "0" * (point - len(all_digits))
        frac_part = ""
    else:
        int_part = all_digits[:point]
        frac_part = all_digits[point:]

    magnitude_is_zero = set(int_part + frac_part) <= {"0"}

    normalized_int = int_part.lstrip("0") or "0"
    out = normalized_int if frac_part == "" else f"{normalized_int}.{frac_part}"
    if sign and not magnitude_is_zero:
        out = "-" + out

    # A defect here would corrupt a root silently, so the output grammar is asserted
    # rather than assumed. This is the same grammar the envelope schema pins.
    assert DECIMAL_OUTPUT_GRAMMAR.match(out) is not None, out
    return out
