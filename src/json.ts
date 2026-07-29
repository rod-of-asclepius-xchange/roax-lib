/**
 * A literal-preserving JSON reader.
 *
 * `JSON.parse` cannot be used for any value this library commits to, for two independent reasons
 * and each alone is disqualifying.
 *
 * 1. **It destroys numeric literals.** Every JSON number goes through an IEEE-754 double, so
 *    `0.010` becomes `0.01` and `9223372036854775807` becomes `9223372036854776000`.
 *    Specification section 6.4 states normatively that implementations MUST NOT parse record
 *    numbers through any floating-point type, and section 6.2 makes the trailing zero significant
 *    because FHIR R4 says SHALL. `docs/conformance-corpus.md` section 5 reproduces the collisions
 *    on Node v22.21.0.
 * 2. **It discards duplicate keys.** Specification section 3.2 requires duplicate map keys to be
 *    rejected at the input boundary, and `JSON.parse` silently keeps the last one.
 *
 * ES2025 source-text access - the reviver's third `context` argument, which specification section
 * 6.4 records as the confirmed mechanism for this language - solves (1) and not (2): by the time a
 * reviver sees an object its duplicate members are already gone. So the scanner below is
 * hand-written, which is what solving both at once requires.
 *
 * The reader is deliberately strict. It implements RFC 8259 JSON text and nothing else: no
 * comments, no trailing commas, no unquoted keys, no `NaN` or `Infinity` extensions.
 */

import { fail } from './errors.js';

/** A JSON number, held as the verbatim source literal. It is never parsed into a machine number. */
export interface JsonNumber {
  readonly kind: 'number';
  /** The literal exactly as it appeared in the source text. */
  readonly literal: string;
}

export interface JsonString {
  readonly kind: 'string';
  readonly value: string;
}

export interface JsonBool {
  readonly kind: 'boolean';
  readonly value: boolean;
}

export interface JsonNull {
  readonly kind: 'null';
}

export interface JsonArray {
  readonly kind: 'array';
  readonly items: readonly JsonValue[];
}

export interface JsonObject {
  readonly kind: 'object';
  /** Members in source order. Order is irrelevant to the root (specification section 3.3). */
  readonly members: readonly (readonly [string, JsonValue])[];
}

export type JsonValue = JsonNumber | JsonString | JsonBool | JsonNull | JsonArray | JsonObject;

/**
 * The observed JSON kind of a value, as the type map's output selector consumes it
 * (specification section 4.2).
 */
export type JsonKind = 'string' | 'number' | 'boolean' | 'null' | 'object' | 'array';

export function jsonKindOf(value: JsonValue): JsonKind {
  return value.kind;
}

const CHAR_TAB = 0x09;
const CHAR_LF = 0x0a;
const CHAR_CR = 0x0d;
const CHAR_SPACE = 0x20;

function isWhitespace(code: number): boolean {
  return code === CHAR_SPACE || code === CHAR_TAB || code === CHAR_LF || code === CHAR_CR;
}

function isDigit(code: number): boolean {
  return code >= 0x30 && code <= 0x39;
}

/**
 * Rejects unpaired UTF-16 surrogates (specification section 3.2).
 *
 * This runs on the decoded JS string and BEFORE anything encodes it. `Buffer.from(s, 'utf8')` and
 * `TextEncoder` both substitute U+FFFD for a lone surrogate silently, so a check placed after
 * encoding is unobservable: the replacement character is well-formed and the rejection never
 * fires. Specification section 6.1 cites dogtag's TypeScript SDK doing exactly this check for the
 * matching reason - Rust strings cannot hold a lone surrogate and JavaScript strings can, so
 * without an explicit rejection on the JavaScript side the two implementations diverge on input
 * neither should accept (`dogtag-mono-repo`, `packages/dogtag-standard-ts/src/encode.ts:14-28`).
 */
export function assertNoUnpairedSurrogate(s: string, where: string): void {
  for (let i = 0; i < s.length; i += 1) {
    const code = s.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = i + 1 < s.length ? s.charCodeAt(i + 1) : -1;
      if (next < 0xdc00 || next > 0xdfff) {
        fail('unpaired-surrogate', `unpaired high surrogate in ${where} at UTF-16 index ${i}`, {
          index: i,
        });
      }
      i += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      fail('unpaired-surrogate', `unpaired low surrogate in ${where} at UTF-16 index ${i}`, {
        index: i,
      });
    }
  }
}

class Scanner {
  private readonly text: string;
  private pos = 0;

  constructor(text: string) {
    this.text = text;
  }

  parseDocument(): JsonValue {
    this.skipWhitespace();
    const value = this.parseValue(0);
    this.skipWhitespace();
    if (this.pos !== this.text.length) {
      this.syntaxError('trailing content after the top-level value');
    }
    return value;
  }

  private syntaxError(message: string): never {
    fail('json-syntax', `${message} (at offset ${this.pos})`, { offset: this.pos });
  }

  private skipWhitespace(): void {
    while (this.pos < this.text.length && isWhitespace(this.text.charCodeAt(this.pos))) {
      this.pos += 1;
    }
  }

  private peek(): number {
    return this.pos < this.text.length ? this.text.charCodeAt(this.pos) : -1;
  }

  private parseValue(depth: number): JsonValue {
    // A depth ceiling, so a hostile document cannot exhaust the JS stack before any rule runs.
    // This is an implementation safeguard and not a canonicalization rule: the specification
    // states no nesting bound, so the limit is set far above any record shape these profiles
    // produce and a document reaching it is rejected rather than truncated.
    if (depth > 512) {
      this.syntaxError('nesting deeper than 512 levels');
    }
    const code = this.peek();
    switch (code) {
      case 0x7b: // {
        return this.parseObject(depth);
      case 0x5b: // [
        return this.parseArray(depth);
      case 0x22: // "
        return { kind: 'string', value: this.parseString() };
      case 0x74: // t
        this.expectLiteral('true');
        return { kind: 'boolean', value: true };
      case 0x66: // f
        this.expectLiteral('false');
        return { kind: 'boolean', value: false };
      case 0x6e: // n
        this.expectLiteral('null');
        return { kind: 'null' };
      default:
        return this.parseNumber();
    }
  }

  private expectLiteral(word: string): void {
    if (this.text.startsWith(word, this.pos)) {
      this.pos += word.length;
      return;
    }
    this.syntaxError(`expected the literal ${word}`);
  }

  private parseObject(depth: number): JsonObject {
    this.pos += 1; // consume '{'
    const members: (readonly [string, JsonValue])[] = [];
    const seen = new Set<string>();
    this.skipWhitespace();
    if (this.peek() === 0x7d) {
      this.pos += 1;
      return { kind: 'object', members };
    }
    for (;;) {
      this.skipWhitespace();
      if (this.peek() !== 0x22) {
        this.syntaxError('expected a quoted member name');
      }
      const key = this.parseString();
      // Specification section 3.2: duplicate keys in a map MUST be rejected at the input boundary
      // and before any hashing. The comparison is over the DECODED key, so `"a"` and `"a"`
      // are the same member. It is deliberately not over the NFC-normalized key: two keys that
      // differ only in normalization form are distinct JSON members here and become the same
      // encoded path later, which `flattenRecord` rejects as a duplicate path. Splitting the two
      // checks keeps this one a statement about the JSON document and the other a statement about
      // the leaf set.
      if (seen.has(key)) {
        fail('duplicate-key', `duplicate object member name ${JSON.stringify(key)}`, { key });
      }
      seen.add(key);
      this.skipWhitespace();
      if (this.peek() !== 0x3a) {
        this.syntaxError('expected ":" after a member name');
      }
      this.pos += 1;
      this.skipWhitespace();
      members.push([key, this.parseValue(depth + 1)] as const);
      this.skipWhitespace();
      const next = this.peek();
      if (next === 0x2c) {
        this.pos += 1;
        continue;
      }
      if (next === 0x7d) {
        this.pos += 1;
        return { kind: 'object', members };
      }
      this.syntaxError('expected "," or "}" in an object');
    }
  }

  private parseArray(depth: number): JsonArray {
    this.pos += 1; // consume '['
    const items: JsonValue[] = [];
    this.skipWhitespace();
    if (this.peek() === 0x5d) {
      this.pos += 1;
      return { kind: 'array', items };
    }
    for (;;) {
      this.skipWhitespace();
      items.push(this.parseValue(depth + 1));
      this.skipWhitespace();
      const next = this.peek();
      if (next === 0x2c) {
        this.pos += 1;
        continue;
      }
      if (next === 0x5d) {
        this.pos += 1;
        return { kind: 'array', items };
      }
      this.syntaxError('expected "," or "]" in an array');
    }
  }

  private parseString(): string {
    this.pos += 1; // consume the opening quote
    let out = '';
    for (;;) {
      if (this.pos >= this.text.length) {
        this.syntaxError('unterminated string');
      }
      const code = this.text.charCodeAt(this.pos);
      if (code === 0x22) {
        this.pos += 1;
        // Checked here rather than at encode time, for the reason on
        // `assertNoUnpairedSurrogate`: the UTF-8 encoder would have replaced it silently.
        assertNoUnpairedSurrogate(out, 'a JSON string');
        return out;
      }
      if (code === 0x5c) {
        this.pos += 1;
        out += this.parseEscape();
        continue;
      }
      if (code < 0x20) {
        // RFC 8259 section 7: an unescaped control character is not admissible in a string.
        this.syntaxError('unescaped control character in a string');
      }
      out += this.text[this.pos];
      this.pos += 1;
    }
  }

  private parseEscape(): string {
    if (this.pos >= this.text.length) {
      this.syntaxError('truncated escape sequence');
    }
    const c = this.text[this.pos];
    this.pos += 1;
    switch (c) {
      case '"':
        return '"';
      case '\\':
        return '\\';
      case '/':
        return '/';
      case 'b':
        return '\b';
      case 'f':
        return '\f';
      case 'n':
        return '\n';
      case 'r':
        return '\r';
      case 't':
        return '\t';
      case 'u': {
        if (this.pos + 4 > this.text.length) {
          this.syntaxError('truncated \\u escape');
        }
        const hex = this.text.slice(this.pos, this.pos + 4);
        if (!/^[0-9a-fA-F]{4}$/.test(hex)) {
          this.syntaxError('malformed \\u escape');
        }
        this.pos += 4;
        // The code unit is emitted as-is. Pairing is checked once, over the whole decoded
        // string, so an escaped high surrogate followed by a LITERAL low surrogate pairs
        // correctly and an escaped lone surrogate is caught.
        return String.fromCharCode(Number.parseInt(hex, 16));
      }
      default:
        this.syntaxError(`unknown escape \\${c ?? ''}`);
    }
  }

  /**
   * Scans a number and returns its source text VERBATIM.
   *
   * Nothing here converts the token to a JS number. The literal travels as a string all the way
   * to `encodeValue`, which applies the section 6.2 canonicalization on digit strings alone.
   */
  private parseNumber(): JsonNumber {
    // `NaN`, `Infinity` and `-Infinity` are not JSON, but they are the tokens a permissive reader
    // would accept and specification section 3.2 names them as states an implementation MUST
    // reject. They are given their own reason code rather than a generic syntax error, because
    // `docs/conformance-corpus.md` class 3 asserts that code.
    if (this.text.startsWith('NaN', this.pos)) {
      fail('non-finite-number', 'NaN is not an admissible value');
    }
    if (this.text.startsWith('Infinity', this.pos)) {
      fail('non-finite-number', 'Infinity is not an admissible value');
    }
    if (this.text.startsWith('-Infinity', this.pos)) {
      fail('non-finite-number', '-Infinity is not an admissible value');
    }

    const start = this.pos;
    if (this.peek() === 0x2d) {
      this.pos += 1;
    }
    if (this.peek() === 0x30) {
      this.pos += 1;
    } else if (isDigit(this.peek())) {
      while (isDigit(this.peek())) {
        this.pos += 1;
      }
    } else {
      this.pos = start;
      this.syntaxError('expected a value');
    }
    if (this.peek() === 0x2e) {
      this.pos += 1;
      if (!isDigit(this.peek())) {
        this.syntaxError('a fraction needs at least one digit');
      }
      while (isDigit(this.peek())) {
        this.pos += 1;
      }
    }
    const e = this.peek();
    if (e === 0x65 || e === 0x45) {
      this.pos += 1;
      const sign = this.peek();
      if (sign === 0x2b || sign === 0x2d) {
        this.pos += 1;
      }
      if (!isDigit(this.peek())) {
        this.syntaxError('an exponent needs at least one digit');
      }
      while (isDigit(this.peek())) {
        this.pos += 1;
      }
    }
    return { kind: 'number', literal: this.text.slice(start, this.pos) };
  }
}

/**
 * Reads JSON text into the literal-preserving value model.
 *
 * Accepts a JS string or raw bytes. Bytes are decoded as STRICT UTF-8: `TextDecoder` with
 * `fatal: true`, because the lenient decode substitutes U+FFFD for an invalid sequence and would
 * hash a document the issuer never wrote. Specification section 4.2 requires the same strictness
 * of type-map artifact bytes.
 */
export function readJson(input: string | Uint8Array): JsonValue {
  let text: string;
  if (typeof input === 'string') {
    text = input;
  } else {
    try {
      text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: false }).decode(input);
    } catch {
      fail('json-syntax', 'input is not strict UTF-8');
    }
  }
  return new Scanner(text).parseDocument();
}

/**
 * Serializes the literal-preserving model back to JSON text.
 *
 * A number is written back as its VERBATIM literal, so a record that entered as `0.010` leaves as
 * `0.010`. `JSON.stringify` cannot be used for the same reason `JSON.parse` cannot: it would have
 * to be handed a JS number.
 *
 * This is a transport writer and NOT a canonicalization. `ROAX-CANON/1` does not canonicalize JSON
 * text at all - it canonicalizes the leaf set - so nothing here sorts keys or normalizes
 * whitespace, and the root does not depend on any choice this function makes.
 */
export function writeJson(value: JsonValue, indent = 0, depth = 0): string {
  const pad = indent > 0 ? '\n' + ' '.repeat(indent * (depth + 1)) : '';
  const closePad = indent > 0 ? '\n' + ' '.repeat(indent * depth) : '';
  switch (value.kind) {
    case 'null':
      return 'null';
    case 'boolean':
      return value.value ? 'true' : 'false';
    case 'number':
      return value.literal;
    case 'string':
      return writeJsonString(value.value);
    case 'array': {
      if (value.items.length === 0) {
        return '[]';
      }
      const items = value.items.map((v) => writeJson(v, indent, depth + 1));
      return `[${pad}${items.join(`,${pad || ''}`)}${closePad}]`;
    }
    case 'object': {
      if (value.members.length === 0) {
        return '{}';
      }
      const members = value.members.map(
        ([k, v]) => `${writeJsonString(k)}:${indent > 0 ? ' ' : ''}${writeJson(v, indent, depth + 1)}`,
      );
      return `{${pad}${members.join(`,${pad || ''}`)}${closePad}}`;
    }
    default:
      return fail('json-syntax', 'unknown value kind');
  }
}

const JSON_STRING_ESCAPES: Record<string, string> = {
  '"': '\\"',
  '\\': '\\\\',
  '\b': '\\b',
  '\f': '\\f',
  '\n': '\\n',
  '\r': '\\r',
  '\t': '\\t',
};

function writeJsonString(s: string): string {
  assertNoUnpairedSurrogate(s, 'a string being written');
  let out = '"';
  for (const ch of s) {
    const escape = JSON_STRING_ESCAPES[ch];
    if (escape !== undefined) {
      out += escape;
    } else if (ch.charCodeAt(0) < 0x20) {
      out += `\\u${ch.charCodeAt(0).toString(16).padStart(4, '0')}`;
    } else {
      out += ch;
    }
  }
  return `${out}"`;
}

/**
 * Converts an ordinary JS value into the literal-preserving model.
 *
 * This exists for values that never came from JSON text - a reserved leaf's value taken from an
 * envelope field, or a fixture assembled in memory. A JS `number` is REJECTED rather than
 * converted, because by the time one exists the literal is already gone: specification section 6.4
 * forbids parsing a record number through a floating-point type, and accepting one here would let
 * a caller launder a destroyed literal into a commitment. Callers with a genuine number carry it
 * as `{kind: 'number', literal}`.
 */
export function fromJsValue(value: unknown, where = 'value'): JsonValue {
  if (value === null) {
    return { kind: 'null' };
  }
  if (typeof value === 'boolean') {
    return { kind: 'boolean', value };
  }
  if (typeof value === 'string') {
    assertNoUnpairedSurrogate(value, where);
    return { kind: 'string', value };
  }
  if (typeof value === 'number') {
    fail(
      'non-finite-number',
      `${where} is a JavaScript number, whose literal has already been destroyed; ` +
        'carry it as a verbatim literal instead (specification section 6.4)',
    );
  }
  if (typeof value === 'undefined') {
    fail('undefined-value', `${where} is undefined, which has no JSON representation`);
  }
  if (Array.isArray(value)) {
    const items: JsonValue[] = [];
    for (let i = 0; i < value.length; i += 1) {
      // A sparse-array hole reads as `undefined` and has no JSON representation
      // (specification section 3.2).
      if (!(i in value)) {
        fail('undefined-value', `${where}[${i}] is a sparse-array hole`);
      }
      items.push(fromJsValue(value[i], `${where}[${i}]`));
    }
    return { kind: 'array', items };
  }
  if (typeof value === 'object') {
    const rec = value as Record<string, unknown>;
    const members: (readonly [string, JsonValue])[] = [];
    for (const key of Object.keys(rec)) {
      assertNoUnpairedSurrogate(key, `${where} member name`);
      members.push([key, fromJsValue(rec[key], `${where}.${key}`)] as const);
    }
    return { kind: 'object', members };
  }
  fail('json-syntax', `${where} has no JSON representation`);
}
