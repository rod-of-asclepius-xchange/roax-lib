/**
 * Byte and Unicode primitives.
 *
 * `u32be`, `u64be`, `utf8` and `NFC` as specification section 1 defines them.
 */

import { fail } from './errors.js';

/** `n` as a 4-byte big-endian unsigned integer. */
export function u32be(n: number): Uint8Array {
  if (!Number.isInteger(n) || n < 0 || n > 0xffffffff) {
    fail('envelope-malformed', `${n} does not fit an unsigned 32-bit big-endian field`);
  }
  const out = new Uint8Array(4);
  out[0] = (n >>> 24) & 0xff;
  out[1] = (n >>> 16) & 0xff;
  out[2] = (n >>> 8) & 0xff;
  out[3] = n & 0xff;
  return out;
}

/**
 * `n` as an 8-byte big-endian unsigned integer.
 *
 * Accepts a `bigint` as well as a `number`, because a value length can exceed `2^53 - 1` in
 * principle and the shift arithmetic a `number` would need is not exact above that.
 */
export function u64be(n: number | bigint): Uint8Array {
  const v = typeof n === 'bigint' ? n : BigInt(n);
  if (v < 0n || v > 0xffffffffffffffffn) {
    fail('envelope-malformed', `${v} does not fit an unsigned 64-bit big-endian field`);
  }
  const out = new Uint8Array(8);
  let rest = v;
  for (let i = 7; i >= 0; i -= 1) {
    // A `BigInt` masked to one byte is exactly representable, so this narrowing is lossless. It is
    // not a numeric literal being read: the value reached here as a `bigint` and stays exact.
    out[i] = Number(rest & 0xffn);
    rest >>= 8n;
  }
  return out;
}

const ENCODER = new TextEncoder();

/**
 * UTF-8 encoding.
 *
 * `TextEncoder` substitutes U+FFFD for a lone surrogate rather than failing, so every caller
 * checks pairing BEFORE reaching here (`assertNoUnpairedSurrogate`). That ordering is the
 * requirement, not this function.
 */
export function utf8(s: string): Uint8Array {
  return ENCODER.encode(s);
}

/**
 * Unicode Normalization Form C (specification section 6.1).
 *
 * **`ROAX-CANON/1` pins Unicode 15.1, and this call is whatever the host runtime's ICU provides.**
 * On Node v22.21.0 that is ICU 77.1, which is Unicode 16.0, so a strict reading of the pin is not
 * satisfied by any stock JavaScript runtime: `String.prototype.normalize` exposes no version
 * selector and the tables are not swappable without shipping a full NFC implementation.
 *
 * The consequence is stated rather than hidden, because section 6.1 requires an implementation
 * whose tables come from a different Unicode version to say so rather than claim conformance.
 * `describeUnicodeEnvironment` below is what a conformance report carries. `corpus/README.md`
 * measures that its Node implementation agreed on every committed vector while running 16.0
 * tables, which is evidence those particular vectors are stable across that release boundary and
 * is not evidence the pin is satisfied.
 */
export function nfc(s: string): string {
  return s.normalize('NFC');
}

/** What a conformance report states about this build's normalization tables. */
export function describeUnicodeEnvironment(): {
  readonly pinnedByCanon: string;
  readonly runtimeProvides: string;
  readonly matchesPin: boolean;
} {
  // `process.versions.unicode` is the Unicode version of the bundled ICU.
  const runtime =
    (globalThis as { process?: { versions?: Record<string, string> } }).process?.versions?.[
      'unicode'
    ] ?? 'unknown';
  return {
    pinnedByCanon: '15.1',
    runtimeProvides: runtime,
    matchesPin: runtime === '15.1' || runtime === '15.1.0',
  };
}

export function concatBytes(parts: readonly Uint8Array[]): Uint8Array {
  let total = 0;
  for (const p of parts) {
    total += p.length;
  }
  const out = new Uint8Array(total);
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
}

const HEX = '0123456789abcdef';
const HEX_UPPER = '0123456789ABCDEF';

export function toHex(bytes: Uint8Array): string {
  let out = '';
  for (const b of bytes) {
    out += HEX[(b >> 4) & 0x0f];
    out += HEX[b & 0x0f];
  }
  return out;
}

/**
 * The value of one hexadecimal digit, in either case, or `-1` for anything else.
 *
 * A table lookup rather than `Number.parseInt(ch, 16)`, so that no path in this package converts
 * text to a machine number through a general-purpose numeric parser. `parseInt` is also lenient in
 * ways a decoder must not be: it stops at the first non-digit and returns what it read, so
 * `parseInt('0x', 16)` is `0` rather than an error.
 *
 * Both cases are accepted because the two callers differ: `fromHex` admits lowercase only and
 * rejects the rest before reaching here, while a JSON `\u` escape is case-insensitive by RFC 8259.
 */
export function hexNibble(ch: string): number {
  const lower = HEX.indexOf(ch);
  return lower >= 0 ? lower : HEX_UPPER.indexOf(ch);
}

export function fromHex(hex: string, where = 'value'): Uint8Array {
  if (!/^(?:[0-9a-f]{2})*$/.test(hex)) {
    fail('envelope-malformed', `${where} is not lowercase hex of even length`);
  }
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i += 1) {
    out[i] = (hexNibble(hex[i * 2] as string) << 4) | hexNibble(hex[i * 2 + 1] as string);
  }
  return out;
}

/**
 * Decodes RFC 4648 section 4 base64: standard alphabet, WITH padding, no line wrapping
 * (specification section 6.3).
 *
 * Rejects the URL-safe alphabet of section 5, absent or excess padding, any character outside the
 * alphabet including a line break, and a final quantum whose unused bits are non-zero - which RFC
 * 4648 section 3.5 identifies as the non-canonical case. Without the last check two distinct
 * texts decode to identical bytes, so an implementation that skips it accepts a second encoding of
 * the same value.
 */
const B64_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

export function decodeBase64Strict(text: string): Uint8Array {
  if (text.length % 4 !== 0) {
    fail('base64-not-canonical', 'base64 length is not a multiple of 4, so padding is not exact');
  }
  if (text.length === 0) {
    return new Uint8Array(0);
  }
  let padding = 0;
  if (text.endsWith('==')) {
    padding = 2;
  } else if (text.endsWith('=')) {
    padding = 1;
  }
  const body = text.slice(0, text.length - padding);
  if (body.includes('=')) {
    fail('base64-not-canonical', 'base64 padding appears before the end of the input');
  }
  const values: number[] = [];
  for (const ch of body) {
    const v = B64_ALPHABET.indexOf(ch);
    if (v < 0) {
      fail('base64-not-canonical', `character ${JSON.stringify(ch)} is outside the RFC 4648 section 4 alphabet`);
    }
    values.push(v);
  }
  // The final quantum's unused low bits MUST be zero (RFC 4648 section 3.5).
  if (padding === 1) {
    const last = values[values.length - 1] as number;
    if ((last & 0x03) !== 0) {
      fail('base64-not-canonical', 'the final base64 quantum carries non-zero unused bits');
    }
  } else if (padding === 2) {
    const last = values[values.length - 1] as number;
    if ((last & 0x0f) !== 0) {
      fail('base64-not-canonical', 'the final base64 quantum carries non-zero unused bits');
    }
  }
  const out = new Uint8Array((values.length * 6) >> 3);
  let bitBuffer = 0;
  let bitCount = 0;
  let at = 0;
  for (const v of values) {
    bitBuffer = (bitBuffer << 6) | v;
    bitCount += 6;
    if (bitCount >= 8) {
      bitCount -= 8;
      out[at] = (bitBuffer >> bitCount) & 0xff;
      at += 1;
    }
  }
  return out;
}
