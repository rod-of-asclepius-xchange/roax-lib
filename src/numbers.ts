/**
 * Canonical numbers (specification section 6.2).
 *
 * Arbitrary precision, held as strings, never parsed into a machine integer and never through a
 * float. No digit of a record value is ever converted to a machine number here: every operation is
 * a string or `BigInt` operation over digit sequences, and `BigInt` appears only for exponent
 * bookkeeping, where it is exact.
 *
 * **There is exactly one `Number()` in this module and it converts no literal.** It narrows the
 * already-computed `BigInt` exponent AFTER the digit bound has proved `|e| <= 1024`, which makes
 * the narrowing exact; the comment at that line states the proof. Converting the exponent literal
 * directly would be the unsafe thing, for the reason given where it is parsed - a large exponent
 * saturates to `Infinity` and turns a rejection into an unbounded allocation.
 */

import { fail } from './errors.js';

/**
 * The total-digit bound of `ROAX-CANON/1`, counting integer and fraction digits together.
 *
 * A fixed constant of the canonicalization version and NOT implementation-chosen
 * (specification section 6.2). Section 13.3 rejects RDFC-1.0 partly because an
 * implementation-chosen iteration limit makes two conformant implementations disagree about which
 * documents they will canonicalize at all, and an implementation-chosen digit limit here would be
 * that same defect.
 */
export const MAX_TOTAL_DIGITS = 1024n;

/**
 * Grammars are anchored `^...$` with `\n` excluded explicitly rather than relying on the anchor.
 *
 * JavaScript's `$` matches only at end of input, so `"1.0\n"` is rejected here without further
 * work - but the same expression in a Python-family dialect ALSO matches before a trailing
 * newline and accepts it. `corpus/README.md` records that divergence as the one the two reference
 * implementations caught, and `reject-decimal-trailing-newline` pins it. The anchors are written
 * out so a reader can see the property is intended rather than inherited from the dialect.
 */
const INTEGER_GRAMMAR = /^-?(?:0|[1-9][0-9]*)$/;
const DECIMAL_INPUT_GRAMMAR = /^(-?)(0|[1-9][0-9]*)(?:\.([0-9]+))?(?:[eE]([+-]?[0-9]+))?$/;

function assertNoLineTerminator(input: string, code: 'integer-grammar' | 'decimal-grammar'): void {
  // Defence in depth against a future edit switching to a multiline-flagged expression, and
  // against a dialect whose `$` is lenient. A newline anywhere in a numeric literal is an error.
  if (/[\n\r\u2028\u2029]/.test(input)) {
    fail(code, 'a numeric literal may not contain a line terminator');
  }
}

/**
 * Canonicalizes an INTEGER (tag 3).
 *
 * - Grammar `^-?(0|[1-9][0-9]*)$`; leading zeros are rejected.
 * - `-0` normalizes to `0`.
 *
 * The 1024-digit bound is applied here as well as to DECIMAL. **This is a stated ambiguity, not a
 * settled reading.** Specification section 6.2 places the bound under *Canonical decimal*, while
 * the paragraph justifying it counts "class 2's 40-digit integer" against it, which only makes
 * sense if it governs INTEGER too. `corpus/README.md` records the same ambiguity as its first
 * finding and notes that both reference implementations apply it to INTEGER and that no vector
 * discriminates. This implementation takes the same reading, independently, for the reason the
 * corpus gives: an unbounded INTEGER is an unbounded allocation on hostile input.
 */
export function canonicalizeInteger(input: string): string {
  assertNoLineTerminator(input, 'integer-grammar');
  if (!INTEGER_GRAMMAR.test(input)) {
    fail('integer-grammar', `not a canonical integer: ${JSON.stringify(input)}`, { input });
  }
  const negative = input.startsWith('-');
  const digits = negative ? input.slice(1) : input;
  if (BigInt(digits.length) > MAX_TOTAL_DIGITS) {
    fail(
      'digit-bound-exceeded',
      `an integer of ${digits.length} digits exceeds the ${MAX_TOTAL_DIGITS} digit bound`,
      { digits: digits.length },
    );
  }
  // A zero magnitude loses its sign. `-0` and `0` are the same value and must be the same leaf.
  if (digits === '0') {
    return '0';
  }
  return negative ? `-${digits}` : digits;
}

/**
 * Canonicalizes a DECIMAL (tag 4).
 *
 * Canonicalization does exactly two things (specification section 6.2): it expands exponent
 * notation into positional notation, and it drops the sign of a zero-valued magnitude. The digit
 * sequence is never rounded, extended or truncated to a target precision, so a trailing zero of
 * the FRACTION survives and `0.010` is not `0.01` - which FHIR R4 states as a SHALL.
 *
 * This is the line dogtag takes the other way: `dogtag-mono-repo`,
 * `crates/dogtag-standard-rs/src/encode.rs:51-59` strips trailing zeros. Porting that function
 * without changing those lines would break FHIR conformance silently.
 */
export function canonicalizeDecimal(input: string): string {
  assertNoLineTerminator(input, 'decimal-grammar');
  const m = DECIMAL_INPUT_GRAMMAR.exec(input);
  if (m === null) {
    fail('decimal-grammar', `not a canonical decimal: ${JSON.stringify(input)}`, { input });
  }
  const negative = m[1] === '-';
  const intDigits = m[2] ?? '';
  const fracDigits = m[3] ?? '';
  // Exponent digits are read with BigInt, exactly. `Number()` would saturate a large exponent to
  // Infinity and turn a rejection into an unbounded allocation.
  const e = m[4] === undefined ? 0n : BigInt(m[4]);

  const i = BigInt(intDigits.length);
  const f = BigInt(fracDigits.length);

  // The digit count of the expanded positional form, computed BEFORE materializing it so a
  // hostile exponent cannot allocate. Derived from the shift rules below:
  //   e >= 0: intLen = i + e,          fracLen = max(0, f - e)   -> total = i + max(e, f)
  //   e <  0: k = -e; if k <= i  intLen = i - k, fracLen = f + k -> total = i + f
  //                   if k >  i  intLen = 0,     fracLen = k + f -> total = k + f
  //           which is total = max(i, k) + f
  const totalDigits = e >= 0n ? i + (e > f ? e : f) : (i > -e ? i : -e) + f;

  // **What the bound counts is a stated ambiguity, and this is the literal reading.**
  // Specification section 6.2 bounds "the expanded positional form", which is taken here as the
  // padded form BEFORE the output-grammar normalization below. `corpus/README.md` records the
  // same ambiguity as its second finding: under this reading `0e99999` is rejected, and under the
  // other it canonicalizes to `0`. No committed vector carries `0e99999`, so nothing
  // discriminates. This reading is chosen for the reason the corpus gives - it is the literal one
  // and the memory-safe one - and it is pinned at the edge by `decimal-at-digit-bound` (`1e1023`,
  // 1024 digits, accepted) and `reject-decimal-just-over-digit-bound` (`1e1024`, 1025, rejected).
  if (totalDigits > MAX_TOTAL_DIGITS) {
    fail(
      'digit-bound-exceeded',
      `the expanded positional form would carry ${totalDigits} digits, ` +
        `above the ${MAX_TOTAL_DIGITS} digit bound`,
      { digits: totalDigits.toString() },
    );
  }

  // Past the bound check the shift is safe to materialize. The bound also constrains the exponent
  // itself: `totalDigits >= e` when `e >= 0` and `totalDigits >= -e` when `e < 0`, so surviving
  // the check means `|e| <= 1024` and this narrowing is exact rather than a float conversion of a
  // literal.
  const shift = Number(e);
  let intPart: string;
  let fracPart: string;
  if (shift >= 0) {
    if (shift <= fracDigits.length) {
      intPart = intDigits + fracDigits.slice(0, shift);
      fracPart = fracDigits.slice(shift);
    } else {
      // The point runs past the digits that are present, so the gap pads with `0`.
      intPart = intDigits + fracDigits + '0'.repeat(shift - fracDigits.length);
      fracPart = '';
    }
  } else {
    const k = -shift;
    if (k <= intDigits.length) {
      intPart = intDigits.slice(0, intDigits.length - k);
      fracPart = intDigits.slice(intDigits.length - k) + fracDigits;
    } else {
      intPart = '';
      fracPart = '0'.repeat(k - intDigits.length) + intDigits + fracDigits;
    }
  }

  // Normalize to the output grammar `^-?(0|[1-9][0-9]*)(\.[0-9]+)?$`.
  //
  // Leading zeros of the integer part are removed and an emptied integer part becomes a single
  // `0`. A fraction of ZERO DIGITS is dropped along with its `.`; a fraction of zero-VALUED digits
  // is not, which is the whole point - `0.010` keeps `010` and `1.00e1` keeps the `0` of `10.0`.
  let normalizedInt = intPart.replace(/^0+/, '');
  if (normalizedInt === '') {
    normalizedInt = '0';
  }
  const isZeroMagnitude = /^0*$/.test(intPart) && /^0*$/.test(fracPart);
  // A zero-valued magnitude keeps its fraction digits and loses its sign, so `-0.00` is `0.00`.
  const sign = negative && !isZeroMagnitude ? '-' : '';
  return fracPart.length === 0 ? `${sign}${normalizedInt}` : `${sign}${normalizedInt}.${fracPart}`;
}
