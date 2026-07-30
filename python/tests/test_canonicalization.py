"""Canonicalization unit tests: numbers, text, paths and values.

These cover what the conformance corpus reaches plus the Python-specific traps it cannot
see, because a trap that is closed by accident reopens on the next edit.
Standard library only: there is no package manifest in this repository by design, so a
test that needed `pytest` could not be run by anyone who just cloned it.

    python3 -m unittest discover -s python/tests -t python
"""

from __future__ import annotations

import re
import sys
import unittest

from roax_canon import (
    DIGIT_BOUND,
    PINNED_UNICODE_VERSION,
    BlobRef,
    Index,
    Key,
    RoaxError,
    canonical_decimal,
    canonical_integer,
    display_path,
    encode_path,
    encode_value,
    nfc,
    runtime_unicode_version,
    unicode_tables_match_pin,
)
from roax_canon.errors import ErrorCode
from roax_canon.numbers import DECIMAL_INPUT_GRAMMAR, INTEGER_GRAMMAR
from roax_canon.value import BYTES, DECIMAL, INTEGER, NULL, STRING, decode_base64_canonical


class TestDecimal(unittest.TestCase):
    def test_worked_examples_from_section_6_2(self):
        for text, want in [
            ("1e2", "100"),
            ("1.0e2", "100"),
            ("1.00e1", "10.0"),
            ("1.5e-2", "0.015"),
            ("1e-3", "0.001"),
            ("0e5", "0"),
            ("0.010", "0.010"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(canonical_decimal(text), want)

    def test_trailing_zeros_in_the_fraction_are_significant(self):
        # FHIR R4 says SHALL. dogtag strips them at
        # `dogtag-mono-repo` crates/dogtag-standard-rs/src/encode.rs:51-59 and ROAX
        # deliberately does not.
        self.assertNotEqual(canonical_decimal("0.010"), canonical_decimal("0.01"))
        self.assertEqual(canonical_decimal("1.50"), "1.50")
        self.assertEqual(canonical_decimal("2.0"), "2.0")
        self.assertEqual(canonical_decimal("-0.00"), "0.00")

    def test_integer_part_trailing_zeros_carry_no_precision(self):
        same = {canonical_decimal(t) for t in ("1e2", "1.0e2", "100")}
        self.assertEqual(same, {"100"})
        self.assertNotEqual(canonical_decimal("100.0"), "100")

    def test_arbitrary_precision_survives(self):
        big = "1234567890123456789012345678901234567890"
        self.assertEqual(canonical_decimal(big), big)
        self.assertEqual(canonical_decimal("1234567890123456789.1"), "1234567890123456789.1")
        self.assertEqual(canonical_decimal("0." + big), "0." + big)

    def test_digit_bound_boundary(self):
        self.assertEqual(len(canonical_decimal("1e1023")), DIGIT_BOUND)
        with self.assertRaises(RoaxError) as ctx:
            canonical_decimal("1e1024")
        self.assertEqual(ctx.exception.code, ErrorCode.DIGIT_BOUND_EXCEEDED)

    def test_absurd_exponent_never_reaches_int(self):
        # CPython 3.11+ ships with a configurable int()/str() conversion limit whose
        # default is 4300 digits, so an unguarded int(exponent) would raise ValueError
        # rather than this specification's own bound.
        with self.assertRaises(RoaxError) as ctx:
            canonical_decimal("1e" + "9" * 5000)
        self.assertEqual(ctx.exception.code, ErrorCode.DIGIT_BOUND_EXCEEDED)

    def test_grammar_rejections(self):
        for text in ("01", "1.", "1.e2", ".5", "+1", "NaN", "Infinity", "0x10", "1.0 ", "1.0\n"):
            with self.subTest(text=text):
                with self.assertRaises(RoaxError) as ctx:
                    canonical_decimal(text)
                self.assertEqual(ctx.exception.code, ErrorCode.DECIMAL_GRAMMAR)


class TestInteger(unittest.TestCase):
    def test_negative_zero_normalizes(self):
        self.assertEqual(canonical_integer("-0"), "0")

    def test_beyond_double(self):
        self.assertEqual(canonical_integer("9223372036854775807"), "9223372036854775807")
        self.assertEqual(canonical_integer("-9223372036854775808"), "-9223372036854775808")

    def test_grammar_rejections(self):
        for text in ("01", "-01", "+1", "1.0", "1e2", "1\n"):
            with self.subTest(text=text):
                with self.assertRaises(RoaxError) as ctx:
                    canonical_integer(text)
                self.assertEqual(ctx.exception.code, ErrorCode.INTEGER_GRAMMAR)

    def test_digit_bound_applies_to_integer_too(self):
        # A reading rather than a quotation: section 6.2 states the bound under
        # *Canonical decimal* and its justification counts class 2's 40-digit integer
        # against it. `corpus/README.md` ambiguity 1 records that both reference
        # implementations read it this way and no vector discriminates.
        self.assertEqual(len(canonical_integer("1" * DIGIT_BOUND)), DIGIT_BOUND)
        with self.assertRaises(RoaxError) as ctx:
            canonical_integer("1" * (DIGIT_BOUND + 1))
        self.assertEqual(ctx.exception.code, ErrorCode.DIGIT_BOUND_EXCEEDED)


class TestPythonRegexTraps(unittest.TestCase):
    def test_dollar_anchor_would_accept_a_trailing_newline(self):
        # The divergence this repository already caught between its two reference
        # implementations. Demonstrated here so an edit that loosens the anchors fails.
        loose = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$")
        self.assertIsNotNone(loose.match("1.0\n"))
        self.assertIsNone(DECIMAL_INPUT_GRAMMAR.match("1.0\n"))
        self.assertIsNone(INTEGER_GRAMMAR.match("1\n"))

    def test_grammars_do_not_admit_non_ascii_digits(self):
        self.assertIsNotNone(re.match(r"\A\d+\Z", "١٢"))  # `\d` would
        self.assertIsNone(INTEGER_GRAMMAR.match("１２"))  # `[0-9]` does not
        with self.assertRaises(RoaxError):
            canonical_integer("１２")


class TestUnicode(unittest.TestCase):
    def test_the_pin_is_declared_and_the_runtime_is_reported(self):
        self.assertEqual(PINNED_UNICODE_VERSION, "15.1")
        self.assertTrue(runtime_unicode_version())
        # Not asserted equal: an interpreter built against another release is a legitimate
        # thing to run this on, and specification section 6.1 requires it to SAY so rather
        # than to fail. `unicode_tables_match_pin` is what a conformance report reads.
        self.assertIsInstance(unicode_tables_match_pin(), bool)

    def test_nfc_applied_to_values_and_keys(self):
        # Written with escapes rather than literals: the two forms render identically,
        # so a reader cannot tell a composed source line from a decomposed one and an
        # editor that normalizes files would silently make this test vacuous.
        composed, decomposed = "\u00e9", "e\u0301"
        self.assertNotEqual(composed, decomposed)
        self.assertEqual(encode_value(STRING, composed), encode_value(STRING, decomposed))
        self.assertEqual(encode_path((Key(composed),)), encode_path((Key(decomposed),)))
        self.assertEqual(encode_value(STRING, decomposed), b"\xc3\xa9")

    def test_kelvin_sign_normalizes_into_ascii(self):
        # U+212A is `e2 84 aa` as received and the single byte 0x4b once normalized.
        # It is the one ASCII letter reachable by NFC from a non-ASCII code point, which
        # is why specification section 11.2 justifies normalizing before the
        # reserved-namespace guard runs with it.
        self.assertEqual(nfc("\u212a"), "K")
        self.assertEqual(encode_value(STRING, "\u212a"), b"\x4b")
        self.assertEqual(encode_path((Key("\u212aelvin"),)), encode_path((Key("Kelvin"),)))

    def test_unpaired_surrogates_rejected_before_normalization(self):
        for bad in ("A\ud800B", "\udc00"):
            with self.subTest(bad=bad):
                with self.assertRaises(RoaxError) as ctx:
                    encode_value(STRING, bad)
                self.assertEqual(ctx.exception.code, ErrorCode.UNPAIRED_SURROGATE)
        with self.assertRaises(RoaxError) as ctx:
            encode_path((Key("\ud83d" + "A"),))
        self.assertEqual(ctx.exception.code, ErrorCode.UNPAIRED_SURROGATE)


class TestPath(unittest.TestCase):
    def test_nested_and_dotted_are_provably_distinct(self):
        nested = encode_path((Key("keyCollisionA"), Key("b")))
        dotted = encode_path((Key("keyCollisionB.c"),))
        self.assertNotEqual(nested, dotted)
        self.assertEqual(nested[:4], (2).to_bytes(4, "big"))
        self.assertEqual(dotted[:4], (1).to_bytes(4, "big"))

    def test_array_element_and_numeric_key_differ(self):
        self.assertNotEqual(encode_path((Index(0),)), encode_path((Key("0"),)))

    def test_empty_key_is_a_real_segment(self):
        self.assertEqual(encode_path((Key(""),)).hex(), "000000010100000000")
        self.assertNotEqual(encode_path((Key(""),)), encode_path(()))

    def test_no_reserved_characters(self):
        for key in ("a.b", "a[0]", "we.ird[key]"):
            with self.subTest(key=key):
                self.assertEqual(len(encode_path((Key(key),))), 4 + 1 + 4 + len(key.encode()))

    def test_index_must_fit_in_32_bits(self):
        self.assertEqual(encode_path((Index(2**32 - 1),)).hex(), "0000000102ffffffff")
        for bad in (2**32, 2**32 + 4):
            with self.subTest(bad=bad):
                with self.assertRaises(RoaxError) as ctx:
                    encode_path((Index(bad),))
                self.assertEqual(ctx.exception.code, ErrorCode.INDEX_OUT_OF_32_BIT_RANGE)

    def test_display_path_is_display_only(self):
        segs = (Key("a"), Index(3), Key("b"), Index(0))
        self.assertEqual(display_path(segs), "a[3].b[0]")
        # There is no parser for this form anywhere in the package, which is what makes
        # the specification section 5.2 trap unreachable rather than merely discouraged.
        import roax_canon.path as path_module

        self.assertFalse(
            [n for n in dir(path_module) if "parse" in n.lower()],
            "a display-path parser would reopen the section 5.2 trap",
        )

    def test_sort_order_is_not_alphabetical(self):
        # Section 5.3: the length prefix precedes the key bytes, so `zz` sorts before `aaa`.
        self.assertLess(encode_path((Key("zz"),)), encode_path((Key("aaa"),)))


class TestValueEncoding(unittest.TestCase):
    def test_valueless_tags(self):
        for tag in (0, 6, 7):
            self.assertEqual(encode_value(tag), b"")
        with self.assertRaises(RoaxError):
            encode_value(NULL, "something")

    def test_bool(self):
        self.assertEqual(encode_value(1, True), b"\x01")
        self.assertEqual(encode_value(1, False), b"\x00")

    def test_numbers_must_be_carried_as_strings(self):
        for tag in (INTEGER, DECIMAL):
            with self.subTest(tag=tag):
                with self.assertRaises(RoaxError):
                    encode_value(tag, 5)

    def test_bytes_tag_takes_bytes(self):
        self.assertEqual(encode_value(BYTES, b"\x00\xff"), b"\x00\xff")

    def test_blob_ref_layout(self):
        digest = bytes(range(32))
        encoded = encode_value(8, BlobRef("14314", digest))
        self.assertEqual(encoded[:8], (14314).to_bytes(8, "big"))
        self.assertEqual(encoded[8:12], (32).to_bytes(4, "big"))
        self.assertEqual(encoded[12:], digest)
        self.assertEqual(len(encoded), 44)


class TestBase64(unittest.TestCase):
    def test_canonical_form_accepted(self):
        self.assertEqual(decode_base64_canonical("aGVsbG8="), b"hello")
        self.assertEqual(decode_base64_canonical(""), b"")

    def test_rejections_named_by_section_6_3(self):
        for bad in (
            "aGVsbG8",  # absent padding
            "aGVsbG8==",  # excess padding
            "aGVsb_8=",  # RFC 4648 section 5 URL-safe alphabet
            "aGVs\nbG8=",  # line wrapping
            "aGVsbG9=",  # non-zero unused bits in the final quantum (RFC 4648 s3.5)
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(RoaxError) as ctx:
                    decode_base64_canonical(bad)
                self.assertEqual(ctx.exception.code, ErrorCode.BASE64_NOT_CANONICAL)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(not unittest.main(exit=False).result.wasSuccessful())
