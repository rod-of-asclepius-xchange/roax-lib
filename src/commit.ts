/**
 * Committing a record: leaves, leaf hashes and the root.
 *
 * This is the composition of sections 3.3, 7, 8 and 9.
 */

import { randomBytes } from 'node:crypto';
import { fail } from './errors.js';
import { toHex, fromHex } from './bytes.js';
import { encodePath, type Path } from './path.js';
import { leafHash, SALT_LENGTH } from './leaf.js';
import { merkleTreeHead, inclusionProof } from './tree.js';
import type { HashFunction } from './hash.js';
import type { RecordIdentity } from './reserved.js';
import { flattenRecord, leafSet, type EmptyContainerPolicy, type OrderedLeaf } from './flatten.js';
import type { TypeTagResolver } from './typemap.js';
import type { JsonValue } from './json.js';

/**
 * Draws one salt (specification section 7).
 *
 * ```
 * salt(leaf) = 16 bytes drawn from a CSPRNG, independently for every leaf
 * ```
 *
 * There is no derivation, no key derivation function, no master secret and no preimage: decision
 * D4 was ruled D4b. A salt MUST NOT be derived from record content, from the leaf's path, from
 * the record identifier, from another salt, from the issuer's signing key, or from any other
 * issuer-stable value, and MUST NOT be reused across leaves or across a reissuance.
 *
 * The 128-bit entropy floor is load-bearing: it is the only thing standing between a withheld
 * low-entropy leaf and a dictionary search (section 10.1). `node:crypto`'s `randomBytes` is the
 * platform CSPRNG; `Math.random` is not one and must never appear here.
 */
export function drawSalt(): Uint8Array {
  return new Uint8Array(randomBytes(SALT_LENGTH));
}

/** A per-leaf salt source, addressed by structured path. */
export interface SaltSource {
  /** Returns the salt for a leaf, or `undefined` if the source does not carry one. */
  saltFor(path: Path, index: number): Uint8Array | undefined;
}

/**
 * Salts addressed by explicit structured path.
 *
 * This is the shape `schemas/envelope-1.0.json` and `schemas/envelope-2.0.json` define for the
 * `salts` array, and it is what every deployed envelope uses. Specification section 7.2 rejects
 * the smaller positional encoding for an envelope on purpose: positional pairing makes
 * salt-to-leaf pairing depend on the reader reproducing the section 9 sort correctly before it
 * can read the salts at all, and a sort that is subtly wrong then yields a wrong root rather than
 * a complaint.
 */
export class PathKeyedSalts implements SaltSource {
  private readonly byEncodedPath = new Map<string, Uint8Array>();

  constructor(entries: readonly { readonly segments: Path; readonly salt: Uint8Array }[]) {
    for (const entry of entries) {
      const key = toHex(encodePath(entry.segments));
      if (this.byEncodedPath.has(key)) {
        fail('salts-duplicate-path', 'a salt set names the same path twice');
      }
      if (entry.salt.length !== SALT_LENGTH) {
        fail('salt-length', `a salt is exactly ${SALT_LENGTH} bytes`);
      }
      this.byEncodedPath.set(key, entry.salt);
    }
  }

  get size(): number {
    return this.byEncodedPath.size;
  }

  saltFor(path: Path): Uint8Array | undefined {
    return this.byEncodedPath.get(toHex(encodePath(path)));
  }
}

/**
 * Salts as a bare array in `encodePath` order.
 *
 * **Corpus carrier only.** Specification section 7.2 rules this out for an envelope, and this
 * class is used solely by the class-10 vectors, which pair positionally so that a path-keyed salt
 * set does not enumerate every path of a shipped third-party reference sample into a public
 * repository. In a corpus vector reproducing the sort IS the thing under test, so a mispairing
 * surfaces as a failed vector rather than as a silently wrong root.
 */
export class PositionalSalts implements SaltSource {
  constructor(private readonly salts: readonly Uint8Array[]) {}

  get size(): number {
    return this.salts.length;
  }

  saltFor(_path: Path, index: number): Uint8Array | undefined {
    return this.salts[index];
  }
}

/** Draws a fresh independent salt for every leaf. This is the issuance path. */
export class FreshSalts implements SaltSource {
  saltFor(): Uint8Array {
    return drawSalt();
  }
}

export interface CommitOptions {
  readonly hash: HashFunction;
  readonly resolver: TypeTagResolver;
  readonly identity: RecordIdentity;
  readonly salts: SaltSource;
  readonly emptyContainerPolicy?: EmptyContainerPolicy | undefined;
}

export interface CommittedLeaf extends OrderedLeaf {
  readonly salt: Uint8Array;
  readonly hash: Uint8Array;
}

export interface Commitment {
  readonly leaves: readonly CommittedLeaf[];
  readonly root: Uint8Array;
  /** The UNION count: record leaves plus reserved leaves (specification section 11.1). */
  readonly leafCount: number;
  auditPathFor(index: number): Uint8Array[];
}

export function commitRecord(record: JsonValue, options: CommitOptions): Commitment {
  const recordLeaves = flattenRecord(record, {
    resolver: options.resolver,
    emptyContainerPolicy: options.emptyContainerPolicy,
  });
  const ordered = leafSet(recordLeaves, options.identity);

  const committed: CommittedLeaf[] = ordered.map((leaf) => {
    const salt = options.salts.saltFor(leaf.path, leaf.index);
    if (salt === undefined) {
      fail('salt-missing-for-leaf', `no salt for the leaf at index ${leaf.index}`, {
        index: leaf.index,
      });
    }
    return {
      ...leaf,
      salt,
      hash: leafHash(options.hash, leaf.path, leaf.tag, leaf.value, salt),
    };
  });

  const hashes = committed.map((l) => l.hash);
  const root = merkleTreeHead(options.hash, hashes);
  return {
    leaves: committed,
    root,
    leafCount: committed.length,
    auditPathFor(index: number): Uint8Array[] {
      return inclusionProof(options.hash, hashes, index);
    },
  };
}

export function saltsFromHex(hexes: readonly string[]): Uint8Array[] {
  return hexes.map((h) => fromHex(h, 'salt'));
}
