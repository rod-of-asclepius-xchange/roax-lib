/**
 * Path encoding (specification section 5).
 *
 * A path is a sequence of typed segments. There are no reserved characters and no escaping: the
 * length prefix does the work an escaping rule would otherwise do, so a nested `a.b` and a literal
 * dotted key `"a.b"` are provably distinct with no rejection rule at all (section 5.1).
 *
 * The display form lives here too, and it is NEVER hashed. `displayPath` produces it; nothing in
 * this library consumes it. Section 5.2 forbids reconstructing an encoded path by parsing a
 * display path, and there is deliberately no parser for one in this module.
 */

import { fail } from './errors.js';
import { nfc, utf8, u32be } from './bytes.js';
import { assertNoUnpairedSurrogate } from './json.js';

export interface KeySegment {
  readonly key: string;
}

export interface IndexSegment {
  readonly index: number;
}

export type PathSegment = KeySegment | IndexSegment;

/** A path, as the sequence of segments that is the only authoritative representation. */
export type Path = readonly PathSegment[];

export function isKeySegment(s: PathSegment): s is KeySegment {
  return Object.prototype.hasOwnProperty.call(s, 'key');
}

/** `2^32`. An index MUST be strictly below this (specification section 5). */
const INDEX_CEILING = 4294967296;

/**
 * Encodes a path (specification section 5).
 *
 * ```
 * encodePath(segments) =
 *     u32be(count(segments))
 *   ‖ for each segment:
 *       KEY(k)   ->  0x01 ‖ u32be(len(utf8(NFC(k)))) ‖ utf8(NFC(k))
 *       INDEX(i) ->  0x02 ‖ u32be(i)
 * ```
 *
 * The KEY length prefix counts the UTF-8 BYTES of the NORMALIZED key, not its code points and not
 * its UTF-16 code units. Those three differ for every non-ASCII key.
 */
export function encodePath(segments: Path): Uint8Array {
  const parts: Uint8Array[] = [u32be(segments.length)];
  for (const segment of segments) {
    if (isKeySegment(segment)) {
      assertNoUnpairedSurrogate(segment.key, 'a path key');
      const bytes = utf8(nfc(segment.key));
      parts.push(Uint8Array.of(0x01), u32be(bytes.length), bytes);
    } else {
      const i = segment.index;
      if (!Number.isInteger(i) || i < 0) {
        fail('index-out-of-32-bit-range', `array index ${i} is not a non-negative integer`, {
          index: i,
        });
      }
      // Section 5: indices MUST be `< 2^32`, and an implementation that cannot represent one in
      // 32 bits MUST error rather than truncate. `u32be` would wrap silently.
      if (i >= INDEX_CEILING) {
        fail('index-out-of-32-bit-range', `array index ${i} is not below 2^32`, { index: i });
      }
      parts.push(Uint8Array.of(0x02), u32be(i));
    }
  }
  return concatBytes(parts);
}

function concatBytes(parts: readonly Uint8Array[]): Uint8Array {
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

/**
 * The human-readable form, `a.b[0].c`.
 *
 * Display only. It is not an input to any hash, and it is not parsed back: specification section
 * 5.2 states both halves, and `corpus/README.md` records that a minimum-disclosure floor written
 * in this notation is silently unenforced because the dotted string matches no leaf a record has.
 *
 * The form is lossy by construction - a key containing `.`, `[` or `]` renders ambiguously - and
 * that is exactly why it never round-trips.
 */
export function displayPath(segments: Path): string {
  let out = '';
  for (const segment of segments) {
    if (isKeySegment(segment)) {
      out += out === '' ? segment.key : `.${segment.key}`;
    } else {
      out += `[${segment.index}]`;
    }
  }
  return out;
}

/** Unsigned byte comparison, which is the ordering specification section 9 pins. */
export function compareBytes(a: Uint8Array, b: Uint8Array): number {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i += 1) {
    const x = a[i] as number;
    const y = b[i] as number;
    if (x !== y) {
      return x < y ? -1 : 1;
    }
  }
  if (a.length === b.length) {
    return 0;
  }
  return a.length < b.length ? -1 : 1;
}
