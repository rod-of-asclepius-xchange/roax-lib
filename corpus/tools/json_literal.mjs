// Literal-preserving JSON scanner for implementation B.
//
// Specification section 6.4 blesses the ES2025 `JSON.parse` source-text reviver for JavaScript,
// and it does preserve numeric literals. It does NOT preserve duplicate object keys, which
// section 3.2 requires an implementation to REJECT rather than silently drop, and it does not
// preserve key order for integer-like keys. So this is a hand-written scanner instead - the
// same shape of thing section 6.4 says a Swift implementation has no choice but to write.
//
// Using a different mechanism from implementation A is the point: two readings of the same
// bytes through two unrelated parsers is most of what the cross-check is worth.

import { NumberLiteral, RecordMap, RoaxError } from "./roax_ref.mjs";

const NUMBER = /^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?/;

class Scanner {
  constructor(text) {
    this.s = text;
    this.i = 0;
  }

  error(what) {
    return new RoaxError("json-syntax", `${what} at offset ${this.i}`);
  }

  ws() {
    while (this.i < this.s.length && " \t\n\r".includes(this.s[this.i])) this.i++;
  }

  expect(ch) {
    if (this.s[this.i] !== ch) throw this.error(`expected ${ch}`);
    this.i++;
  }

  value() {
    this.ws();
    const c = this.s[this.i];
    if (c === undefined) throw this.error("unexpected end of input");
    if (c === "{") return this.object();
    if (c === "[") return this.array();
    if (c === '"') return this.string();
    if (this.s.startsWith("true", this.i)) { this.i += 4; return true; }
    if (this.s.startsWith("false", this.i)) { this.i += 5; return false; }
    if (this.s.startsWith("null", this.i)) { this.i += 4; return null; }
    // Section 3.2: NaN, Infinity and -Infinity are not JSON and MUST be rejected. Naming them
    // explicitly gives the corpus a stable reason code instead of a generic syntax error.
    for (const bad of ["NaN", "Infinity", "-Infinity"]) {
      if (this.s.startsWith(bad, this.i)) throw new RoaxError("non-finite-number", bad);
    }
    return this.number();
  }

  object() {
    this.expect("{");
    const entries = [];
    this.ws();
    if (this.s[this.i] === "}") { this.i++; return new RecordMap(entries); }
    for (;;) {
      this.ws();
      const key = this.string();
      this.ws();
      this.expect(":");
      entries.push([key, this.value()]);
      this.ws();
      if (this.s[this.i] === ",") { this.i++; continue; }
      this.expect("}");
      return new RecordMap(entries);
    }
  }

  array() {
    this.expect("[");
    const out = [];
    this.ws();
    if (this.s[this.i] === "]") { this.i++; return out; }
    for (;;) {
      out.push(this.value());
      this.ws();
      if (this.s[this.i] === ",") { this.i++; continue; }
      this.expect("]");
      return out;
    }
  }

  string() {
    this.expect('"');
    let out = "";
    for (;;) {
      const c = this.s[this.i];
      if (c === undefined) throw this.error("unterminated string");
      if (c === '"') { this.i++; return out; }
      if (c === "\\") {
        this.i++;
        const e = this.s[this.i++];
        if (e === "u") {
          const hex = this.s.slice(this.i, this.i + 4);
          if (!/^[0-9a-fA-F]{4}$/.test(hex)) throw this.error("bad \\u escape");
          this.i += 4;
          // Emitted as a raw code unit, INCLUDING a lone surrogate. Rejecting it here would
          // hide the section 3.2 rejection inside the parser; roax_ref rejects it at the
          // hashing boundary, which is where the specification puts it.
          out += String.fromCharCode(parseInt(hex, 16));
          continue;
        }
        const simple = { '"': '"', "\\": "\\", "/": "/", b: "\b", f: "\f", n: "\n", r: "\r", t: "\t" };
        if (!(e in simple)) throw this.error("bad escape");
        out += simple[e];
        continue;
      }
      if (c.charCodeAt(0) < 0x20) throw this.error("raw control character in string");
      out += c;
      this.i++;
    }
  }

  number() {
    const m = NUMBER.exec(this.s.slice(this.i));
    if (!m) throw this.error("bad number");
    this.i += m[0].length;
    // The verbatim source text. No Number(), no parseFloat, nothing numeric at all.
    return new NumberLiteral(m[0]);
  }
}

export function parse(text) {
  const sc = new Scanner(text);
  const v = sc.value();
  sc.ws();
  if (sc.i !== sc.s.length) throw sc.error("trailing content");
  return v;
}
