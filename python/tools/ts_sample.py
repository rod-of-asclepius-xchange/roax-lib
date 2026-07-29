"""Read one named export out of a TypeScript sample-data module.

Class 10 of the conformance corpus names its records by module and export in a checkout
that lives outside this repository by design, for example
``references/schemata/src/sg/gov/moh/recovery-healthcert/2.0/sample-data.ts#sampleDocument``.
No reference schema or sample is ever copied in, not even a fragment, so a runner has to
read one in place.

This is a deliberately small object-literal reader, not a JavaScript engine.
It accepts the subset those sample modules are written in: object and array literals,
double-quoted and single-quoted strings, unquoted identifier keys, numeric literals,
``true``, ``false``, ``null``, trailing commas, and line and block comments.
Anything else is an error rather than a guess, because a sample this cannot read is a
sample whose record it must not pretend to have extracted.

**Numeric literals are carried verbatim as :class:`~roax_canon.jsonio.JsonNumber`.**
The recovery sample happens to contain none, and that is checked rather than assumed: an
extractor that quietly routed one through :class:`float` would destroy the literal before
the implementation under test ever saw it, which is the failure specification section 6.4
exists to prevent.
"""

from __future__ import annotations

import re
from typing import Any

from roax_canon.jsonio import JsonNumber

__all__ = ["load_export", "parse_object_literal"]

_WS = re.compile(r"(?:\s+|//[^\n]*|/\*.*?\*/)*", re.DOTALL)
_IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_ESCAPES = {'"': '"', "'": "'", "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


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
            return True
        if ch == "f" and self.text.startswith("false", self.pos):
            self.pos += 5
            return False
        if ch == "n" and self.text.startswith("null", self.pos):
            self.pos += 4
            return None
        m = _NUMBER.match(self.text, self.pos)
        if m is not None:
            self.pos = m.end()
            return JsonNumber(m.group(0))
        raise ValueError(f"unsupported literal at offset {self.pos}: {self.text[self.pos:self.pos + 30]!r}")

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
            if ch == "\\":
                nxt = self.text[self.pos + 1]
                if nxt == "u":
                    out.append(chr(int(self.text[self.pos + 2 : self.pos + 6], 16)))
                    self.pos += 6
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
            if self.peek() == ",":
                self.pos += 1

    def arr(self) -> list:
        self.expect("[")
        out: list[Any] = []
        while True:
            if self.peek() == "]":
                self.pos += 1
                return out
            out.append(self.value())
            if self.peek() == ",":
                self.pos += 1


def parse_object_literal(text: str, pos: int = 0) -> Any:
    """Parse one literal starting at ``pos``."""
    return _Reader(text, pos).value()


def load_export(path: str, export_name: str) -> Any:
    """Read ``export const <export_name> = <literal>`` out of a module."""
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    m = re.search(
        r"export\s+const\s+" + re.escape(export_name) + r"\s*(?::[^=]*)?=\s*",
        text,
    )
    if m is None:
        raise ValueError(f"{path} has no export named {export_name!r}")
    return parse_object_literal(text, m.end())
