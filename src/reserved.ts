/**
 * Reserved leaves and the reserved-namespace guard (specification section 11.2).
 *
 * The envelope fields that say what a record IS are committed INSIDE the root as ordinary leaves.
 * They are salted per section 7, hashed per section 8, and sorted into the same order as record
 * leaves per section 9. Nothing about them is special-cased except where they come from.
 */

import { fail } from './errors.js';
import { ORDERING_DEFAULT, resolveOrdering, type Ordering } from './hash.js';
import { nfc } from './bytes.js';
import { isKeySegment, type Path } from './path.js';
import { TypeTag, type TypeTagValue } from './value.js';

/**
 * **Each reserved path is a SINGLE `KEY` segment whose key is the literal dotted string.**
 *
 * `roax.recordType` is one segment `KEY("roax.recordType")`, not two segments `KEY("roax")` then
 * `KEY("recordType")`. Under section 5 the name could otherwise legally encode as three segments,
 * as two, or as one key containing dots, and each produces a different root.
 */
export const RESERVED_PATHS = {
  recordType: 'roax.recordType',
  schemaVersion: 'roax.schemaVersion',
  typeMapId: 'roax.typeMap.id',
  recordId: 'roax.recordId',
  issuerId: 'roax.issuer.id',
  issuerKeyId: 'roax.issuer.keyId',
  ordering: 'roax.ordering',
} as const;

/** The ASCII prefix the guard tests for. */
export const RESERVED_PREFIX = 'roax.';

/** The identity an envelope commits as reserved leaves. */
export interface RecordIdentity {
  readonly recordType: string;
  readonly schemaVersion: string;
  readonly recordId: string;
  readonly issuerId: string;
  /**
   * The exact type-map artifact ID, committed at `roax.typeMap.id`.
   *
   * REQUIRED by specification section 11.2 and by `schemas/envelope-2.0.json`, and OPTIONAL here
   * because `schemas/envelope-1.0.json` predates the binding and still governs every envelope
   * issued under it, including all 54 committed corpus fixtures. Absent means NO LEAF, exactly as
   * for `issuerKeyId`: it is not emitted as a NULL leaf or as an empty string, because those are
   * different roots and only one of them can be right. `issueEnvelope` requires it; the
   * verification path derives its expectation from the envelope in hand.
   */
  readonly typeMapId?: string | undefined;
  /**
   * The issuing key identifier, committed at `roax.issuer.keyId`.
   *
   * The FIRST of the two CONDITIONAL reserved leaves; `ordering` below is the second. An absent
   * `keyId` emits no leaf, so with both conditionals in play the reserved leaf count is 5, 6 or 7
   * under `schemas/envelope-2.0.json` and 4, 5 or 6 under `schemas/envelope-1.0.json`.
   */
  readonly issuerKeyId?: string | undefined;
  /**
   * The record's leaf ordering, committed at `roax.ordering` (specification section 11.2).
   *
   * The SECOND conditional reserved leaf. It is emitted only when the ordering is not the default
   * `path`; a path-ordered record emits NO ordering leaf and must not emit `"path"`, a NULL or an
   * empty string in its place, because those are different roots and only one can be right. The
   * conditionality is the same `ROAX-CANON/1` compatibility rule that gives `path` an empty domain
   * suffix, and section 11.2 argues it rather than leaving it to be reverse-engineered.
   *
   * THIS LEAF IS NOT AUTHORITY. It is written from the ordering supplied here and is never read
   * back to select one: a verifier takes the ordering from the anchoring registry (section 9.5,
   * H2). Section 11.2 argues why committing it is not section 7.4's rejected `roax.hashAlg` leaf
   * under a new name - weak hash algorithms exist so that leaf enabled a downgrade, whereas both
   * orderings are equally strong, so this one is redundant rather than dangerous and what it buys
   * is committed issuer intent.
   */
  readonly ordering?: Ordering | undefined;
}

export interface ReservedLeafSpec {
  readonly path: Path;
  readonly tag: TypeTagValue;
  readonly value: string;
}

/**
 * The reserved leaves an identity emits, in table order.
 *
 * Every reserved leaf is a STRING, so every value is normalized to NFC and encoded per section
 * 6.1 like any other string. Order here is irrelevant: the union is sorted by encoded path in
 * section 9 before any hashing of the tree.
 */
export function reservedLeaves(identity: RecordIdentity): ReservedLeafSpec[] {
  const out: ReservedLeafSpec[] = [
    { path: [{ key: RESERVED_PATHS.recordType }], tag: TypeTag.STRING, value: identity.recordType },
    {
      path: [{ key: RESERVED_PATHS.schemaVersion }],
      tag: TypeTag.STRING,
      value: identity.schemaVersion,
    },
  ];
  if (identity.typeMapId !== undefined) {
    out.push({
      path: [{ key: RESERVED_PATHS.typeMapId }],
      tag: TypeTag.STRING,
      value: identity.typeMapId,
    });
  }
  out.push(
    { path: [{ key: RESERVED_PATHS.recordId }], tag: TypeTag.STRING, value: identity.recordId },
    { path: [{ key: RESERVED_PATHS.issuerId }], tag: TypeTag.STRING, value: identity.issuerId },
  );
  if (identity.issuerKeyId !== undefined) {
    out.push({
      path: [{ key: RESERVED_PATHS.issuerKeyId }],
      tag: TypeTag.STRING,
      value: identity.issuerKeyId,
    });
  }
  if (resolveOrdering(identity.ordering ?? ORDERING_DEFAULT) !== ORDERING_DEFAULT) {
    out.push({
      path: [{ key: RESERVED_PATHS.ordering }],
      tag: TypeTag.STRING,
      value: identity.ordering as string,
    });
  }
  return out;
}

/**
 * The reserved paths that are MANDATORY to disclose, for the identity actually committed.
 *
 * Specification section 10.2 names five. `roax.typeMap.id` is one of them and is present here
 * only when the record committed it, because a floor demanding a path the root does not carry
 * rejects every conforming disclosed copy under `schemas/envelope-1.0.json`.
 *
 * `roax.issuer.keyId` is deliberately NOT in this set even when committed. Requiring it would
 * permanently bind an anchored record to the key it was issued under, leaving a holder whose
 * issuer has rotated keys with no path to verify - which is the foreclosure specification section
 * 12.2 rules out. Section 10.2 says so in the place an editor would otherwise widen it back.
 */
export function mandatoryReservedPaths(identity: RecordIdentity): Path[] {
  const paths: Path[] = [
    [{ key: RESERVED_PATHS.recordType }],
    [{ key: RESERVED_PATHS.schemaVersion }],
  ];
  if (identity.typeMapId !== undefined) {
    paths.push([{ key: RESERVED_PATHS.typeMapId }]);
  }
  paths.push([{ key: RESERVED_PATHS.recordId }], [{ key: RESERVED_PATHS.issuerId }]);
  return paths;
}

/**
 * The reserved-namespace guard (specification section 11.2).
 *
 * > No record-supplied path may have, as its FIRST segment, a `KEY` whose NFC-normalized key
 * > begins with the ASCII prefix `roax.`.
 *
 * Three ways to get this wrong, and each is guarded against explicitly here:
 *
 * 1. **Running it over a rendered display path.** Section 5.2 forbids reasoning over display
 *    paths, and a guard that reconstructs `a.b[0].c` to test it is doing exactly that. This
 *    function takes segments and never renders one.
 * 2. **Applying it to every segment rather than the first.** `[KEY("a"), KEY("roax.foo")]`
 *    differs from every reserved path in SEGMENT COUNT and cannot collide with one, so rejecting
 *    it is over-broad. This is the most likely over-implementation.
 * 3. **Checking the bytes as received rather than the NFC form.** Section 6.1 normalizes keys
 *    before they are encoded and hashed, so a check on the raw bytes checks a different string
 *    from the one that gets committed.
 *
 * A key named `roax`, or `roaxX`, with no dot, is ACCEPTED: no reserved path is the bare segment
 * `KEY("roax")`, so it collides with nothing.
 *
 * **The normalization half of this MUST is currently unobservable**, and that is a fact about
 * today's prefix rather than about the design: no character normalizes into `roax.`, so for every
 * input a record can supply, checking before or after normalization gives the same verdict
 * (specification section 11.2, `docs/conformance-corpus.md` class 15). The order is written the
 * required way anyway, because the property that has to hold is that this guard and the hashing
 * path reason about the same string.
 */
export function assertRecordPathAllowed(path: Path): void {
  const first = path[0];
  if (first === undefined || !isKeySegment(first)) {
    return;
  }
  if (nfc(first.key).startsWith(RESERVED_PREFIX)) {
    fail(
      'reserved-namespace',
      `a record path may not begin with the reserved key prefix ${JSON.stringify(RESERVED_PREFIX)}: ` +
        JSON.stringify(first.key),
      { key: first.key },
    );
  }
}
