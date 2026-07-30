/**
 * The error taxonomy.
 *
 * Every rejection this library performs names one of these codes.
 * The codes are the ones `corpus/conformance-corpus-1.0.json` carries in its `reject` and
 * `envelope` vectors, and they are emitted verbatim rather than mapped at the boundary.
 * `corpus/README.md` makes the reason load-bearing for an envelope vector: several fixtures are
 * rejectable for more than one cause, so a boolean alone would pass an implementation that never
 * ran the check the vector is about.
 */
export type RoaxErrorCode =
  // Section 6.2 number grammars.
  | 'integer-grammar'
  | 'decimal-grammar'
  | 'digit-bound-exceeded'
  // Section 3.2 input-boundary rejections.
  | 'non-finite-number'
  | 'duplicate-key'
  | 'unpaired-surrogate'
  | 'undefined-value'
  | 'json-syntax'
  // Section 5 path encoding.
  | 'index-out-of-32-bit-range'
  // Section 11.2 reserved-namespace guard.
  | 'reserved-namespace'
  // Section 4.2 schema binding.
  | 'type-map-fail-closed'
  | 'type-map-rejected'
  | 'profile-unknown'
  // Sections 6.1, 6.3 and 6.5 value encoding.
  | 'value-type-mismatch'
  | 'base64-not-canonical'
  | 'blob-ref-not-selectable'
  // Section 7.4 algorithm authority.
  | 'hash-alg-not-allowed'
  | 'hash-alg-unsupported'
  // Sections 7.3, 10 and 11 envelope rules.
  | 'envelope-malformed'
  | 'envelope-copy-kind'
  | 'disclosed-copy-carries-salts'
  | 'disclosed-leaf-named-without-value'
  | 'master-salt-in-envelope'
  | 'salt-missing-for-leaf'
  | 'salts-duplicate-path'
  | 'salts-length-not-leaf-count'
  | 'leaf-count-mismatch'
  | 'inclusion-proof-failed'
  | 'root-mismatch'
  | 'outer-identity-mismatch'
  | 'minimum-disclosure-floor'
  // Section 3.3 issuance floor.
  | 'record-contributes-no-leaves'
  // Section 7 salt rules.
  | 'salt-length';

/**
 * **Every rejection of INPUT is a `RoaxError` carrying one of the codes above.**
 *
 * A precondition violation by the CALLER is not, and the package has exactly one such RULE: drawing
 * an audit path for a leaf index outside the tree it was handed throws a `RangeError`. Three entry
 * points reach it - `inclusionProof` and `MerkleTree.auditPath` in `./tree.js`, and
 * `Commitment.auditPathFor` in `./commit.js`, which forwards to the second.
 * That one rule is deliberately outside this taxonomy rather than an omission from it. These codes
 * are the conformance corpus's own reason strings emitted verbatim, which is what lets an envelope
 * vector assert a REASON rather than a boolean, so minting a code here to cover a caller's bad
 * argument would spend the one property that makes the taxonomy checkable against the corpus.
 * `RangeError` is also the JavaScript idiom for an out-of-range argument.
 *
 * A consumer writing `catch (e) { if (e instanceof RoaxError) ... }` therefore handles every
 * rejection of a record, an envelope or a type map, and drops that one `RangeError`.
 */
export class RoaxError extends Error {
  readonly code: RoaxErrorCode;
  /** Optional machine-readable context. Never part of any hash preimage. */
  readonly detail: Readonly<Record<string, unknown>> | undefined;

  constructor(code: RoaxErrorCode, message: string, detail?: Record<string, unknown>) {
    super(`${code}: ${message}`);
    this.name = 'RoaxError';
    this.code = code;
    this.detail = detail;
  }
}

export function fail(
  code: RoaxErrorCode,
  message: string,
  detail?: Record<string, unknown>,
): never {
  throw new RoaxError(code, message, detail);
}
