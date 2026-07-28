#!/usr/bin/env python3
"""Extract one exported record from a reference `sample-data.ts` as JSON text.

The three Singapore MOH sample records are shipped as TypeScript object literals in a
third-party checkout that this repository deliberately does not vendor. Class 10 references
them by file, so a runner needs a way to turn `export const sampleDocument = { ... }` into JSON
text before any implementation reads it.

Two things this deliberately does NOT do.

It does not evaluate the file. Handing the literal to a JavaScript engine would route every
number through a double, which is precisely the hazard specification section 6.4 exists to
name, and a corpus tool that does the forbidden thing "because these particular samples happen
to be safe" teaches the wrong lesson to anyone reading it. The tokenizer below copies numeric
literals across as their verbatim source text and never constructs a number at all.

It does not write into this repository. The output goes wherever the caller asks, and
`corpus/README.md` tells a runner to put it in a scratch directory. Committing the extracted
record would republish a third-party sample by another route.

Usage:
    python3 extract_reference_record.py --references DIR --module PATH --export NAME --out FILE
"""

from __future__ import annotations

import argparse
import json
import os
import sys

IDENT_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_$")
IDENT_REST = IDENT_START | set("0123456789")
NUMBER_START = set("0123456789-")


class ExtractError(Exception):
    pass


class Reader:
    """A tokenizer for the restricted JavaScript object-literal subset these files use."""

    def __init__(self, text: str):
        self.s = text
        self.i = 0

    def error(self, what: str) -> ExtractError:
        line = self.s.count("\n", 0, self.i) + 1
        return ExtractError(f"{what} at line {line}")

    def skip(self):
        """Whitespace and comments. Comments only exist outside strings by construction."""
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif self.s.startswith("//", self.i):
                nl = self.s.find("\n", self.i)
                self.i = len(self.s) if nl < 0 else nl + 1
            elif self.s.startswith("/*", self.i):
                end = self.s.find("*/", self.i + 2)
                if end < 0:
                    raise self.error("unterminated block comment")
                self.i = end + 2
            else:
                return

    def value(self):
        self.skip()
        if self.i >= len(self.s):
            raise self.error("unexpected end of input")
        c = self.s[self.i]
        if c == "{":
            return self.obj()
        if c == "[":
            return self.arr()
        if c in "\"'":
            return json.dumps(self.string(), ensure_ascii=False)
        if c in NUMBER_START:
            return self.number()
        word = self.ident()
        if word in ("true", "false", "null"):
            return word
        raise self.error(f"unsupported value {word!r}")

    def obj(self):
        self.i += 1
        parts = []
        while True:
            self.skip()
            if self.i >= len(self.s):
                raise self.error("unterminated object")
            if self.s[self.i] == "}":
                self.i += 1
                return "{" + ",".join(parts) + "}"
            if self.s[self.i] in "\"'":
                key = self.string()
            else:
                key = self.ident()
            self.skip()
            if self.s[self.i] != ":":
                raise self.error("expected ':'")
            self.i += 1
            parts.append(json.dumps(key, ensure_ascii=False) + ":" + self.value())
            self.skip()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1

    def arr(self):
        self.i += 1
        parts = []
        while True:
            self.skip()
            if self.i >= len(self.s):
                raise self.error("unterminated array")
            if self.s[self.i] == "]":
                self.i += 1
                return "[" + ",".join(parts) + "]"
            parts.append(self.value())
            self.skip()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1

    def string(self) -> str:
        quote = self.s[self.i]
        self.i += 1
        out = []
        while True:
            if self.i >= len(self.s):
                raise self.error("unterminated string")
            c = self.s[self.i]
            if c == quote:
                self.i += 1
                return "".join(out)
            if c == "\\":
                self.i += 1
                e = self.s[self.i]
                self.i += 1
                if e == "u":
                    out.append(chr(int(self.s[self.i:self.i + 4], 16)))
                    self.i += 4
                elif e == "x":
                    out.append(chr(int(self.s[self.i:self.i + 2], 16)))
                    self.i += 2
                else:
                    out.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f",
                                "0": "\0"}.get(e, e))
                continue
            out.append(c)
            self.i += 1

    def ident(self) -> str:
        start = self.i
        if self.i >= len(self.s) or self.s[self.i] not in IDENT_START:
            raise self.error("expected identifier")
        while self.i < len(self.s) and self.s[self.i] in IDENT_REST:
            self.i += 1
        return self.s[start:self.i]

    def number(self) -> str:
        """Copied across verbatim. No float, no int, no Number() - just the source bytes."""
        start = self.i
        if self.s[self.i] == "-":
            self.i += 1
        while self.i < len(self.s) and self.s[self.i] in "0123456789":
            self.i += 1
        if self.i < len(self.s) and self.s[self.i] == ".":
            self.i += 1
            while self.i < len(self.s) and self.s[self.i] in "0123456789":
                self.i += 1
        if self.i < len(self.s) and self.s[self.i] in "eE":
            self.i += 1
            if self.i < len(self.s) and self.s[self.i] in "+-":
                self.i += 1
            while self.i < len(self.s) and self.s[self.i] in "0123456789":
                self.i += 1
        literal = self.s[start:self.i]
        if literal in ("", "-"):
            raise self.error("bad number")
        return literal


def extract(module_text: str, export_name: str) -> str:
    marker = f"export const {export_name}"
    at = module_text.find(marker)
    if at < 0:
        raise ExtractError(f"export {export_name!r} not found")
    eq = module_text.index("=", at + len(marker))
    reader = Reader(module_text)
    reader.i = eq + 1
    return reader.value()


def numeric_literals(json_text: str):
    """Every numeric literal in the extracted text, for the report.

    Section 6.4's whole point is that these are the values a float-based parser destroys, so a
    runner should be able to see at a glance which ones a given sample actually contains.
    """
    import re
    return re.findall(r"(?<![\"\w.])(-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)(?=[,}\]])",
                      json_text)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--module", required=True, help="path to the sample-data.ts file")
    ap.add_argument("--export", required=True, dest="export_name")
    ap.add_argument("--out", required=True)
    ap.add_argument("--list-numbers", action="store_true")
    args = ap.parse_args()

    with open(args.module, "r", encoding="utf-8") as handle:
        text = handle.read()
    try:
        out = extract(text, args.export_name)
    except ExtractError as exc:
        print(f"extraction failed: {exc}", file=sys.stderr)
        raise SystemExit(2)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(out)
    print(f"wrote {args.out} ({len(out)} bytes)")
    if args.list_numbers:
        print("numeric literals:", sorted(set(numeric_literals(out))))


if __name__ == "__main__":
    main()
