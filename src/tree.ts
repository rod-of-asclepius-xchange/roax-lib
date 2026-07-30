/**
 * Tree construction and inclusion proofs (specification section 9).
 *
 * RFC 9162 section 2.1.1, with the one stated adaptation of section 9.1: the `0x00` leaf-domain
 * byte is already applied inside `leafHash`, so this tree operates on ALREADY-HASHED leaves and
 * MUST NOT apply it a second time.
 *
 * ```
 * MTH([])      = H("")            // total function only; unreachable in a conforming implementation
 * MTH([x])     = x                // NOT H(0x00 ‖ x)
 * MTH(L), n>1  = H(0x01 ‖ MTH(L[0:k]) ‖ MTH(L[k:n]))
 *                where k is the largest power of two strictly smaller than n
 * ```
 */

import { concatBytes } from './bytes.js';
import { compareBytes } from './path.js';
import type { HashFunction } from './hash.js';

/**
 * The largest power of two strictly smaller than `n`, for `n > 1`.
 *
 * This is the RFC 9162 split rule and it is where a hand-rolled tree goes wrong, because it goes
 * wrong only at non-power-of-two sizes. `docs/conformance-corpus.md` class 8 therefore mandates
 * the leaf counts 1, 2, 3, 5, 7, 8, 9 and 130 rather than only powers of two.
 */
export function splitPoint(n: number): number {
  let k = 1;
  while (k * 2 < n) {
    k *= 2;
  }
  return k;
}

/**
 * A tree whose subtree heads are computed ONCE and shared by every audit path drawn from it.
 *
 * The heads are addressed by the half-open leaf range `[lo, hi)` they cover, which is the same
 * addressing the `MTH` recursion above already uses, so the value cached under a range is
 * byte-identical to the one a fresh `MTH` over that range would produce. Every sibling an audit
 * path needs is itself a node of this tree, so the descent below reads the cache the root
 * computation already filled and hashes nothing further.
 *
 * That matters because `discloseFrom` draws one audit path per revealed leaf. Recomputing each
 * sibling subtree from scratch makes a single path cost `O(n)` hashes and a fully disclosed record
 * `O(n^2)`, which the 130-leaf ceiling of the committed corpus does not measure and a real FHIR
 * bundle would.
 */
export interface MerkleTree {
  readonly size: number;
  readonly root: Uint8Array;
  /**
   * The RFC 9162 section 2.1.3.1 audit path for `index`, from the leaf outwards.
   *
   * Throws a `RangeError` for an index outside the tree, for the reason `inclusionProof` states.
   */
  auditPath(index: number): Uint8Array[];
}

export function buildMerkleTree(hash: HashFunction, leaves: readonly Uint8Array[]): MerkleTree {
  const size = leaves.length;
  const heads = new Map<number, Uint8Array>();

  const head = (lo: number, hi: number): Uint8Array => {
    if (hi - lo === 1) {
      // `MTH([x]) = x`, NOT `H(0x00 ‖ x)`: the leaf-domain byte is already inside `leafHash`.
      return leaves[lo] as Uint8Array;
    }
    const key = lo * (size + 1) + hi;
    const cached = heads.get(key);
    if (cached !== undefined) {
      return cached;
    }
    const k = lo + splitPoint(hi - lo);
    const computed = hash.hash(
      concatBytes([
        Uint8Array.of(0x01), // RFC 9162 internal-node domain byte.
        head(lo, k),
        head(k, hi),
      ]),
    );
    heads.set(key, computed);
    return computed;
  };

  // Unreachable in a conforming implementation: the leaf set is the union of specification
  // section 3.3, which always carries the reserved leaves, so `L` is never empty and its length is
  // never below 6. The branch exists only so the function is total, which is easier to port than
  // one with an undefined case.
  const root = size === 0 ? hash.hash(new Uint8Array(0)) : head(0, size);

  return {
    size,
    root,
    auditPath(index: number): Uint8Array[] {
      if (!Number.isInteger(index) || index < 0 || index >= size) {
        throw new RangeError(`leaf index ${index} is outside a tree of ${size} leaves`);
      }
      const path: Uint8Array[] = [];
      let lo = 0;
      let hi = size;
      while (hi - lo > 1) {
        const k = lo + splitPoint(hi - lo);
        if (index < k) {
          path.push(head(k, hi));
          hi = k;
        } else {
          path.push(head(lo, k));
          lo = k;
        }
      }
      // The descent runs root-first and `verifyInclusion` consumes the path leaf-first.
      return path.reverse();
    },
  };
}

export function merkleTreeHead(hash: HashFunction, leaves: readonly Uint8Array[]): Uint8Array {
  return buildMerkleTree(hash, leaves).root;
}

/**
 * The RFC 9162 section 2.1.3 audit path for the leaf at `index` in a tree of `leaves`.
 *
 * Ordered from the leaf outwards, which is the order `verifyInclusion` consumes.
 *
 * **Throws a `RangeError`, not a `RoaxError`, for an index outside the tree.** That is the one
 * throw in this package outside the error taxonomy, because an out-of-range argument is a caller
 * precondition violation rather than a rejection of record input; `./errors.js` gives the full
 * reasoning. A consumer catching only `RoaxError` does not catch this. The range is checked before
 * the tree is built, so an out-of-range call hashes nothing.
 *
 * A caller drawing MORE than one path over the same leaves should hold a `MerkleTree` from
 * `buildMerkleTree` instead, which shares the subtree heads across paths.
 */
export function inclusionProof(
  hash: HashFunction,
  leaves: readonly Uint8Array[],
  index: number,
): Uint8Array[] {
  if (!Number.isInteger(index) || index < 0 || index >= leaves.length) {
    throw new RangeError(`leaf index ${index} is outside a tree of ${leaves.length} leaves`);
  }
  return buildMerkleTree(hash, leaves).auditPath(index);
}

/**
 * Verifies an RFC 9162 section 2.1.3.2 inclusion proof.
 *
 * **This is a fold primitive and it proves nothing on its own.** It trusts the `leafHash` it is
 * handed, exactly as dogtag documents of its own `process_proof` (`dogtag-mono-repo`,
 * `crates/dogtag-standard-rs/src/merkle.rs:86-91`). Specification section 10 step 2 is what makes
 * it meaningful: a verifier RECOMPUTES the leaf hash from the disclosed path, tag, value and salt
 * and never accepts one. `verifyDisclosedCopy` is the caller that does that; nothing else in this
 * library calls this function with a supplied hash.
 *
 * `treeSize` is an INPUT here, not something the algorithm recovers. Specification section 11.1
 * records the measurement: an attacker supplying both a leaf hash and a forged tree size can walk
 * an internal node to the genuine root, so `leafCount` is NOT authenticated in a disclosed copy.
 */
export function verifyInclusion(
  hash: HashFunction,
  leafHashValue: Uint8Array,
  index: number,
  treeSize: number,
  auditPath: readonly Uint8Array[],
  root: Uint8Array,
): boolean {
  if (!Number.isInteger(index) || !Number.isInteger(treeSize)) {
    return false;
  }
  if (treeSize < 1 || index < 0 || index >= treeSize) {
    return false;
  }
  if (leafHashValue.length !== hash.digestLength) {
    return false;
  }
  for (const sibling of auditPath) {
    if (sibling.length !== hash.digestLength) {
      return false;
    }
  }

  // RFC 9162 section 2.1.3.2, written iteratively over the audit path from the leaf outwards.
  let fn = index;
  let sn = treeSize - 1;
  let r = leafHashValue;
  let consumed = 0;
  while (sn > 0) {
    if (consumed >= auditPath.length) {
      // A truncated audit path. The RFC's algorithm demands another sibling here.
      return false;
    }
    const sibling = auditPath[consumed] as Uint8Array;
    consumed += 1;
    if (fn % 2 === 1 || fn === sn) {
      r = hash.hash(concatBytes([Uint8Array.of(0x01), sibling, r]));
      while (fn % 2 === 0 && fn !== 0) {
        fn = Math.floor(fn / 2);
        sn = Math.floor(sn / 2);
      }
    } else {
      r = hash.hash(concatBytes([Uint8Array.of(0x01), r, sibling]));
    }
    fn = Math.floor(fn / 2);
    sn = Math.floor(sn / 2);
  }
  // An EXTENDED audit path is rejected rather than ignored: leftover siblings mean the proof does
  // not describe this tree size, and accepting them would let an attacker append freely.
  if (consumed !== auditPath.length) {
    return false;
  }
  return compareBytes(r, root) === 0;
}
