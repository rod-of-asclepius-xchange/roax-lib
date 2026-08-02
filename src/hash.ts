/**
 * The hash function, and the domain string it is bound into.
 *
 * `ROAX-CANON/1` is hash-agile and DEFINES the construction for `SHA-256` only
 * (specification section 7.4).
 */

import { createHash } from 'node:crypto';
import { fail } from './errors.js';
import { utf8 } from './bytes.js';

/** Algorithms the envelope schema registers. Registered is not the same as issuable. */
export type HashAlgName = 'SHA-256' | 'Poseidon-BN254';

export interface HashFunction {
  readonly name: HashAlgName;
  /** The digest length in bytes, which fixes the leaf and node width. */
  readonly digestLength: number;
  hash(input: Uint8Array): Uint8Array;
}

const SHA256: HashFunction = {
  name: 'SHA-256',
  digestLength: 32,
  hash(input: Uint8Array): Uint8Array {
    return new Uint8Array(createHash('sha256').update(input).digest());
  },
};

/**
 * Resolves a hash algorithm name to its construction.
 *
 * `Poseidon-BN254` is REGISTERED and has no defined construction: the field, the rate and
 * capacity, the round constants and the encoding from a length-prefixed byte string to field
 * elements are all unpinned, and specification section 7.4 states normatively that a record MUST
 * NOT be issued against it until a revision pins them. Rejecting it here rather than omitting it
 * from a lookup table is deliberate, so the reason a caller sees names the actual state of the
 * specification instead of reading as an unknown identifier.
 */
export function resolveHashFunction(name: string): HashFunction {
  if (name === 'SHA-256') {
    return SHA256;
  }
  if (name === 'Poseidon-BN254') {
    fail(
      'hash-alg-unsupported',
      'Poseidon-BN254 is registered but its parameterization is not pinned by ROAX-CANON/1, ' +
        'so a record MUST NOT be issued against it (specification section 7.4)',
    );
  }
  fail('hash-alg-unsupported', `unknown hash algorithm ${JSON.stringify(name)}`);
}

/**
 * `DOMAIN = "ROAX-CANON/1/" ‖ hashAlg` (specification sections 7 and 8).
 *
 * It is ALGORITHM-QUALIFIED rather than a bare `ROAX-CANON/1`, and section 7.4 is honest that
 * this buys almost nothing cryptographically: an attacker computing a whole record under a weak
 * algorithm computes the domain string under it too. What it does buy is the removal of
 * cross-algorithm root ambiguity by construction.
 *
 * `hashAlg` is NOT a leaf and must never become one. A leaf is hashed under the algorithm it
 * names, so it cannot bind it; authority comes from the anchoring registry (section 7.4, H2) and
 * the verifier's own allow-list (H3).
 */
export const CANON_VERSION = 'ROAX-CANON/1';

/**
 * Leaf ordering, selected per record (specification section 9).
 *
 * Two first-class options, exactly as decision B makes ZK-friendly and non-ZK hashes both
 * first-class and selectable per record. The amended decision D5 rules ordering the same kind of
 * axis. `path` is the DEFAULT and every one of the five libraries defaults to it, which is what
 * section 9 requires: a default that differed between implementations would be the silent
 * divergence this project exists to prevent.
 */
export type Ordering = 'path' | 'hash';

export const ORDERING_DEFAULT: Ordering = 'path';

/**
 * The domain suffix each ordering contributes to `DOMAIN` (specification sections 8 and 9).
 *
 * The asymmetry is a stated compatibility rule rather than an accident, and section 9.5 argues
 * it: `path` contributes the EMPTY string so that a path-ordered record's domain string is
 * byte-identical to what `ROAX-CANON/1` specified before this axis existed. Giving `path` a
 * non-empty suffix would change every leaf hash of every record already issued under that name.
 * Read the suffix from this table; never derive it from the ordering's name.
 */
export const ORDERING_DOMAIN_SUFFIX: Readonly<Record<Ordering, string>> = {
  path: '',
  hash: '/hash',
};

/**
 * Fail closed on an unregistered ordering rather than falling back to the default.
 *
 * This is also H3 of section 9.5 at its narrowest: an ordering absent from what this library
 * defines is refused rather than approximated.
 */
export function resolveOrdering(ordering: string): Ordering {
  if (ordering !== 'path' && ordering !== 'hash') {
    fail('ordering-not-defined', `ROAX-CANON/1 defines no leaf ordering named ${ordering}`);
  }
  return ordering;
}

/**
 * `DOMAIN`, which is algorithm-qualified AND ordering-qualified (specification section 8).
 *
 * One string with one length prefix, not two components: `ORD` is part of the domain string.
 */
export function domainString(hashAlg: HashAlgName, ordering: Ordering = ORDERING_DEFAULT): Uint8Array {
  return utf8(`${CANON_VERSION}/${hashAlg}${ORDERING_DOMAIN_SUFFIX[resolveOrdering(ordering)]}`);
}
