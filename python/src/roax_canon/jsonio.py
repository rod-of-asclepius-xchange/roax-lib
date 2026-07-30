"""A JSON reader that does not destroy the record (specification sections 3.2 and 6.4).

> **Normative:** implementations MUST NOT parse record numbers through any floating-point
> type (specification section 6.4).

Python's :mod:`json` violates that by default in three separate ways, and each has to be
closed explicitly:

1. ``parse_float`` defaults to :class:`float`, so ``0.010`` becomes ``0.01`` and
   ``9223372036854775807`` becomes ``9223372036854776000`` before any of this
   specification's rules run.
2. ``parse_constant`` defaults to producing ``float("nan")`` and ``float("inf")``, so
   ``NaN``, ``Infinity`` and ``-Infinity`` are *accepted*, which specification section
   3.2 forbids.
3. The default object hook is :class:`dict`, which silently keeps the last of a set of
   duplicate keys.
   Specification section 3.2 requires the duplicate to be REJECTED, and the
   OpenAttestation audit (section 9.8) demonstrates the concrete harm of resolving it
   quietly.

There is a fourth hazard that is specific to the obvious fix.
Passing ``parse_int=str, parse_float=str`` preserves the literal correctly and then
collapses the JSON number ``5`` and the JSON string ``"5"`` into the same Python value.
That matters because the type map is keyed on the observed JSON kind (specification
section 4.2), so a collapsed representation resolves the wrong tag.
`corpus/fixtures/records/typed-scalars.json` is built to catch exactly this: it carries
``{"counts": {"integer": 5, "decimal": 0.010, "text": "5"}}`` and the map binds
``counts.integer`` at kind ``number`` and ``counts.text`` at kind ``string``.
:class:`JsonNumber` is the distinct carrier that keeps the two apart, so
:func:`json_kind` reads the Python type and never re-inspects the text.
"""

from __future__ import annotations

import ipaddress
import json
import re
from typing import Any

from .errors import ErrorCode, InputError
from .text import has_unpaired_surrogate

__all__ = [
    "JsonNumber",
    "loads",
    "load_file",
    "json_kind",
    "as_int",
    "is_json_string",
    "is_uri_string",
    "is_nonnegative_schema_integer",
    "is_record_type_string",
]


class JsonNumber(str):
    """A JSON numeric literal, carried verbatim as text.

    A subclass of :class:`str` so the literal is trivially available, and a *distinct*
    type so that a JSON number is never confused with a JSON string.
    Both distinctions are load-bearing: the first is specification section 6.4, the second
    is the type-map lookup key of specification section 4.2.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"JsonNumber({str.__repr__(self)})"


def _reject_constant(name: str) -> Any:
    raise InputError(
        ErrorCode.NON_FINITE_NUMBER,
        f"{name} is not an admissible value (specification section 3.2)",
    )


def _pairs_hook(pairs: list[tuple[str, Any]]) -> dict:
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise InputError(
                ErrorCode.DUPLICATE_KEY,
                f"duplicate object member name {key!r}",
            )
        seen.add(key)
    return dict(pairs)


def _check_surrogates(node: Any, where: str) -> None:
    """Reject unpaired surrogates at the input boundary (specification section 3.2).

    A JSON text may carry ``\\ud800`` as an escape, and Python's decoder produces a lone
    surrogate in the resulting :class:`str` without complaint.
    Left alone, it would survive normalization and only fail at UTF-8 encoding, which is
    after the reserved-namespace guard of specification section 11.2 has already run.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if has_unpaired_surrogate(key):
                raise InputError(
                    ErrorCode.UNPAIRED_SURROGATE,
                    f"object member name at {where} carries an unpaired surrogate",
                )
            _check_surrogates(value, f"{where}/{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _check_surrogates(item, f"{where}/{i}")
    elif isinstance(node, str) and not isinstance(node, JsonNumber):
        if has_unpaired_surrogate(node):
            raise InputError(
                ErrorCode.UNPAIRED_SURROGATE,
                f"string value at {where} carries an unpaired surrogate",
            )


def loads(text: str | bytes) -> Any:
    """Parse JSON text, preserving numeric literals and rejecting what section 3.2 lists.

    Accepts :class:`str` or :class:`bytes`.
    Bytes are decoded as strict UTF-8, so an invalid sequence is a rejection rather than a
    replacement character.
    """
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InputError(ErrorCode.MALFORMED_JSON, f"not valid UTF-8: {exc}") from exc
    try:
        parsed = json.loads(
            text,
            parse_int=JsonNumber,
            parse_float=JsonNumber,
            parse_constant=_reject_constant,
            object_pairs_hook=_pairs_hook,
        )
    except InputError:
        raise
    except json.JSONDecodeError as exc:
        raise InputError(ErrorCode.MALFORMED_JSON, str(exc)) from exc
    _check_surrogates(parsed, "")
    return parsed


def load_file(path: str) -> Any:
    """Read and parse a file with :func:`loads`."""
    with open(path, "rb") as handle:
        return loads(handle.read())


def json_kind(node: Any) -> str:
    """The observed JSON kind, as the type map keys on (specification section 4.2).

    ``bool`` is tested before ``JsonNumber`` because Python's :class:`bool` is a subclass
    of :class:`int`; the ordering is defensive rather than reachable, since this reader
    never produces a bare :class:`int`.
    """
    if node is None:
        return "null"
    if isinstance(node, bool):
        return "boolean"
    if isinstance(node, JsonNumber):
        return "number"
    if isinstance(node, str):
        return "string"
    if isinstance(node, dict):
        return "object"
    if isinstance(node, list):
        return "array"
    if isinstance(node, (int, float)):
        # Reachable only if a caller hands in a Python-native structure rather than one
        # this reader produced. A float here has already lost the literal, so it is a
        # rejection rather than a coercion.
        raise InputError(
            ErrorCode.NON_FINITE_NUMBER,
            "record numbers must be carried as JsonNumber, not as a Python numeric type "
            "(specification section 6.4)",
        )
    raise InputError(ErrorCode.MALFORMED_JSON, f"not an admissible value: {node!r}")


def is_json_string(value: Any) -> bool:
    """True only for a value that arrived as a JSON *string*.

    :class:`JsonNumber` subclasses :class:`str` so the literal survives verbatim, which
    means a bare ``isinstance(value, str)`` test also accepts a JSON number.
    Wherever a member is required to BE a string - an envelope identity field that becomes
    a reserved STRING leaf (specification section 11.2), a `KEY` path segment
    (specification section 5), a type-map pattern - that acceptance would collapse the JSON
    number ``5`` and the JSON string ``"5"`` into the same committed bytes, which is the
    very collapse :class:`JsonNumber` exists to prevent.
    """
    return isinstance(value, str) and not isinstance(value, JsonNumber)


_URI_SCHEME = re.compile(r"\A[A-Za-z][A-Za-z0-9+.-]*\Z")
_RECORD_TYPE = re.compile(r"\A[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)+\Z")
_IPV_FUTURE = re.compile(r"\A[vV][0-9A-Fa-f]+\.[A-Za-z0-9._~!$&'()*+,;=:-]+\Z")
_URI_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_URI_SUB_DELIMITERS = frozenset("!$&'()*+,;=")
_URI_PCHAR = _URI_UNRESERVED | _URI_SUB_DELIMITERS | frozenset(":@")
_URI_QUERY_OR_FRAGMENT = _URI_PCHAR | frozenset("/?")
_URI_USERINFO = _URI_UNRESERVED | _URI_SUB_DELIMITERS | frozenset(":")
_URI_REG_NAME = _URI_UNRESERVED | _URI_SUB_DELIMITERS


def _uri_component_is_valid(value: str, allowed: frozenset[str]) -> bool:
    index = 0
    while index < len(value):
        character = value[index]
        if character == "%":
            escape = value[index + 1 : index + 3]
            if len(escape) != 2 or any(ch not in "0123456789abcdefABCDEF" for ch in escape):
                return False
            index += 3
            continue
        if character not in allowed:
            return False
        index += 1
    return True


def _uri_authority_is_valid(authority: str) -> bool:
    if authority.count("@") > 1:
        return False
    if "@" in authority:
        userinfo, host_and_port = authority.split("@", 1)
        if not _uri_component_is_valid(userinfo, _URI_USERINFO):
            return False
    else:
        host_and_port = authority

    if "[" not in host_and_port and "]" not in host_and_port:
        if host_and_port.count(":") > 1:
            return False
        if ":" in host_and_port:
            host, port = host_and_port.rsplit(":", 1)
            if any(digit not in "0123456789" for digit in port):
                return False
        else:
            host = host_and_port
        return _uri_component_is_valid(host, _URI_REG_NAME)

    if not host_and_port.startswith("[") or host_and_port.count("[") != 1:
        return False
    closing = host_and_port.find("]")
    if closing < 0 or host_and_port.count("]") != 1:
        return False
    literal = host_and_port[1:closing]
    suffix = host_and_port[closing + 1 :]
    if suffix and (
        not suffix.startswith(":") or any(digit not in "0123456789" for digit in suffix[1:])
    ):
        return False
    if _IPV_FUTURE.match(literal) is not None:
        return True
    try:
        ipaddress.IPv6Address(literal)
    except ipaddress.AddressValueError:
        return False
    return True


def is_uri_string(value: Any) -> bool:
    """Whether a genuine JSON string has an RFC 3986 generic absolute-URI shape.

    The envelope schema permits any URI scheme, including ``did``, ``urn`` and
    ``https``, so this boundary deliberately does not invent scheme-specific host or path
    rules.
    It requires an ASCII scheme, a colon, a non-empty scheme-specific part, only RFC 3986
    unreserved/reserved characters, well-formed percent escapes, and brackets only around
    a valid IP literal in the authority host position.
    This is stricter than the pinned Ajv format checker for malformed percent escapes but
    does not claim to validate the semantics of any individual scheme.
    """
    if not is_json_string(value):
        return False
    scheme, separator, remainder = value.partition(":")
    if not separator or not remainder or _URI_SCHEME.match(scheme) is None:
        return False

    if remainder.count("#") > 1:
        return False
    before_fragment, fragment_separator, fragment = remainder.partition("#")
    hierarchy, query_separator, query = before_fragment.partition("?")
    if not hierarchy:
        return False
    if query_separator and not _uri_component_is_valid(query, _URI_QUERY_OR_FRAGMENT):
        return False
    if fragment_separator and not _uri_component_is_valid(fragment, _URI_QUERY_OR_FRAGMENT):
        return False

    if hierarchy.startswith("//"):
        authority_and_path = hierarchy[2:]
        path_start = authority_and_path.find("/")
        if path_start < 0:
            authority, path = authority_and_path, ""
        else:
            authority = authority_and_path[:path_start]
            path = authority_and_path[path_start:]
        return _uri_authority_is_valid(authority) and _uri_component_is_valid(
            path, _URI_PCHAR | frozenset("/")
        )
    return _uri_component_is_valid(hierarchy, _URI_PCHAR | frozenset("/"))


def is_record_type_string(value: Any) -> bool:
    """Whether a genuine JSON string has the envelope's reverse-DNS profile form."""
    return is_json_string(value) and _RECORD_TYPE.match(value) is not None


def is_nonnegative_schema_integer(value: Any) -> bool:
    """Whether a value satisfies JSON Schema ``integer`` and ``minimum: 0``.

    Unlike :func:`as_int`, this predicate imposes no conversion-size bound.
    It is for schema metadata such as ``anchor.chainId`` that is validated but never used
    arithmetically, and it decides integrality from decimal text without constructing a
    potentially enormous Python integer.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    if not isinstance(value, JsonNumber):
        return False

    from .numbers import DECIMAL_INPUT_GRAMMAR

    match = DECIMAL_INPUT_GRAMMAR.match(value)
    if match is None:
        return False
    coefficient = match.group("int") + (match.group("frac") or "")
    if not coefficient.strip("0"):
        return True
    if match.group("sign"):
        return False

    fraction_length = len(match.group("frac") or "")
    exponent_text = match.group("exp") or "0"
    exponent_negative = exponent_text.startswith("-")
    exponent_magnitude_text = exponent_text.lstrip("+-").lstrip("0") or "0"
    # Past this threshold a positive exponent necessarily leaves an integer, while a
    # negative one necessarily asks to remove more decimal places than this non-zero
    # coefficient contains. Compare text first so an attacker cannot choose an int()
    # conversion larger than CPython's configured limit.
    relevant_exponent = len(coefficient) + fraction_length
    relevant_text = str(relevant_exponent)
    if len(exponent_magnitude_text) > len(relevant_text) or (
        len(exponent_magnitude_text) == len(relevant_text)
        and exponent_magnitude_text > relevant_text
    ):
        return not exponent_negative

    exponent_magnitude = int(exponent_magnitude_text)
    exponent = -exponent_magnitude if exponent_negative else exponent_magnitude
    scale = exponent - fraction_length
    if scale >= 0:
        return True
    removed = -scale
    return removed <= len(coefficient) and all(
        digit == "0" for digit in coefficient[len(coefficient) - removed :]
    )


#: The most decimal digits :func:`as_int` will convert.
#: Every field it reads is integer protocol metadata rather than a record value, and
#: specification section 5 bounds an array index below 2^32, so a bound at the 20 digits
#: of 2^64 - 1 is generous by roughly ten orders of magnitude and still rejects on this
#: specification's own terms.
#: Without it CPython's configurable :func:`int` conversion limit, whose default is 4300
#: digits, raises :class:`ValueError` out of a verifier that converts the explicitly
#: enumerated malformed-member failures into results; that is the same interpreter hazard
#: :mod:`roax_canon.numbers` already refuses for a decimal exponent (numbers.py,
#: ``_MAX_EXPONENT_DIGITS``), met here at a second site.
_MAX_INT_DIGITS = 20


def as_int(value: Any, *, field: str) -> int:
    """Read a JSON Schema ``integer`` field without passing it through a float.

    The whole envelope is read through :func:`loads` so that a full copy's ``record``
    keeps its literals (specification section 7.3), which means ``leafCount`` and
    ``index`` arrive as :class:`JsonNumber` too.
    They are counts rather than record values, so converting them here is correct; doing
    it by an explicit call keeps that decision visible.

    JSON Schema classifies a numeric value by its mathematical value, not by its lexical
    spelling, so ``1``, ``1.0`` and ``1e0`` are all integers.
    The conversion below implements that rule over decimal text and never uses
    :class:`float`, preserving specification section 6.4's parser boundary.
    """
    if isinstance(value, bool) or not isinstance(value, (JsonNumber, int)):
        raise InputError(ErrorCode.ENVELOPE_SHAPE, f"{field} must be an integer")
    if isinstance(value, JsonNumber):
        from .numbers import DECIMAL_INPUT_GRAMMAR

        match = DECIMAL_INPUT_GRAMMAR.match(value)
        if match is None:
            raise InputError(ErrorCode.ENVELOPE_SHAPE, f"{field} must be an integer")
        integer_digits = match.group("int")
        fraction_digits = match.group("frac") or ""
        coefficient = integer_digits + fraction_digits
        if not coefficient.strip("0"):
            return 0

        exponent_text = match.group("exp") or "0"
        exponent_negative = exponent_text.startswith("-")
        exponent_magnitude_text = exponent_text.lstrip("+-").lstrip("0") or "0"
        # An exponent larger than the coefficient plus the accepted output bound either
        # pads far past the bound or requires more trailing zeros than the coefficient
        # contains. Compare its decimal text before calling int(), so CPython's
        # configurable string-conversion limit never chooses the rejection.
        relevant_exponent = len(coefficient) + len(fraction_digits) + _MAX_INT_DIGITS
        relevant_text = str(relevant_exponent)
        if len(exponent_magnitude_text) > len(relevant_text) or (
            len(exponent_magnitude_text) == len(relevant_text)
            and exponent_magnitude_text > relevant_text
        ):
            if exponent_negative:
                raise InputError(ErrorCode.ENVELOPE_SHAPE, f"{field} must be an integer")
            raise InputError(
                ErrorCode.ENVELOPE_SHAPE,
                f"{field} is past the {_MAX_INT_DIGITS}-digit bound this reader converts",
            )
        exponent_magnitude = int(exponent_magnitude_text)
        exponent = -exponent_magnitude if exponent_negative else exponent_magnitude
        scale = exponent - len(fraction_digits)

        if scale < 0:
            removed = -scale
            if removed > len(coefficient) or any(
                digit != "0" for digit in coefficient[len(coefficient) - removed :]
            ):
                raise InputError(ErrorCode.ENVELOPE_SHAPE, f"{field} must be an integer")
            integral_digits = coefficient[: len(coefficient) - removed]
        else:
            significant = coefficient.lstrip("0")
            if len(significant) + scale > _MAX_INT_DIGITS:
                raise InputError(
                    ErrorCode.ENVELOPE_SHAPE,
                    f"{field} is past the {_MAX_INT_DIGITS}-digit bound this reader converts",
                )
            integral_digits = coefficient + "0" * scale

        integral_digits = integral_digits.lstrip("0") or "0"
        if len(integral_digits) > _MAX_INT_DIGITS:
            raise InputError(
                ErrorCode.ENVELOPE_SHAPE,
                f"{field} carries {len(integral_digits)} digits, past the "
                f"{_MAX_INT_DIGITS}-digit bound this reader converts",
            )
        parsed = int(integral_digits)
        return -parsed if match.group("sign") else parsed
    if abs(value) >= 10**_MAX_INT_DIGITS:
        raise InputError(
            ErrorCode.ENVELOPE_SHAPE,
            f"{field} is past the {_MAX_INT_DIGITS}-digit bound this reader converts",
        )
    return value
