/**
 * Shared harness for the conformance runner.
 *
 * The runner consumes `corpus/conformance-corpus-1.0.json` and the fixtures it references, and
 * reports per class. It is a TEST HARNESS and not part of the library: nothing under `src/`
 * imports it.
 *
 * The vector file itself is read with `JSON.parse`, deliberately and safely. Every value carrier
 * in `schemas/conformance-corpus-1.0.json` refs `carrierValue`, which makes a JSON number
 * unrepresentable at any depth, so no committed VALUE travels as a number. What does travel as a
 * number is structural - `leafCount`, `index`, `treeSize`, `class`, and the deliberate
 * `{"$segments": [{"index": 4294967296}]}` of `reject-index-at-2-32` - and every one of those is
 * an exact integer well inside `Number.MAX_SAFE_INTEGER`. RECORD and ENVELOPE fixtures are a
 * different matter and are read with the library's own literal-preserving reader, because those
 * carry `0.010`.
 */

import { readFileSync } from 'node:fs';
import { RoaxError } from '../src/errors.js';

export interface ClassResult {
  passed: number;
  failed: number;
  skipped: number;
  readonly failures: string[];
  readonly notes: string[];
}

export class Report {
  private readonly classes = new Map<number, ClassResult>();

  private forClass(cls: number): ClassResult {
    let r = this.classes.get(cls);
    if (r === undefined) {
      r = { passed: 0, failed: 0, skipped: 0, failures: [], notes: [] };
      this.classes.set(cls, r);
    }
    return r;
  }

  pass(cls: number): void {
    this.forClass(cls).passed += 1;
  }

  fail(cls: number, what: string): void {
    const r = this.forClass(cls);
    r.failed += 1;
    r.failures.push(what);
  }

  skip(cls: number, why: string): void {
    const r = this.forClass(cls);
    r.skipped += 1;
    if (!r.notes.includes(why)) {
      r.notes.push(why);
    }
  }

  note(cls: number, text: string): void {
    const r = this.forClass(cls);
    if (!r.notes.includes(text)) {
      r.notes.push(text);
    }
  }

  entries(): [number, ClassResult][] {
    return [...this.classes.entries()].sort((a, b) => a[0] - b[0]);
  }

  get totalFailed(): number {
    let n = 0;
    for (const r of this.classes.values()) {
      n += r.failed;
    }
    return n;
  }

  get totalPassed(): number {
    let n = 0;
    for (const r of this.classes.values()) {
      n += r.passed;
    }
    return n;
  }

  get totalSkipped(): number {
    let n = 0;
    for (const r of this.classes.values()) {
      n += r.skipped;
    }
    return n;
  }
}

/** Runs `body` and reports pass or fail against an expected value, comparing with `===`. */
export function expectEqual(
  report: Report,
  cls: number,
  name: string,
  actual: unknown,
  expected: unknown,
): void {
  if (actual === expected) {
    report.pass(cls);
  } else {
    report.fail(cls, `${name}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

/**
 * Reference reason codes this library spells differently, and the measurement behind each.
 *
 * **A corpus `reason` is the REFERENCE implementations' spelling, not a normative code**, and
 * every reject vector agreed with this library's spelling until the record-shaped reject vectors
 * of the 2026-07-30 type rulings arrived. Those are the first whose reason is a FAIL-CLOSED, and
 * the four implementations name that one condition four ways:
 * `corpus/tools/roax_ref.py` and `roax_ref.mjs` say `type-map-uncovered-path`, this library says
 * `type-map-fail-closed`, `python/src/roax_canon/errors.py` says `type-unresolved`, and
 * `rust/src/error.rs` says `type-map-fail-closed`. `corpus/README.md` records that divergence.
 *
 * This table is therefore a DECLARED equivalence and not a way to pass: it maps one reference
 * code to the one local code that means the same condition, so a rejection for a DIFFERENT reason
 * still fails. Adding an entry is a claim that the two codes name one condition, and it belongs
 * beside the measurement rather than inside a comparison.
 */
const REFERENCE_REASON_ALIASES: ReadonlyMap<string, string> = new Map([
  ['type-map-uncovered-path', 'type-map-fail-closed'],
]);

/** Asserts that `body` throws a `RoaxError` whose code equals `reason` or its declared alias. */
export function expectReject(
  report: Report,
  cls: number,
  name: string,
  reason: string,
  body: () => unknown,
): void {
  let threw: unknown;
  try {
    body();
  } catch (e) {
    threw = e;
  }
  if (threw === undefined) {
    report.fail(cls, `${name}: expected rejection ${reason}, but the input was accepted`);
    return;
  }
  if (!(threw instanceof RoaxError)) {
    report.fail(cls, `${name}: threw a non-RoaxError: ${String(threw)}`);
    return;
  }
  const expected = REFERENCE_REASON_ALIASES.get(reason) ?? reason;
  if (threw.code !== expected) {
    const alias = expected === reason ? '' : ` (this library's spelling of ${reason})`;
    report.fail(cls, `${name}: expected reason ${expected}${alias}, got ${threw.code}`);
    return;
  }
  report.pass(cls);
}

export function readTextFile(path: string): string {
  return readFileSync(path, 'utf8');
}

export function readJsonFileLoose(path: string): unknown {
  return JSON.parse(readFileSync(path, 'utf8')) as unknown;
}

/**
 * The corpus's three input escape forms (`corpus/README.md`).
 *
 * `{"$utf16": [...]}` is how an unpaired surrogate is carried, because a conforming JSON writer
 * cannot emit one as well-formed UTF-8.
 */
export function decodeUtf16Escape(v: unknown): string | undefined {
  if (typeof v === 'object' && v !== null && '$utf16' in v) {
    const units = (v as { $utf16: unknown }).$utf16;
    if (Array.isArray(units)) {
      return String.fromCharCode(...units.map((u) => Number.parseInt(String(u), 16)));
    }
  }
  return undefined;
}

export function isEscapeObject(v: unknown, key: '$utf16' | '$segments' | '$jsonText'): boolean {
  return typeof v === 'object' && v !== null && key in v;
}
