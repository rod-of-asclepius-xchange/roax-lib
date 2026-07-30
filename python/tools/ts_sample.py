"""Read one named export out of a TypeScript sample-data module.

Class 10 of the conformance corpus names its records by module and export in a checkout
that lives outside this repository by design, for example
``references/schemata/src/sg/gov/moh/recovery-healthcert/2.0/sample-data.ts#sampleDocument``
at upstream commit ``09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa``.
No reference schema or sample is ever copied in, not even a fragment, so a runner has to
read one in place.

This is a deliberately small object-literal reader, not a JavaScript engine.
It accepts the subset those sample modules are written in: object and array literals,
double-quoted and single-quoted strings, unquoted identifier keys, JSON-shaped decimal
numeric literals, ``true``, ``false``, ``null``, trailing commas, and line and block
comments.
Anything else is an error rather than a guess, because a sample this cannot read is a
sample whose record it must not pretend to have extracted.
The named export must be a live top-level declaration.
Text inside comments, strings, template literals, or nested blocks is never treated as one.

**Numeric literals are carried verbatim as :class:`~roax_canon.jsonio.JsonNumber`.**
If a sample contains one, this reader never routes it through :class:`float`, which would
destroy the literal before the implementation under test saw it and violate specification
section 6.4.
"""

from __future__ import annotations

import re
from typing import Any

from roax_canon.jsonio import JsonNumber

__all__ = ["load_export", "parse_object_literal"]

_WS = re.compile(r"(?:\s+|//[^\n]*|/\*.*?\*/)*", re.DOTALL)
_IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_IDENT_CONTINUATION = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_$")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_ESCAPES = {
    '"': '"',
    "'": "'",
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def _skip_quoted(text: str, pos: int, quote: str) -> int:
    """Return the position after a JavaScript string, or EOF if it is unterminated."""
    pos += 1
    while pos < len(text):
        ch = text[pos]
        if ch == "\\":
            pos += 2
        elif ch == quote:
            return pos + 1
        else:
            pos += 1
    return len(text)


def _skip_line_comment(text: str, pos: int) -> int:
    pos += 2
    while pos < len(text) and text[pos] not in "\r\n\u2028\u2029":
        pos += 1
    if pos < len(text) and text.startswith("\r\n", pos):
        return pos + 2
    return min(pos + 1, len(text))


def _skip_block_comment(text: str, pos: int) -> int:
    end = text.find("*/", pos + 2)
    return len(text) if end < 0 else end + 2


def _skip_template_expression(text: str, pos: int) -> int:
    """Skip from just after ``${`` through its matching ``}``."""
    depth = 1
    while pos < len(text):
        if text.startswith("//", pos):
            pos = _skip_line_comment(text, pos)
        elif text.startswith("/*", pos):
            pos = _skip_block_comment(text, pos)
        elif text[pos] in "\"'":
            pos = _skip_quoted(text, pos, text[pos])
        elif text[pos] == "`":
            pos = _skip_template(text, pos)
        elif text[pos] == "{":
            depth += 1
            pos += 1
        elif text[pos] == "}":
            depth -= 1
            pos += 1
            if depth == 0:
                return pos
        else:
            pos += 1
    return len(text)


def _skip_template(text: str, pos: int) -> int:
    """Return the position after a template literal, including interpolations."""
    pos += 1
    while pos < len(text):
        if text[pos] == "\\":
            pos += 2
        elif text[pos] == "`":
            return pos + 1
        elif text.startswith("${", pos):
            pos = _skip_template_expression(text, pos + 2)
        else:
            pos += 1
    return len(text)


def _top_level_tokens(text: str) -> list[tuple[str, str, int, int]]:
    """Tokenize enough TypeScript to locate live top-level export declarations."""
    tokens: list[tuple[str, str, int, int]] = []
    delimiters: list[str] = []
    closing = {"(": ")", "[": "]", "{": "}"}
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
        elif text.startswith("//", pos):
            pos = _skip_line_comment(text, pos)
        elif text.startswith("/*", pos):
            pos = _skip_block_comment(text, pos)
        elif text[pos] in "\"'":
            pos = _skip_quoted(text, pos, text[pos])
        elif text[pos] == "`":
            pos = _skip_template(text, pos)
        else:
            match = _IDENT.match(text, pos)
            if match is not None:
                if not delimiters:
                    tokens.append(("identifier", match.group(0), pos, match.end()))
                pos = match.end()
                continue

            ch = text[pos]
            if ch in closing:
                if not delimiters:
                    tokens.append(("punctuation", ch, pos, pos + 1))
                delimiters.append(closing[ch])
            elif ch in ")]}":
                if delimiters and delimiters[-1] == ch:
                    delimiters.pop()
                if not delimiters:
                    tokens.append(("punctuation", ch, pos, pos + 1))
            elif not delimiters:
                tokens.append(("punctuation", ch, pos, pos + 1))
            pos += 1
    return tokens


def _skip_trivia(text: str, pos: int) -> int:
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
        elif text.startswith("//", pos):
            pos = _skip_line_comment(text, pos)
        elif text.startswith("/*", pos):
            pos = _skip_block_comment(text, pos)
        else:
            break
    return pos


def _export_value_start(text: str, pos: int) -> int | None:
    """Locate ``=`` after a declaration name and its optional type annotation."""
    pos = _skip_trivia(text, pos)
    if pos < len(text) and text[pos] == "=":
        return _skip_trivia(text, pos + 1)
    if pos >= len(text) or text[pos] != ":":
        return None

    pos += 1
    delimiters: list[str] = []
    closing = {"(": ")", "[": "]", "{": "}", "<": ">"}
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
        elif text.startswith("//", pos):
            pos = _skip_line_comment(text, pos)
        elif text.startswith("/*", pos):
            pos = _skip_block_comment(text, pos)
        elif text[pos] in "\"'":
            pos = _skip_quoted(text, pos, text[pos])
        elif text[pos] == "`":
            pos = _skip_template(text, pos)
        else:
            ch = text[pos]
            if ch in closing:
                delimiters.append(closing[ch])
            elif ch in ")]}>":
                if delimiters and delimiters[-1] == ch:
                    delimiters.pop()
            elif ch == "=" and not delimiters:
                if pos + 1 < len(text) and text[pos + 1] == ">":
                    pos += 2
                    continue
                return _skip_trivia(text, pos + 1)
            elif ch == ";" and not delimiters:
                return None
            pos += 1
    return None


class _Reader:
    def __init__(self, text: str, pos: int = 0) -> None:
        self.text = text
        self.pos = pos

    def skip(self) -> None:
        self.pos = _WS.match(self.text, self.pos).end()

    def expect(self, ch: str) -> None:
        self.skip()
        if self.pos >= len(self.text) or self.text[self.pos] != ch:
            raise ValueError(f"expected {ch!r} at offset {self.pos}")
        self.pos += 1

    def peek(self) -> str:
        self.skip()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def value(self) -> Any:
        ch = self.peek()
        if ch == "{":
            return self.obj()
        if ch == "[":
            return self.arr()
        if ch in "\"'":
            return self.string()
        if ch == "t" and self.text.startswith("true", self.pos):
            self.pos += 4
            self.scalar_boundary("true")
            return True
        if ch == "f" and self.text.startswith("false", self.pos):
            self.pos += 5
            self.scalar_boundary("false")
            return False
        if ch == "n" and self.text.startswith("null", self.pos):
            self.pos += 4
            self.scalar_boundary("null")
            return None
        m = _NUMBER.match(self.text, self.pos)
        if m is not None:
            self.pos = m.end()
            self.scalar_boundary("number")
            return JsonNumber(m.group(0))
        raise ValueError(
            f"unsupported literal at offset {self.pos}: {self.text[self.pos:self.pos + 30]!r}"
        )

    def scalar_boundary(self, kind: str) -> None:
        """Reject a valid scalar token that is only a prefix of another token."""
        if self.pos >= len(self.text):
            return
        following = self.text[self.pos]
        if following in _IDENT_CONTINUATION or following == ".":
            raise ValueError(f"invalid {kind} token boundary at offset {self.pos}")

    def string(self) -> str:
        quote = self.text[self.pos]
        self.pos += 1
        out: list[str] = []
        while True:
            if self.pos >= len(self.text):
                raise ValueError("unterminated string")
            ch = self.text[self.pos]
            if ch == quote:
                self.pos += 1
                return "".join(out)
            if ch in "\r\n\u2028\u2029" or ord(ch) < 0x20:
                raise ValueError(f"unescaped control or line terminator at offset {self.pos}")
            if ch == "\\":
                if self.pos + 1 >= len(self.text):
                    raise ValueError("unterminated string escape")
                nxt = self.text[self.pos + 1]
                if nxt == "u":
                    if self.pos + 6 > len(self.text):
                        raise ValueError("incomplete Unicode escape")
                    digits = self.text[self.pos + 2 : self.pos + 6]
                    if any(ch not in "0123456789abcdefABCDEF" for ch in digits):
                        raise ValueError(f"invalid Unicode escape at offset {self.pos}")
                    code_unit = int(digits, 16)
                    self.pos += 6
                    if (
                        0xD800 <= code_unit <= 0xDBFF
                        and self.pos + 6 <= len(self.text)
                        and self.text.startswith("\\u", self.pos)
                    ):
                        low_digits = self.text[self.pos + 2 : self.pos + 6]
                        if all(ch in "0123456789abcdefABCDEF" for ch in low_digits):
                            low = int(low_digits, 16)
                            if 0xDC00 <= low <= 0xDFFF:
                                scalar = 0x10000 + ((code_unit - 0xD800) << 10) + low - 0xDC00
                                out.append(chr(scalar))
                                self.pos += 6
                                continue
                    # JavaScript strings may contain an unpaired UTF-16 surrogate.
                    # Preserve it here so the ROAX text boundary can reject it under
                    # specification section 6.1 rather than silently changing the value.
                    out.append(chr(code_unit))
                    continue
                if nxt not in _ESCAPES:
                    raise ValueError(f"unsupported escape \\{nxt} at offset {self.pos}")
                out.append(_ESCAPES[nxt])
                self.pos += 2
                continue
            out.append(ch)
            self.pos += 1

    def obj(self) -> dict:
        self.expect("{")
        out: dict[str, Any] = {}
        while True:
            if self.peek() == "}":
                self.pos += 1
                return out
            ch = self.peek()
            if ch in "\"'":
                key = self.string()
            else:
                m = _IDENT.match(self.text, self.pos)
                if m is None:
                    raise ValueError(f"expected a member name at offset {self.pos}")
                key, self.pos = m.group(0), m.end()
            if key in out:
                # Specification section 3.2: duplicate member names are rejected, never
                # resolved. The same rule the JSON reader applies, applied here so the
                # extractor cannot smuggle one past it.
                raise ValueError(f"duplicate member name {key!r}")
            self.expect(":")
            out[key] = self.value()
            separator = self.peek()
            if separator == ",":
                self.pos += 1
            elif separator != "}":
                raise ValueError(f"expected ',' or '}}' at offset {self.pos}")

    def arr(self) -> list:
        self.expect("[")
        out: list[Any] = []
        while True:
            if self.peek() == "]":
                self.pos += 1
                return out
            out.append(self.value())
            separator = self.peek()
            if separator == ",":
                self.pos += 1
            elif separator != "]":
                raise ValueError(f"expected ',' or ']' at offset {self.pos}")


def parse_object_literal(text: str, pos: int = 0) -> Any:
    """Parse one literal starting at ``pos``."""
    reader = _Reader(text, pos)
    value = reader.value()
    reader.skip()
    if reader.pos != len(text):
        raise ValueError(f"unexpected text after literal at offset {reader.pos}")
    return value


def load_export(path: str, export_name: str) -> Any:
    """Read ``export const <export_name> = <literal>`` out of a module."""
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    start = None
    tokens = _top_level_tokens(text)
    for index in range(len(tokens) - 2):
        export, const, name = tokens[index : index + 3]
        if (
            export[:2] == ("identifier", "export")
            and const[:2] == ("identifier", "const")
            and name[:2] == ("identifier", export_name)
        ):
            start = _export_value_start(text, name[3])
            if start is not None:
                break
    if start is None:
        raise ValueError(
            f"{path} has no export named {export_name!r} as a live top-level declaration"
        )
    reader = _Reader(text, start)
    value = reader.value()
    reader.skip()
    if reader.pos < len(text) and reader.text[reader.pos] != ";":
        raise ValueError(f"expected ';' after export {export_name!r} at offset {reader.pos}")
    return value
