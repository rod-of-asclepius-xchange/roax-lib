"""The TypeScript sample-data extractor `python/tools/ts_sample.py`.

It is the only module in this deliverable that no corpus vector reaches unless the
third-party reference checkout is present, because its single consumer is the class-10
record path in `python/tools/run_corpus.py`.
That checkout is gitignored and is never committed, so a run without it exercises none of
this file.

These cases need no external artifact.
They pin three properties an extractor can break silently: a numeric literal must arrive
verbatim rather than through a float (specification section 6.4), a duplicate member name
must be rejected rather than resolved (specification section 3.2), and an export locator
must not treat inert source text as a declaration.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from roax_canon import JsonNumber, json_kind  # noqa: E402
from ts_sample import load_export, parse_object_literal  # noqa: E402


class NumericLiterals(unittest.TestCase):
    """A number reaches the implementation under test as the bytes the module carries."""

    def test_a_decimal_keeps_its_trailing_zero(self):
        parsed = parse_object_literal('{"dose": 0.010}')
        self.assertIsInstance(parsed["dose"], JsonNumber)
        self.assertEqual(str(parsed["dose"]), "0.010")

    def test_an_overflowing_literal_does_not_become_inf(self):
        parsed = parse_object_literal("{value: 1e999}")
        self.assertEqual(str(parsed["value"]), "1e999")
        self.assertNotIsInstance(parsed["value"], float)

    def test_an_integer_beyond_double_precision_is_exact(self):
        parsed = parse_object_literal("{value: 9007199254740993}")
        self.assertEqual(str(parsed["value"]), "9007199254740993")

    def test_a_number_and_a_string_do_not_collapse(self):
        parsed = parse_object_literal('{n: 5, s: "5"}')
        self.assertEqual(json_kind(parsed["n"]), "number")
        self.assertEqual(json_kind(parsed["s"]), "string")


class Rejections(unittest.TestCase):
    """Anything this reader cannot read is an error, never a guess."""

    def test_duplicate_member_name_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            parse_object_literal('{"a": 1, "a": 2}')
        self.assertIn("duplicate member name", str(caught.exception))

    def test_a_nested_duplicate_is_rejected_too(self):
        with self.assertRaises(ValueError):
            parse_object_literal('{outer: {"a": 1, a: 2}}')

    def test_an_unsupported_literal_is_an_error(self):
        with self.assertRaises(ValueError) as caught:
            parse_object_literal("{value: someIdentifier}")
        self.assertIn("unsupported literal", str(caught.exception))

    def test_an_unterminated_string_is_an_error(self):
        with self.assertRaises(ValueError):
            parse_object_literal('{value: "open')

    def test_a_raw_line_break_in_a_string_is_an_error(self):
        with self.assertRaises(ValueError):
            parse_object_literal('{value: "two\nlines"}')

    def test_an_unescaped_control_character_is_an_error(self):
        with self.assertRaises(ValueError):
            parse_object_literal('{value: "before\x01after"}')

    def test_an_unsupported_escape_is_an_error(self):
        with self.assertRaises(ValueError) as caught:
            parse_object_literal(r'{value: "\x41"}')
        self.assertIn("unsupported escape", str(caught.exception))

    def test_object_members_require_a_comma(self):
        with self.assertRaises(ValueError) as caught:
            parse_object_literal("{a: 1 b: 2}")
        self.assertIn("expected ',' or '}'", str(caught.exception))

    def test_array_items_require_a_comma(self):
        with self.assertRaises(ValueError) as caught:
            parse_object_literal("[1 2]")
        self.assertIn("expected ',' or ']'", str(caught.exception))

    def test_keywords_cannot_be_token_prefixes(self):
        for text in ("truex", "falseValue", "nullish"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_object_literal(text)

    def test_incomplete_exponent_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_object_literal("1e")

    def test_trailing_text_after_a_literal_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            parse_object_literal("{a: 1}; another")
        self.assertIn("unexpected text after literal", str(caught.exception))


class TheAcceptedSubset(unittest.TestCase):
    """The shapes the sample modules are actually written in."""

    def test_comments_trailing_commas_and_both_quote_styles(self):
        text = """{
            // a line comment
            quoted: "double",
            'single': 'quoted',   /* a block
                                     comment */
            nested: {list: [1, true, false, null,],},
        }"""
        self.assertEqual(
            parse_object_literal(text),
            {
                "quoted": "double",
                "single": "quoted",
                "nested": {"list": [JsonNumber("1"), True, False, None]},
            },
        )

    def test_a_unicode_escape_is_decoded(self):
        self.assertEqual(parse_object_literal(r'{value: "caf\u00e9"}')["value"], "café")

    def test_a_utf16_surrogate_pair_escape_is_one_scalar(self):
        self.assertEqual(parse_object_literal(r'{value: "\uD83D\uDE00"}')["value"], "😀")


class LoadExport(unittest.TestCase):
    """Reading one named export out of a module on disk."""

    def _module(self, body: str) -> str:
        handle = tempfile.NamedTemporaryFile("w", suffix=".ts", encoding="utf-8", delete=False)
        handle.write(body)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_reads_the_named_export_past_a_type_annotation(self):
        path = self._module(
            "import {Thing} from './thing';\n"
            "export const other = {no: 'not this one'};\n"
            "export const sampleDocument: Thing = {id: 'urn:uuid:1', dose: 0.50};\n"
        )
        parsed = load_export(path, "sampleDocument")
        self.assertEqual(parsed["id"], "urn:uuid:1")
        self.assertEqual(str(parsed["dose"]), "0.50")

    def test_an_absent_export_is_an_error_rather_than_an_empty_record(self):
        path = self._module("export const sampleDocument = {a: 1};\n")
        with self.assertRaises(ValueError) as caught:
            load_export(path, "notThere")
        self.assertIn("no export named", str(caught.exception))

    def test_a_name_that_only_prefixes_an_export_does_not_match_it(self):
        path = self._module("export const sampleDocumentV2 = {a: 1};\n")
        with self.assertRaises(ValueError):
            load_export(path, "sampleDocument")
        self.assertEqual(str(load_export(path, "sampleDocumentV2")["a"]), "1")

    def test_an_export_spelling_in_a_line_comment_is_not_live(self):
        path = self._module(
            "// export const sampleDocument = {from: 'comment'};\n"
            "export const other = {a: 1};\n"
        )
        with self.assertRaises(ValueError):
            load_export(path, "sampleDocument")

    def test_an_export_spelling_in_a_block_comment_is_not_live(self):
        path = self._module(
            "/* before\n"
            "export const sampleDocument = {from: 'comment'};\n"
            "*/\n"
            "export const other = {a: 1};\n"
        )
        with self.assertRaises(ValueError):
            load_export(path, "sampleDocument")

    def test_an_export_spelling_in_a_string_is_not_live(self):
        for quoted in (
            '"export const sampleDocument = {from: \\"string\\"};"',
            "'export const sampleDocument = {from: \\'string\\'};'",
        ):
            with self.subTest(quoted=quoted):
                path = self._module(f"const description = {quoted};\n")
                with self.assertRaises(ValueError):
                    load_export(path, "sampleDocument")

    def test_an_export_spelling_in_a_template_literal_is_not_live(self):
        path = self._module(
            "const description = `export const sampleDocument = {from: 'template'}; "
            "${`nested ${'value'}`}`;\n"
        )
        with self.assertRaises(ValueError):
            load_export(path, "sampleDocument")

    def test_a_nested_namespace_export_is_not_a_module_export(self):
        path = self._module(
            "namespace Nested {\n"
            "  export const sampleDocument = {from: 'namespace'};\n"
            "}\n"
        )
        with self.assertRaises(ValueError):
            load_export(path, "sampleDocument")

    def test_a_live_export_after_inert_spellings_is_read(self):
        path = self._module(
            "const description = 'export const sampleDocument = {wrong: true};';\n"
            "/* export const sampleDocument = {wrong: true}; */\n"
            "const template = `export const sampleDocument = {wrong: true};`;\n"
            "export const sampleDocument = {right: true};\n"
        )
        self.assertEqual(load_export(path, "sampleDocument"), {"right": True})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
